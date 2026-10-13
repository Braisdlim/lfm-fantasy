"""Entrenar precios solo cuando cambian datos, corte temporal o código del modelo.

La recomendación de hoy se sigue recalculando con mercado, saldo, disponibilidad
y tesis actuales. La caché contiene exclusivamente el modelo y las series de precios.
"""

from dataclasses import asdict
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path

from lfm.analysis import drift, trend
from lfm.config import settings
from lfm.db import analysis_cache, price_cache


def calculate(rows, day: date) -> dict:
    from lfm.analysis.recommend import current_series

    history = drift.consecutive_segments(r for r in rows if r.day < day)
    table = drift.build_table(history)
    magnitude = drift.build_table_magnitude(history, stat="median")
    trend_table, trend_check = trend.fit(rows, day)
    return {
        "recent": current_series(rows, day),
        "table": {k: asdict(v) for k, v in table.items()},
        "magnitude": {k: asdict(v) for k, v in magnitude.items()},
        "trend_table": dict(trend_table),
        "trend_check": trend_check,
    }


def validate(result: dict) -> None:
    if not isinstance(result, dict) or set(result) != {
        "recent",
        "table",
        "magnitude",
        "trend_table",
        "trend_check",
    }:
        raise ValueError("Formato de modelo de precios inválido")
    for key in result:
        if not isinstance(result[key], dict):
            raise ValueError("Tabla de modelo inválida")
    for name in ("table", "magnitude"):
        for values in result[name].values():
            drift.Drift(**values)
    for name in ("recent", "trend_table"):
        if any(not isinstance(values, list) for values in result[name].values()):
            raise ValueError("Serie de modelo inválida")


def load(conn, day: date) -> dict:
    # Verificar TODOS los precios, incluidas correcciones y borrados antiguos.
    cutoff = day + timedelta(days=1)
    fingerprint = conn.execute(price_cache.SQL_FINGERPRINT, {"as_of": str(cutoff)}).scalar_one()
    version = sha256()
    for path in (
        Path(__file__),
        Path(drift.__file__),
        Path(trend.__file__),
        Path(__file__).with_name("recommend.py"),
    ):
        version.update(path.read_bytes())
    key = sha256(f"{day}|{fingerprint}|{version.hexdigest()}".encode()).hexdigest()

    def compute():
        result = calculate(price_cache.load(conn, as_of=cutoff), day)
        confirmed = conn.execute(price_cache.SQL_FINGERPRINT, {"as_of": str(cutoff)}).scalar_one()
        if confirmed != fingerprint:
            raise RuntimeError("Precios modificados durante el entrenamiento: conservar análisis anterior")
        return result

    return analysis_cache.load(
        conn,
        name="price-models",
        fingerprint=key,
        compute=compute,
        validate=validate,
        directory=settings.price_cache_dir,
    )
