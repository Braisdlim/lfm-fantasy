"""Ejecuta la proyección de capturas en Postgres aislado (TEST_POSTGRES_URL, configurado en CI)."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from lfm.analysis.cash import SQL_SQUAD_SNAPSHOTS, _players, observed_clause_spend


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="Requiere Postgres de pruebas")
def test_snapshot_projection_preserves_cash_inputs_and_reduces_transfer():
    start = datetime(2026, 9, 8, tzinfo=UTC)
    fixture = json.loads((Path(__file__).parent / "fixtures/team.json").read_text())
    # La fixture no incluye necesariamente cláusulas; representar una subida y una compra intermedia.
    fixture["players"] = [
        {"buyoutClause": 7_000_000, "playerMaster": {"id": 7, "marketValue": 5_000_000}},
        {"buyoutClause": 7_000_000, "playerMaster": {"id": 8, "marketValue": 5_000_000}},
    ]
    fixture["unused"] = "x" * 20_000
    changed = json.loads(json.dumps(fixture))
    for player in changed["players"]:
        player["buyoutClause"] += 2_000_000
    payloads = [
        fixture,
        changed,
        None,
        [],
        {},
        {"players": None},
        {"players": []},
        {
            "players": [
                {"buyoutClause": "9000000", "playerMaster": {"id": 9, "marketValue": None}},
                {"buyoutClause": None, "playerMaster": {"id": 10}},
                {"buyoutClause": 10_000_000, "playerMaster": {"id": 9, "marketValue": 6_000_000}},
                {"buyoutClause": 4_000_000},
            ]
        },
    ]
    original_sql = text(
        "SELECT endpoint, fetched_at, payload FROM raw_snapshots "
        "WHERE source = 'laliga_api' AND endpoint LIKE :endpoint AND fetched_at < :until "
        "ORDER BY endpoint, fetched_at"
    )
    engine = create_engine(os.environ["TEST_POSTGRES_URL"])
    try:
        with engine.begin() as conn:
            # Una tabla temporal oculta cualquier tabla homónima; nunca tocar datos persistentes.
            conn.execute(
                text(
                    "CREATE TEMP TABLE raw_snapshots "
                    "(source text, endpoint text, fetched_at timestamptz, payload jsonb) ON COMMIT DROP"
                )
            )
            insert = text(
                "INSERT INTO raw_snapshots VALUES (:source, :endpoint, :at, CAST(:payload AS jsonb))"
            )
            for i, payload in enumerate(payloads):
                conn.execute(
                    insert,
                    {
                        "source": "laliga_api",
                        "endpoint": f"/leagues/L/teams/{0 if i < 2 else i}",
                        "at": start + timedelta(days=i == 1),
                        "payload": json.dumps(payload),
                    },
                )
            for source, endpoint, at in [
                ("other", "/leagues/L/teams/0", start),
                ("laliga_api", "/leagues/other/teams/0", start),
                ("laliga_api", "/leagues/L/teams/0", start + timedelta(days=2)),
            ]:
                conn.execute(insert, {"source": source, "endpoint": endpoint, "at": at, "payload": "{}"})
            params = {"endpoint": "%/leagues/L/teams/%", "until": start + timedelta(days=2)}
            full = conn.execute(original_sql, params).all()
            compact = conn.execute(SQL_SQUAD_SNAPSHOTS, params).all()
            assert len(full) == len(compact) == len(payloads)
            for old, new in zip(full, compact, strict=True):
                assert old[:2] == new[:2]
                if isinstance(old.payload, dict):
                    assert _players(old.payload) == _players(new.payload)
                else:
                    assert old.payload == new.payload
            transfers = [("8", start + timedelta(hours=12))]
            teams = {str(i) for i in range(len(payloads))}
            assert observed_clause_spend(full, transfers, teams) == {"0": 1_000_000}
            assert observed_clause_spend(compact, transfers, teams) == {"0": 1_000_000}

            def size(rows):
                return sum(len(json.dumps(r.payload).encode()) for r in rows)

            assert size(compact) < size(full) / 10
            assert conn.execute(original_sql, params).all() == full
    finally:
        engine.dispose()
