"""La agregación debe conservar el cálculo de referencia con historia y traspasos."""

import json
import os
import random
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text

from lfm.analysis.cash import SQL_CLAUSE_SPEND, SQL_SQUAD_SNAPSHOTS, observed_clause_spend


def sample():
    rng = random.Random(20261009)
    start = datetime(2026, 9, 1, tzinfo=UTC)
    snapshots, transfers = [], []
    for team in ("A", "B", "C", "D"):
        clauses = {str(p): 5_000_000 for p in range(20)}
        for i in range(80):
            at = start + timedelta(hours=i)
            players = []
            for pid in clauses:
                value = 5_000_000 + rng.randrange(-20, 20) * 45_329
                clauses[pid] = max(clauses[pid], value)
                if rng.random() < 0.09:
                    clauses[pid] += rng.choice([499_000, 500_000, 501_000, 502_000, 1_650_000, 2_000_000])
                if rng.random() < 0.03:
                    transfers.append((pid, at - timedelta(minutes=rng.choice([0, 30, 60]))))
                if rng.random() < 0.05:
                    continue  # jugador ausente: no encadenar estados a través del hueco
                p = {"buyoutClause": clauses[pid], "playerMaster": {"id": pid, "marketValue": value}}
                if i % 5 == 0:
                    p["buyoutClause"] = str(p["buyoutClause"])
                players.append(p)
                if i % 7 == 0:
                    # El último duplicado válido prevalece, como en _players.
                    players.append({"buyoutClause": clauses[pid] + 500_000, "playerMaster": {"id": pid}})
                    players.append({"buyoutClause": None, "playerMaster": {"id": pid}})
            payload = {"players": players, "unused": "x" * 4000}
            if i % 17 == 0:
                payload = {}  # captura válida vacía: reinicia el estado
            elif i % 19 == 0:
                payload = None  # captura no objeto: se ignora sin reiniciar
            elif i % 23 == 0:
                payload = []
            snapshots.append((f"/leagues/L/teams/{team}", at, payload))
    snapshots.sort(key=lambda row: row[:2])
    return snapshots, transfers


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="Requiere Postgres de pruebas")
def test_aggregate_equals_reference_and_returns_only_one_row_per_team():
    engine = create_engine(os.environ["TEST_POSTGRES_URL"])
    snapshots, transfers = sample()
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TEMP TABLE raw_snapshots "
                    "(id bigserial, source text, endpoint text, fetched_at timestamptz, payload jsonb) "
                    "ON COMMIT DROP"
                )
            )
            conn.execute(
                text(
                    "CREATE TEMP TABLE league_activity "
                    "(league_id text, activity_type int, player_id text, happened_at timestamptz) "
                    "ON COMMIT DROP"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO raw_snapshots (source, endpoint, fetched_at, payload) "
                    "VALUES ('laliga_api', :endpoint, :at, CAST(:payload AS jsonb))"
                ),
                [
                    {"endpoint": endpoint, "at": at, "payload": json.dumps(payload)}
                    for endpoint, at, payload in snapshots
                ],
            )
            conn.execute(
                text("INSERT INTO league_activity VALUES ('L', 31, :pid, :at)"),
                [{"pid": pid, "at": at} for pid, at in transfers],
            )
            params = {
                "endpoint": "%/leagues/L/teams/%",
                "until": datetime(2026, 10, 1, tzinfo=UTC),
                "league_id": "L",
                "team_ids": ["A", "B", "C"],
            }
            full = conn.execute(SQL_SQUAD_SNAPSHOTS, params).all()
            reference = observed_clause_spend(full, transfers, set(params["team_ids"]))
            actual = {row.team_id: int(row.spend) for row in conn.execute(SQL_CLAUSE_SPEND, params)}
            assert actual == reference and len(actual) == 3
            old_bytes = len(json.dumps([(e, at.isoformat(), p) for e, at, p in full]).encode())
            new_bytes = len(json.dumps(actual).encode())
            assert new_bytes / old_bytes < 0.001
            print(
                json.dumps(
                    {
                        "compact_history_bytes": old_bytes,
                        "aggregate_bytes": new_bytes,
                        "reduction": 1 - new_bytes / old_bytes,
                    }
                )
            )
            # Una corrección antigua se vuelve a calcular, sin acumuladores obsoletos.
            conn.execute(text("DELETE FROM league_activity WHERE player_id = '7'"))
            remaining = [(pid, at) for pid, at in transfers if pid != "7"]
            actual = {row.team_id: int(row.spend) for row in conn.execute(SQL_CLAUSE_SPEND, params)}
            assert actual == observed_clause_spend(full, remaining, set(params["team_ids"]))
            # El corte temporal y la selección de liga se aplican antes de calcular.
            params["until"] = snapshots[0][1] + timedelta(hours=25)
            full = conn.execute(SQL_SQUAD_SNAPSHOTS, params).all()
            actual = {row.team_id: int(row.spend) for row in conn.execute(SQL_CLAUSE_SPEND, params)}
            assert actual == observed_clause_spend(full, remaining, set(params["team_ids"]))
    finally:
        engine.dispose()
