import os
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, text

from lfm.analysis import price_models
from lfm.db import analysis_cache, price_cache


class Connection:
    def __init__(self):
        self.fingerprint = "data1"
        self.model = None

    def execute(self, sql, params):
        if sql is price_cache.SQL_FINGERPRINT:
            return SimpleNamespace(scalar_one=lambda: self.fingerprint)
        if sql is analysis_cache.SQL_META:
            return SimpleNamespace(scalar=lambda: None)
        if sql is analysis_cache.SQL_READ:
            row = self.model if self.model and self.model["fingerprint"] == params["fingerprint"] else None
            return SimpleNamespace(first=lambda: SimpleNamespace(**row) if row else None)
        assert sql is analysis_cache.SQL_SAVE
        self.model = params


def test_model_hit_reuses_exact_output_and_invalidation(monkeypatch):
    conn = Connection()
    rows = price_cache.decode('[["1","2026-10-01","laliga_api",100]]')
    calls = []

    def prices(*args, **kwargs):
        calls.append(True)
        return rows

    monkeypatch.setattr(price_cache, "load", prices)
    day = date(2026, 10, 2)
    first = price_models.load(conn, day)
    assert price_models.load(conn, day) == first == price_models.calculate(rows, day)
    assert len(calls) == 1
    conn.fingerprint = "historical-correction"
    price_models.load(conn, day)
    price_models.load(conn, date(2026, 10, 3))
    assert len(calls) == 3
    original = price_models.Path.read_bytes
    monkeypatch.setattr(price_models.Path, "read_bytes", lambda p: original(p) + b"\n# version change")
    price_models.load(conn, date(2026, 10, 3))
    assert len(calls) == 4


def test_concurrent_price_write_does_not_save_wrong_key(monkeypatch):
    conn = Connection()

    def prices(*args, **kwargs):
        conn.fingerprint = "concurrent-write"
        return []

    monkeypatch.setattr(price_cache, "load", prices)
    with pytest.raises(RuntimeError, match="Precios modificados"):
        price_models.load(conn, date(2026, 10, 2))
    assert conn.model is None


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="Requiere Postgres de pruebas")
def test_postgres_persistent_model_survives_file_cache_loss_and_invalidates(tmp_path, monkeypatch):
    engine = create_engine(os.environ["TEST_POSTGRES_URL"])
    monkeypatch.setattr(price_models.settings, "price_cache_dir", tmp_path)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TEMP TABLE analysis_cache "
                    "(name text PRIMARY KEY,fingerprint text,body bytea,sha256 text) ON COMMIT DROP"
                )
            )
            conn.execute(
                text(
                    "CREATE TEMP TABLE player_value_daily "
                    "(player_id text,day date,source text,market_value bigint) ON COMMIT DROP"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO player_value_daily SELECT '1', '2026-08-01'::date + i, "
                    "'laliga_api', 1000000 + (i % 15) * 10000 FROM generate_series(0,65) i"
                )
            )
            day = date(2026, 10, 2)
            rows = conn.execute(price_cache.SQL_DOCUMENT, {"as_of": "2026-10-03"}).one()
            expected = price_models.calculate(price_cache.decode(rows.body), day)
            assert price_models.load(conn, day) == expected
            queries = []
            event.listen(conn, "before_cursor_execute", lambda *args: queries.append(args[2]))
            assert price_models.load(conn, day) == expected
            assert len(queries) == 2  # huella de datos y SHA del modelo; sin histórico ni modelo
            for path in tmp_path.glob("*.gz"):
                path.unlink()
            with monkeypatch.context() as m:
                m.setattr(price_models, "calculate", lambda *_: pytest.fail("No debe reentrenar"))
                assert price_models.load(conn, day) == expected
            conn.execute(text("UPDATE player_value_daily SET market_value=900000 WHERE day='2026-08-01'"))
            assert price_models.load(conn, day) != expected
            assert conn.execute(text("SELECT count(*) FROM analysis_cache")).scalar() == 1
    finally:
        engine.dispose()
