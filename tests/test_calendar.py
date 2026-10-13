"""Colector de calendario contra capturas reales (tests/fixtures/week_current.json, calendar.json)."""

import json
import pathlib

from lfm.collectors import calendar

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def test_week_fixture_contract():
    w = calendar.normalize_week(load("week_current"))
    assert w["week"] == 5 and w["next_week"] == 6 and w["is_live"] is False
    assert w["opening_at"].startswith("2026-09-11T21:00") and w["closing_at"]


def test_matches_fixture_contract():
    rows = calendar.normalize_matches(load("calendar"), 5)
    assert len(rows) == 10  # 20 clubes, 10 partidos
    for r in rows:
        assert (
            r["match_id"]
            and r["week"] == 5
            and r["match_date"]
            and r["local_team_id"]
            and r["visitor_team_id"]
        )
    clubs = {r["local_team_id"] for r in rows} | {r["visitor_team_id"] for r in rows}
    assert len(clubs) == 20


class FakeConn:
    def __init__(self):
        self.calls = []

    def execute(self, stmt, params):
        self.calls.append((str(stmt), params))


class FakeClient:
    def current_week(self):
        return load("week_current")

    def calendar(self, week):
        return load("calendar")  # la API devuelve lo mismo si se pierde weekNumber: debe deduplicar


def test_collect_calendar_writes_week_and_matches_for_current_and_next_week():
    conn = FakeConn()
    s = calendar.collect_calendar(FakeClient(), conn)
    assert [sql.split(" ")[2] for sql, _ in conn.calls] == ["weeks", "matches"]
    assert s["week"] == 5 and s["matches"] == 10  # 20 filas de entrada, 10 ids distintos
    assert calendar.normalize_week({}) is None


class CountingClient(FakeClient):
    def __init__(self):
        self.weeks = []

    def calendar(self, week):
        self.weeks.append(week)
        return load("calendar")


def test_it_asks_for_the_current_week_and_the_five_after_it():
    """Horizonte de 5 jornadas para satisfacer el calendario FDR."""
    client = CountingClient()
    calendar.collect_calendar(client, FakeConn())
    assert client.weeks == [5, 6, 7, 8, 9, 10]


def test_it_never_asks_for_a_week_past_the_end_of_the_season():
    class LateClient(CountingClient):
        def current_week(self):
            return dict(load("week_current"), weekNumber=37, nextWeek=38)

    client = LateClient()
    calendar.collect_calendar(client, FakeConn())
    assert client.weeks == [37, 38]
