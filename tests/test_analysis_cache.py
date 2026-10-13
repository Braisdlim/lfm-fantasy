import gzip
import hashlib
import json
from types import SimpleNamespace

import pytest

from lfm.db import analysis_cache as cache


class Connection:
    def __init__(self):
        self.saved = None
        self.calls = []

    def execute(self, statement, params):
        self.calls.append(statement)
        if statement is cache.SQL_META:
            digest = (
                self.saved["sha256"]
                if self.saved and self.saved["fingerprint"] == params["fingerprint"]
                else None
            )
            return SimpleNamespace(scalar=lambda: digest)
        if statement is cache.SQL_READ:
            row = self.saved if self.saved and self.saved["fingerprint"] == params["fingerprint"] else None
            return SimpleNamespace(first=lambda: SimpleNamespace(**row) if row else None)
        assert statement is cache.SQL_SAVE
        self.saved = params


def test_local_hit_still_checks_database_and_cold_runner_does_not_retrain(tmp_path):
    conn = Connection()
    calls = []

    def compute():
        calls.append(True)
        return {"value": 7}

    def load():
        return cache.load(
            conn, name="model", fingerprint="a", compute=compute, validate=lambda _: None, directory=tmp_path
        )

    load()
    conn.calls.clear()
    assert load() == {"value": 7}
    assert conn.calls == [cache.SQL_META]
    next(tmp_path.glob("*.model.gz")).write_bytes(b"broken")
    conn.calls.clear()
    assert load() == {"value": 7}
    assert conn.calls == [cache.SQL_META, cache.SQL_READ]
    assert len(calls) == 1


def test_verified_hit_and_data_change():
    conn = Connection()
    calls = []

    def compute():
        calls.append(True)
        return {"value": len(calls)}

    def validate(value):
        assert isinstance(value["value"], int)

    def load(key):
        return cache.load(conn, name="model", fingerprint=key, compute=compute, validate=validate)

    assert load("a") == load("a") == {"value": 1}
    assert load("b") == {"value": 2}
    assert len(calls) == 2


@pytest.mark.parametrize("damage", ["gzip", "hash", "schema"])
def test_corruption_recomputes(damage):
    conn = Connection()

    def validate(value):
        if "value" not in value:
            raise ValueError("schema")

    def load():
        return cache.load(
            conn, name="model", fingerprint="a", compute=lambda: {"value": 7}, validate=validate
        )

    load()
    if damage == "gzip":
        conn.saved["body"] = b"broken"
    elif damage == "hash":
        conn.saved["sha256"] = "0" * 64
    else:
        raw = json.dumps({"wrong": 1}).encode()
        conn.saved["body"] = gzip.compress(raw)
        conn.saved["sha256"] = hashlib.sha256(raw).hexdigest()
    assert load() == {"value": 7}
    assert gzip.decompress(conn.saved["body"]) == b'{"value": 7}'


def test_failed_training_never_overwrites_previous_model():
    conn = Connection()
    conn.saved = {"fingerprint": "old"}

    def fail():
        raise RuntimeError("changed while training")

    with pytest.raises(RuntimeError, match="changed"):
        cache.load(conn, name="model", fingerprint="new", compute=fail, validate=lambda _: None)
    assert conn.saved == {"fingerprint": "old"}
