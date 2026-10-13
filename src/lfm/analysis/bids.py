"""Cuánto hay que pujar para ganar, medido en las subastas de tu propia liga.

El mercado de la liga es a puja ciega: gana la más alta y pagas lo que pujaste. Del feed de
actividad conocemos, de cada fichaje (tipo 31), **cuánto se pagó** y **cuánto valía ese día**, así
que tenemos la distribución empírica de la prima que hizo falta para ganar.

Aviso que hay que dar siempre (docs/criterio.md §7.2): solo observamos las pujas **ganadoras**,
nunca las perdedoras. La tabla responde «cuánto hizo falta para ganar», que es la pregunta, pero
condicionada a que alguien pujara.

Medido el 2026-09-08 sobre 70 fichajes: mediana 1,026 × valor, y la prima depende mucho del tramo
de precio (en los caros basta rozar el valor, en los baratos hay que pagar bastante más).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

SQL_WINNING_BIDS = text(
    "SELECT a.amount::float8 AS paid, v.market_value::float8 AS value, "
    "       v3.market_value::float8 AS value_before "
    "FROM league_activity a "
    "JOIN player_value_daily v ON v.player_id = a.player_id "
    "     AND v.day = (a.happened_at AT TIME ZONE 'Europe/Madrid')::date "
    "LEFT JOIN player_value_daily v3 ON v3.player_id = a.player_id "
    "     AND v3.day = (a.happened_at AT TIME ZONE 'Europe/Madrid')::date - :days "
    "WHERE a.league_id = :league_id AND a.activity_type = 31 "
    "  AND v.market_value > 0 AND a.amount > 0 "
    "  AND (a.happened_at AT TIME ZONE 'Europe/Madrid')::date < CAST(:before AS date)"
)

# Tramos de valor: la sobrepuja se comporta muy distinto en un jugador de 2 M que en uno de 60 M
BANDS: tuple[tuple[float, float, str], ...] = (
    (0.0, 5e6, "menos de 5 M"),
    (5e6, 20e6, "de 5 a 20 M"),
    (20e6, math.inf, "más de 20 M"),
)
MIN_BAND_SAMPLE = 10  # por debajo de esto no nos fiamos del tramo y usamos toda la liga

# --- La racha, que es lo que más mueve la puja --------------------------------------------------
#
# El modelo miraba solo el precio, y por eso se quedaba corto con los que están subiendo: el
# 2026-09-15 recomendo pujar 24,57 M por Xavi Espart, un 3 % sobre su valor, cuando llevaba
# **+37 % en tres dias** y eso lo estaba viendo toda la liga.
#
# Medido sobre 83 fichajes reales, el percentil 70 —lo que hizo falta para ganar 7 de cada 10—
# por racha de tres dias:
#
#     baja o plana  (n=17)  1,032 x          sube 5-15 %  (n=25)  1,117 x
#     sube 0-5 %    (n=30)  1,026 x          sube +15 %   (n=11)  1,221 x
#
# El efecto del precio sigue ahi (1,12 x en los baratos frente a 1,03 x en los caros), asi que se
# combinan **multiplicando**: el tramo de precio pone la base y la racha la corrige. Cruzarlos
# directamente no se puede con esta muestra —las celdas quedan en n=5, y en «mas de 20 M» con racha
# fuerte no hay ni una observacion, que es justo el caso de Espart.
MOMENTUM_DAYS = 3
MOMENTUM_BANDS: tuple[tuple[float, float, str], ...] = (
    (-math.inf, 0.0, "bajando o plano"),
    (0.0, 0.05, "subiendo poco"),
    (0.05, 0.15, "subiendo bastante"),
    (0.15, math.inf, "subiendo mucho"),
)
MIN_MOMENTUM_SAMPLE = 8
# La correccion se acota: con once observaciones en el tramo alto, dejarla suelta seria creerse una
# extrapolacion. Entre estos limites sigue moviendo la puja donde importa.
MOMENTUM_FACTOR_RANGE = (0.90, 1.35)


def momentum(series: list[float] | None, days: int = MOMENTUM_DAYS) -> float | None:
    """Cambio relativo del valor en los ultimos `days` dias. `None` si no hay serie suficiente."""
    if not series or len(series) < days + 1:
        return None
    antes = series[-(days + 1)]
    if not antes:
        return None
    return (series[-1] - antes) / antes


def momentum_band(m: float | None) -> str | None:
    if m is None:
        return None
    for lo, hi, name in MOMENTUM_BANDS:
        if lo <= m < hi:
            return name
    return MOMENTUM_BANDS[-1][2]


@dataclass(frozen=True)
class BidToWin:
    ratio: float  # veces el valor
    amount: int  # euros
    confidence: float  # percentil de precios ganadores, NO probabilidad de ganar
    n: int  # tamaño de muestra
    band: str  # tramo usado
    momentum_band: str | None = None  # tramo de racha aplicado, si lo hubo
    momentum_factor: float = 1.0  # cuánto corrigió la racha
    momentum_n: int = 0


def band_of(value: float) -> str:
    for lo, hi, name in BANDS:
        if lo <= value < hi:
            return name
    return BANDS[-1][2]


def percentile(sorted_values: list[float], q: float) -> float:
    """Percentil por el método del más cercano por arriba: el valor que habría bastado para
    ganar esa fracción de las subastas observadas."""
    if not sorted_values:
        raise ValueError("sin muestra")
    i = max(0, min(len(sorted_values) - 1, math.ceil(q * len(sorted_values)) - 1))
    return sorted_values[i]


@dataclass(frozen=True)
class Won:
    ratio: float  # pagado / valor
    value: float
    momentum: float | None  # como venia su valor los dias anteriores


def load_ratios(conn: Connection, *, league_id: str, before) -> list[Won]:
    """Los fichajes anteriores a `before` (sin mirar el futuro), con su prima y su racha."""
    rows = conn.execute(
        SQL_WINNING_BIDS,
        {"league_id": league_id, "before": str(before), "days": MOMENTUM_DAYS},
    ).all()
    return [
        Won(
            ratio=r.paid / r.value,
            value=r.value,
            momentum=(r.value - r.value_before) / r.value_before if r.value_before else None,
        )
        for r in rows
    ]


def bid_to_win(
    ratios: list[Won],
    value: float,
    confidence: float = 0.7,
    player_momentum: float | None = None,
) -> BidToWin | None:
    """Referencia por el percentil `confidence` de los precios ganadores observados.

    No conocemos las pujas perdedoras ni la distribución futura: ese percentil
    no es una probabilidad calibrada de ganar la próxima subasta.

    El tramo de precio pone la base y la racha la corrige, porque los dos efectos estan medidos y
    tiran en direcciones distintas: en los baratos se paga mas prima, y en los que suben, mucha mas.
    """
    if len(ratios) < MIN_BAND_SAMPLE:
        return None
    band = band_of(value)
    same = sorted(w.ratio for w in ratios if band_of(w.value) == band)
    if len(same) >= MIN_BAND_SAMPLE:
        used, label = same, band
    else:
        used, label = sorted(w.ratio for w in ratios), "toda la liga"
    ratio = percentile(used, confidence)

    # Correccion por racha: cuanto se desvia su tramo del conjunto de los que tienen racha medible.
    mb = momentum_band(player_momentum)
    factor, mom_n = 1.0, 0
    if mb is not None:
        mismos = sorted(w.ratio for w in ratios if momentum_band(w.momentum) == mb)
        todos = sorted(w.ratio for w in ratios if w.momentum is not None)
        if len(mismos) >= MIN_MOMENTUM_SAMPLE and todos:
            base = percentile(todos, confidence)
            if base > 0:
                bruto = percentile(mismos, confidence) / base
                factor = max(MOMENTUM_FACTOR_RANGE[0], min(MOMENTUM_FACTOR_RANGE[1], bruto))
                mom_n = len(mismos)
        if mom_n == 0:
            mb = None

    final = ratio * factor
    return BidToWin(
        ratio=round(final, 4),
        amount=int(round(value * final)),
        confidence=confidence,
        n=len(used),
        band=label,
        momentum_band=mb,
        momentum_factor=round(factor, 4),
        momentum_n=mom_n,
    )
