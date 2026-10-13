"""Conexión a Postgres (SQLAlchemy Core + psycopg)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Engine, create_engine, text

from lfm.config import settings

_engine: Engine | None = None


def dsn(url: str) -> str:
    """Fuerza el driver psycopg 3: SQLAlchemy interpreta `postgresql://` como psycopg2.
    Neon y la mayoría de proveedores entregan la URL sin sufijo de driver."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def engine() -> Engine:
    global _engine
    if _engine is None:
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL no configurada")
        _engine = create_engine(dsn(settings.database_url), pool_pre_ping=True)
    return _engine


def save_raw(source: str, endpoint: str, params: dict[str, Any] | None, payload: Any) -> None:
    """Guarda una respuesta cruda (regla 2 de CLAUDE.md)."""
    with engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO raw_snapshots (source, endpoint, params, payload) "
                "VALUES (:source, :endpoint, CAST(:params AS jsonb), CAST(:payload AS jsonb))"
            ),
            {
                "source": source,
                "endpoint": endpoint,
                "params": json.dumps(params) if params else None,
                "payload": json.dumps(payload, ensure_ascii=False),
            },
        )
