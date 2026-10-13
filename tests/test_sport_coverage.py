import json
import os
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from lfm.analysis import eleven, fixtures, points


def test_eleven_targets_one_week_and_combines_official_unavailability(monkeypatch):
    strength = {"easy": fixtures.Strength(1, 1.5, 7), "hard": fixtures.Strength(1, 0.7, 7)}
    games = [
        fixtures.Fixture(8, "club", "easy", True, 1, 1, 0.3),
        fixtures.Fixture(9, "club", "hard", False, 1, 1, 0.3),
    ]

    def load(conn, *, limit_weeks):
        return strength, 1.5, {"club": games[:limit_weeks]}

    monkeypatch.setattr(eleven.fx_mod, "load", load)
    monkeypatch.setattr(eleven.pts_mod, "load", lambda _, **kw: ({"a": [6, 6, 6]}, {3: 4}))
    monkeypatch.setattr(eleven.pts_mod, "availability", lambda _: {"a": {"start_prob": 0.8}})

    class Conn:
        def execute(self, _):
            return [
                SimpleNamespace(player_id="a", name="A", position_id=3, club_id="club", status="suspended")
            ]

    [pick] = eleven.picks_from(Conn())
    assert pick.xpts == pytest.approx(
        points.expected([6, 6, 6], 3, games[:1], {3: 4}, 1.5, strength, 0.8).xpts
    )
    assert pick.xpts != pytest.approx(points.expected([6, 6, 6], 3, games, {3: 4}, 1.5, strength, 0.8).xpts)
    assert pick.suspended and eleven.best([pick]) is None


def test_refresh_reuses_captured_actual_lineup_without_external_api(monkeypatch):
    payload = [1]

    class Conn:
        def execute(self, sql, params):
            assert sql is eleven.SQL_CURRENT_CAPTURE
            assert params["endpoint"] == "%/teams/my-team/lineup"
            return SimpleNamespace(scalar=lambda: payload)

    saved = []
    monkeypatch.setattr(eleven, "save", lambda conn, **kw: saved.append(kw) or {"formation": "4-4-2"})
    assert eleven.refresh(Conn(), team_id="my-team", day=date(2026, 10, 9)) == {"formation": "4-4-2"}
    assert saved[0]["current"] == {"1"}


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="Requiere Postgres de pruebas")
def test_scoped_points_preserve_global_means_and_actual_lineup_ids():
    engine = create_engine(os.environ["TEST_POSTGRES_URL"])
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TEMP TABLE players(player_id text,position_id int) ON COMMIT DROP"))
            conn.execute(
                text("CREATE TEMP TABLE player_week_stats(player_id text,total_points int) ON COMMIT DROP")
            )
            conn.execute(
                text(
                    "CREATE TEMP TABLE raw_snapshots(source text,endpoint text,payload jsonb,"
                    "fetched_at timestamptz) ON COMMIT DROP"
                )
            )
            conn.execute(text("INSERT INTO players VALUES ('a',3),('b',3),('c',1)"))
            conn.execute(
                text(
                    "INSERT INTO player_week_stats VALUES ('a',6),('a',0),('a',-1),"
                    "('a',NULL),('b',8),('b',2),('c',5)"
                )
            )
            full, means = points.load(conn)
            scoped, scoped_means = points.load(conn, player_ids=["a"])
            assert scoped == {"a": full["a"]} and scoped_means == means
            assert points.expected(scoped["a"], 3, [], scoped_means, 1.5) == points.expected(
                full["a"], 3, [], means, 1.5
            )
            payload = {
                "formation": {
                    key: [{"playerMaster": {"id": i}}] for i, key in enumerate(eleven.LINEUP_KEYS, 1)
                }
            }
            payload["formation"]["bench"] = [{"playerMaster": {"id": 99}}]
            conn.execute(
                text(
                    "INSERT INTO raw_snapshots VALUES ('laliga_api','/teams/mine/lineup',"
                    "CAST(:payload AS jsonb),now())"
                ),
                {"payload": json.dumps(payload)},
            )
            ids = conn.execute(eleven.SQL_CURRENT_CAPTURE, {"endpoint": "%/teams/mine/lineup"}).scalar()
            assert {str(pid) for pid in ids} == eleven.current_ids(payload) == {"1", "2", "3", "4"}
    finally:
        engine.dispose()
