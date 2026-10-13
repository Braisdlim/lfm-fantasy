import gzip
import hashlib
import json
import os
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, text

from lfm.analysis import drift, recommend, trend
from lfm.db import price_cache as cache


class Connection:
    def __init__(self, body):
        self.body = body
        self.calls = []
        self.engine = SimpleNamespace(url=SimpleNamespace(render_as_string=lambda **_: "db1"))

    def execute(self, sql, params):
        self.calls.append(sql)
        body = self.body
        return SimpleNamespace(
            scalar_one=lambda: hashlib.md5(body.encode()).hexdigest(),
            one=lambda: SimpleNamespace(body=body, fingerprint=hashlib.md5(body.encode()).hexdigest()),
        )


def test_cache_hit_checks_fingerprint_without_downloading_history(tmp_path):
    conn = Connection('[["7", "2026-10-01", "laliga_api", 12345678]]')
    day = date(2026, 10, 2)
    first = cache.load(conn, as_of=day, directory=tmp_path)
    assert conn.calls == [cache.SQL_FINGERPRINT, cache.SQL_DOCUMENT]
    conn.calls.clear()
    assert cache.load(conn, as_of=day, directory=tmp_path) == first
    assert conn.calls == [cache.SQL_FINGERPRINT]
    assert first == [("7", date(2026, 10, 1), "laliga_api", 12345678.0)]


def test_correction_deletion_and_source_change_invalidate(tmp_path):
    conn = Connection('[["7", "2026-10-01", "laliga_api", 100]]')
    for body in [conn.body, conn.body.replace("100", "200"), conn.body.replace("laliga_api", "other"), "[]"]:
        conn.body = body
        conn.calls.clear()
        assert cache.load(conn, as_of=date(2026, 10, 2), directory=tmp_path) == cache.decode(body)
        assert conn.calls == [cache.SQL_FINGERPRINT, cache.SQL_DOCUMENT]


def test_corrupt_file_and_date_change_are_safe_cache_misses(tmp_path):
    conn = Connection("[]")
    day = date(2026, 10, 2)
    cache.load(conn, as_of=day, directory=tmp_path)
    next(tmp_path.glob("*.gz")).write_bytes(b"broken gzip")
    assert cache.load(conn, as_of=day, directory=tmp_path) == []
    conn.calls.clear()
    cache.load(conn, as_of=day + timedelta(days=1), directory=tmp_path)
    assert conn.calls == [cache.SQL_FINGERPRINT, cache.SQL_DOCUMENT]
    assert len(list(tmp_path.glob("*.gz"))) == 1


def test_database_error_never_serves_unverified_prices(tmp_path):
    conn = Connection("[]")
    day = date(2026, 10, 2)
    cache.load(conn, as_of=day, directory=tmp_path)

    def fail(*_):
        raise RuntimeError("database unavailable")

    conn.execute = fail
    with pytest.raises(RuntimeError, match="unavailable"):
        cache.load(conn, as_of=day, directory=tmp_path)


def test_write_during_fingerprint_check_cannot_label_old_content_as_new(tmp_path):
    conn = Connection('[["7", "2026-10-01", "laliga_api", 100]]')
    original_execute = conn.execute

    def concurrent_update(sql, params):
        result = original_execute(sql, params)
        if sql is cache.SQL_FINGERPRINT:
            conn.body = conn.body.replace("100", "200")
        return result

    conn.execute = concurrent_update
    assert cache.load(conn, as_of=date(2026, 10, 2), directory=tmp_path)[0].v == 200
    conn.calls.clear()
    assert cache.load(conn, as_of=date(2026, 10, 2), directory=tmp_path)[0].v == 200
    assert conn.calls == [cache.SQL_FINGERPRINT]


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="Requiere Postgres de pruebas")
def test_postgres_cache_matches_original_models_and_bounds_repeat_transfer(tmp_path):
    engine = create_engine(os.environ["TEST_POSTGRES_URL"])
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TEMP TABLE player_value_daily "
                    "(player_id text, day date, source text, market_value bigint) ON COMMIT DROP"
                )
            )
            start = date(2026, 7, 1)
            rows = [
                {
                    "pid": str(p),
                    "day": start + timedelta(days=i),
                    "source": "laliga_api" if i > 8 else "backfill",
                    "v": 1_000_000 + (i % 20) * 15_000 + p,
                }
                for p in range(80)
                for i in range(90)
                if not (p == 0 and i == 25)
            ]
            conn.execute(text("INSERT INTO player_value_daily VALUES (:pid, :day, :source, :v)"), rows)
            day = start + timedelta(days=80)
            until = day + timedelta(days=1)
            original = conn.execute(drift.SQL_SERIES, {"as_of": str(until)}).all()
            first = cache.load(conn, as_of=until, directory=tmp_path)
            repeated = cache.load(conn, as_of=until, directory=tmp_path)
            assert first == repeated == original
            assert recommend.current_series(repeated, day) == recommend.current_series(original, day)
            assert trend.fit(repeated, day) == trend.fit(original, day)
            assert drift.build_table(drift.consecutive_segments(repeated)) == drift.build_table(
                drift.consecutive_segments(original)
            )
            body = gzip.decompress(next(tmp_path.glob("*.gz")).read_bytes())
            # 20 lecturas del mismo día: una descarga completa y 20 huellas de 32 bytes.
            assert (len(body) + 20 * 32) / (20 * len(body)) < 0.051
            print(
                json.dumps(
                    {
                        "history_json_bytes": len(body),
                        "repeat_fingerprint_bytes": 32,
                        "20_reads_payload_reduction": 1 - (len(body) + 20 * 32) / (20 * len(body)),
                    }
                )
            )
            conn.execute(
                text(
                    "UPDATE player_value_daily SET market_value = 987654321 "
                    "WHERE player_id = '0' AND day = :day"
                ),
                {"day": start},
            )
            corrected = cache.load(conn, as_of=until, directory=tmp_path)
            assert corrected[0].v == 987654321
            statements = []
            event.listen(conn, "before_cursor_execute", lambda *args: statements.append(args[2]))
            assert cache.load(conn, as_of=until, directory=tmp_path) == corrected
            assert len(statements) == 1 and "SELECT md5(body) FROM" in statements[0]
    finally:
        engine.dispose()
