import json
import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event, text

from lfm.analysis import journal
from lfm.db.batch_reads import Result


def test_result_mapping_and_tuple_semantics():
    result = Result([{"name": "a", "position_id": 2}])
    assert result.first() == ("a", 2)
    assert result.scalar() == "a"
    assert result.mappings().first() == {"name": "a", "position_id": 2}
    assert result.mappings().all() == [{"name": "a", "position_id": 2}]
    assert Result([]).mappings().first() is None
    assert Result([]).first() is None


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="Requiere Postgres de pruebas")
def test_journal_batch_preserves_values_and_query_count():
    engine = create_engine(os.environ["TEST_POSTGRES_URL"])
    try:
        with engine.begin() as conn:
            tables = {
                "players": "player_id text,name text,nickname text,position_id int",
                "player_value_daily": "player_id text,day date,source text,market_value bigint",
                "matches": "week int,match_date timestamptz",
                "player_week_stats": "player_id text,week int,total_points int",
                "lineup_daily": "team_id text,player_id text,day date,current boolean",
                "recommendation_log": "player_id text,kind text,cycle_end timestamptz,verdict text",
                "decision_journal": (
                    "league_id text,player_id text,entry_at timestamptz,open boolean,detail jsonb"
                ),
            }
            for name, columns in tables.items():
                conn.execute(text(f"CREATE TEMP TABLE {name} ({columns}) ON COMMIT DROP"))
            conn.execute(text("INSERT INTO players VALUES ('a','Alpha',NULL,2),('b','Beta','B',2)"))
            conn.execute(
                text(
                    "INSERT INTO player_value_daily VALUES "
                    "('a','2026-10-01','laliga_api',100),('a','2026-10-05','laliga_api',120),"
                    "('b','2026-10-01','laliga_api',200),('b','2026-10-05','laliga_api',180),"
                    "('b','2026-10-01','other',190),('b','2026-10-05','other',170)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO matches VALUES "
                    "(1,'2026-10-02T20:00Z'),(1,'2026-10-03T20:00Z'),(2,'2026-10-05T20:00Z')"
                )
            )
            conn.execute(text("INSERT INTO player_week_stats VALUES ('a',1,7),('a',2,NULL),('b',1,3)"))
            conn.execute(
                text(
                    "INSERT INTO lineup_daily VALUES "
                    "('me','a','2026-10-01',true),('me','b','2026-10-01',false)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO recommendation_log VALUES "
                    "('a','buy','2026-10-02T00:00Z','pujar'),('a','sell','2026-10-05T20:00Z','vender')"
                )
            )
            at = datetime(2026, 10, 1, 22, 30, tzinfo=UTC)  # Madrid: ya día 2
            exit_at = datetime(2026, 10, 5, 19, tzinfo=UTC)
            holdings = [
                journal.Holding("a", at, "mercado", 105, exit_at, "venta_sistema", 125),
                journal.Holding("a", exit_at, "manager", 110),
                journal.Holding("b", None, "inicial", None, exit_at, "venta_sistema", 195),
                journal.Holding("missing", at, "mercado", 20),
            ]
            expected = [journal.enrich(conn, h, team_id="me") for h in holdings]
            queries = []
            event.listen(conn, "before_cursor_execute", lambda *args: queries.append(args[2]))
            assert journal.enrich_many(conn, holdings, team_id="me") == expected
            assert len(queries) == 6
            queries.clear()
            assert journal.enrich_many(conn, holdings * 50, team_id="me") == expected * 50
            assert len(queries) == 6  # mismo trabajo aunque haya 200 operaciones
            queries.clear()
            assert journal.enrich_many(conn, [], team_id="me") == []
            assert not queries
            conn.execute(
                journal.SQL_SAVE_BATCH,
                {
                    "league_id": "league",
                    "rows": json.dumps(
                        [
                            {
                                "pid": row["player_id"],
                                "entry_at": row["entry_at"] or journal.EPOCH,
                                "open": row["open"],
                                "detail": row,
                            }
                            for row in expected
                        ]
                    ),
                },
            )
            saved = conn.execute(text("SELECT detail FROM decision_journal ORDER BY ctid")).scalars().all()
            assert saved == expected
    finally:
        engine.dispose()
