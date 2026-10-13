"""Resultados derivados verificables: nunca pickle ni código serializado."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import logging
import os
import zlib
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile

from sqlalchemy import text

MAX_BYTES = 64 * 1024 * 1024
log = logging.getLogger(__name__)
SQL_META = text("SELECT sha256 FROM analysis_cache WHERE name=:name AND fingerprint=:fingerprint")
SQL_READ = text("SELECT body, sha256 FROM analysis_cache WHERE name=:name AND fingerprint=:fingerprint")
SQL_SAVE = text(
    "INSERT INTO analysis_cache (name, fingerprint, body, sha256) "
    "VALUES (:name, :fingerprint, :body, :sha256) ON CONFLICT (name) DO UPDATE SET "
    "fingerprint=EXCLUDED.fingerprint, body=EXCLUDED.body, sha256=EXCLUDED.sha256"
)


def _decode(body, expected, validate):
    with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("Caché derivada sin integridad")
    result = json.loads(raw)
    validate(result)
    return result


def _save_file(directory, body, digest):
    if directory is None:
        return
    temporary = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{digest}.model.gz"
        with NamedTemporaryFile(dir=directory, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(body)
        os.replace(temporary, path)
        for old in directory.glob("*.model.gz"):
            if old != path:
                old.unlink(missing_ok=True)
    except OSError:
        log.warning("No se pudo guardar la copia local del modelo; Postgres sigue siendo la fuente")
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def load(
    conn,
    *,
    name: str,
    fingerprint: str,
    compute: Callable[[], dict],
    validate: Callable[[dict], None],
    directory: Path | None = None,
):
    if directory is not None:
        digest = conn.execute(SQL_META, {"name": name, "fingerprint": fingerprint}).scalar()
        if digest:
            try:
                body = (directory / f"{digest}.model.gz").read_bytes()
                result = _decode(body, digest, validate)
                print(f"[analysis-cache] local-hit name={name} avoided_bytes={len(body)}")
                return result
            except (OSError, EOFError, ValueError, TypeError, KeyError, zlib.error):
                pass
    row = conn.execute(SQL_READ, {"name": name, "fingerprint": fingerprint}).first()
    if row is not None:
        try:
            result = _decode(row.body, row.sha256, validate)
            _save_file(directory, row.body, row.sha256)
            print(f"[analysis-cache] hit name={name} compressed_bytes={len(row.body)}")
            return result
        except (OSError, EOFError, ValueError, TypeError, KeyError, zlib.error):
            pass  # No publicar resultados antiguos/corruptos; rehacer desde los datos reales.
    result = compute()
    validate(result)
    raw = json.dumps(result, ensure_ascii=False, allow_nan=False).encode()
    if len(raw) <= MAX_BYTES:
        body = gzip.compress(raw, mtime=0)
        conn.execute(
            SQL_SAVE,
            {
                "name": name,
                "fingerprint": fingerprint,
                "body": body,
                "sha256": hashlib.sha256(raw).hexdigest(),
            },
        )
        _save_file(directory, body, hashlib.sha256(raw).hexdigest())
        print(f"[analysis-cache] miss name={name} compressed_bytes={len(body)}")
    return result
