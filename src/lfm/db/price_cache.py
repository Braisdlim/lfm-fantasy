"""Copia local verificable de precios: la BD decide siempre si sigue vigente.

Solo ahorra transferencia, no cambia el universo ni el cálculo del modelo. La
huella incluye cada precio, fecha, jugador y fuente: detecta también correcciones
y borrados antiguos. No se sirve una copia si la comprobación SQL falla.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import zlib
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import NamedTuple

from sqlalchemy import text

from lfm.config import settings

log = logging.getLogger(__name__)
MAX_BYTES = 64 * 1024 * 1024

# Ambas consultas calculan exactamente el mismo texto, en una sola instantánea
# Postgres cada una. En un fallo de caché se devuelve texto Y huella juntos: una
# escritura concurrente entre la comprobación y la descarga no envenena la copia.
DOCUMENT = """
SELECT COALESCE(json_agg(json_build_array(player_id, day, source, market_value::float8)
    ORDER BY player_id, day)::text, '[]') AS body
FROM player_value_daily WHERE market_value > 0 AND day < CAST(:as_of AS date)
"""
SQL_FINGERPRINT = text(f"SELECT md5(body) FROM ({DOCUMENT}) document")
SQL_DOCUMENT = text(f"SELECT md5(body) AS fingerprint, body FROM ({DOCUMENT}) document")


class PriceRow(NamedTuple):
    player_id: str
    day: date
    source: str
    v: float


def decode(body: str) -> list[PriceRow]:
    return [
        PriceRow(pid, date.fromisoformat(day), source, float(v)) for pid, day, source, v in json.loads(body)
    ]


def load(conn, *, as_of: date, directory: Path | None = None) -> list[PriceRow]:
    """Una huella de 32 caracteres en un acierto, el histórico solo si cambia."""
    directory = directory if directory is not None else settings.price_cache_dir
    params = {"as_of": as_of.isoformat()}
    if directory is None:
        return decode(conn.execute(SQL_DOCUMENT, params).one().body)

    # Separa bases, roles y cortes sin almacenar URLs ni credenciales en el archivo.
    identity = f"{conn.engine.url.render_as_string(hide_password=True)}|{as_of}"
    key = hashlib.sha256(identity.encode()).hexdigest()
    path = directory / f"{key}.json.gz"
    fingerprint = conn.execute(SQL_FINGERPRINT, params).scalar_one()
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            body = stream.read(MAX_BYTES + 1)
        if len(body.encode()) <= MAX_BYTES and hashlib.md5(body.encode()).hexdigest() == fingerprint:
            rows = decode(body)
            print(f"[price-cache] hit rows={len(rows)} avoided_json_bytes={len(body.encode())}")
            return rows
    except (OSError, EOFError, ValueError, TypeError, zlib.error):
        pass  # Ausente, truncada o inválida: nunca se usa como fuente de verdad.

    result = conn.execute(SQL_DOCUMENT, params).one()
    rows = decode(result.body)
    print(f"[price-cache] miss rows={len(rows)} json_bytes={len(result.body.encode())}")
    if len(result.body.encode()) > MAX_BYTES:
        return rows
    temporary = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        # Un solo corte por caché; reemplazo atómico y sin pickle/código ejecutable.
        with NamedTemporaryFile(dir=directory, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(gzip.compress(result.body.encode(), mtime=0))
        os.replace(temporary, path)
        for old in directory.glob("*.json.gz"):
            if old != path:
                old.unlink(missing_ok=True)
    except OSError:
        log.warning("No se pudo guardar la caché de precios; se usaron datos actuales de Postgres")
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return rows
