import json
import os
from datetime import date

import pytest
from sqlalchemy import create_engine, text

from lfm.collectors.value_history import SQL_CHANGES, SQL_SAVE, normalize


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="Requiere Postgres de pruebas")
def test_history_replaces_external_values_without_changing_current_capture():
    db = create_engine(os.environ["TEST_POSTGRES_URL"])
    try:
        with db.begin() as conn:
            conn.execute(
                text(
                    "CREATE TEMP TABLE player_value_daily (player_id text, day date, "
                    "market_value bigint, source text, change bigint, status text, "
                    "points_total int, PRIMARY KEY(player_id,day)) ON COMMIT DROP"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO player_value_daily VALUES "
                    "('p','2026-10-07',99,'futbolfantasy_backfill',NULL,NULL,NULL),"
                    "('p','2026-10-09',120,'laliga_api',NULL,'injured',300)"
                )
            )
            payload = [
                {"date": "2026-10-07T00:00:00+02:00", "marketValue": 100},
                {"date": "2026-10-08T00:00:00+02:00", "marketValue": 110},
                {"date": "2026-10-09T00:00:00+02:00", "marketValue": 125},
            ]
            for _ in range(2):
                conn.execute(
                    SQL_SAVE, {"pid": "p", "rows": json.dumps(normalize(payload, date(2026, 10, 9)))}
                )
                conn.execute(SQL_CHANGES, {"pid": "p"})
            rows = conn.execute(
                text(
                    "SELECT market_value,source,change,status,points_total "
                    "FROM player_value_daily ORDER BY day"
                )
            ).all()
            assert rows == [
                (100, "laliga_api", None, None, None),
                (110, "laliga_api", 10, None, None),
                (120, "laliga_api", 10, "injured", 300),
            ]
    finally:
        db.dispose()
