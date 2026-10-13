"""Deriva esperada del valor, estimada de la propia historia y sin mirar el futuro.

No es un modelo entrenado: es la **distribución empírica condicionada** al estado del jugador. Con
44.000 observaciones diarias da tamaños de muestra grandes y se puede auditar entero, que es lo que
pide `docs/criterio.md`.

El estado se resume en la racha: cuántos días seguidos lleva subiendo o bajando. Medido el
2026-09-08, la señal es fuerte y bate de largo al baseline:

    cualquier día        media a 7 días  −1,4 %   sube el 18,7 %
    8+ días bajando      media a 7 días −10,4 %   sube el  6,7 %

La tabla se construye **solo con días anteriores** al que se está evaluando (parámetro `as_of`),
que es lo que evita la fuga de información.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.engine import Connection

HORIZON = 7  # días vista
MIN_SAMPLE = 100  # por debajo de esto la celda no se usa y se cae al baseline

SQL_SERIES = text(
    "SELECT player_id, day, source, market_value::float8 AS v FROM player_value_daily "
    "WHERE market_value > 0 AND day < CAST(:as_of AS date) ORDER BY player_id, day"
)


@dataclass(frozen=True)
class Drift:
    mean: float  # cambio medio a 7 días, en tanto por uno
    up_rate: float  # fracción de casos que acabaron subiendo
    n: int
    bucket: str
    low: float | None = None  # percentil 20 de los resultados históricos, no intervalo de confianza
    high: float | None = None  # percentil 80


def summarize(xs: list[float], bucket: str, *, stat: str = "mean") -> Drift:
    ordered = sorted(xs)
    return Drift(
        statistics.median(xs) if stat == "median" else statistics.mean(xs),
        sum(x > 0 for x in xs) / len(xs),
        len(xs),
        bucket,
        ordered[int((len(xs) - 1) * 0.2)],
        ordered[int((len(xs) - 1) * 0.8)],
    )


def consecutive_segments(rows) -> dict[str, list[float]]:
    """Nunca convertir un hueco de tres días en un movimiento de un día.

    Conserva todos los tramos continuos para entrenar; un cambio de fuente también
    rompe el tramo si el lector trae source. Las claves son internas, no player_id.
    """
    result: dict[str, list[float]] = {}
    previous = None
    segment = 0
    for row in rows:
        if (
            previous is None
            or row.player_id != previous.player_id
            or row.day != previous.day + timedelta(days=1)
            or getattr(row, "source", None) != getattr(previous, "source", None)
        ):
            segment += 1
        result.setdefault(f"{row.player_id}:{segment}", []).append(row.v)
        previous = row
    return result


def streak(values: list[float]) -> int:
    """Días seguidos subiendo (positivo) o bajando (negativo) hasta el último valor."""
    k = 0
    for i in range(len(values) - 1, 0, -1):
        d = values[i] - values[i - 1]
        if d == 0 or (k and (d > 0) != (k > 0)):
            break
        k = (k + 1) if d > 0 else (k - 1)
    return k


def bucket_of(k: int) -> str:
    if k <= -8:
        return "bajando 8+ días"
    if k <= -4:
        return "bajando 4-7 días"
    if k <= -1:
        return f"bajando {abs(k)} día{'s' if k < -1 else ''}"
    if k == 0:
        return "plano"
    if k >= 8:
        return "subiendo 8+ días"
    if k >= 4:
        return "subiendo 4-7 días"
    return f"subiendo {k} día{'s' if k > 1 else ''}"


def build_table(series: dict[str, list[float]], *, horizon: int = HORIZON) -> dict[str, Drift]:
    """Para cada estado, el cambio medio observado en los `horizon` días siguientes."""
    acc: dict[str, list[float]] = defaultdict(list)
    for values in series.values():
        if len(values) < horizon + 3:
            continue
        for i in range(2, len(values) - horizon):
            base = values[i]
            if base <= 0:
                continue
            acc[bucket_of(streak(values[: i + 1]))].append((values[i + horizon] - base) / base)
    table: dict[str, Drift] = {}
    for bucket, xs in acc.items():
        table[bucket] = summarize(xs, bucket)
    todos = [x for xs in acc.values() for x in xs]
    if todos:
        table["baseline"] = summarize(todos, "baseline")
    return table


def load_series(conn: Connection, *, as_of) -> dict[str, list[float]]:
    return consecutive_segments(conn.execute(SQL_SERIES, {"as_of": str(as_of)}))


UNKNOWN_STREAK = "racha desconocida (serie corta)"
# Hasta esta racha, que esté censurada la deja inservible; por encima sigue siendo una cota
# inferior útil. Ver `censored`.
CENSORING_HURTS_UPTO = 3


def censored(values: list[float]) -> bool:
    """La racha se come toda la serie, así que **no sabemos dónde empezó de verdad**.

    Un jugador que entra en el juego hoy y sube mañana tiene racha «subiendo 1 día» solo porque no
    vemos más atrás: podría llevar nueve. El 2026-09-09 había quince jugadores así, recién llegados
    a LaLiga Fantasy el día 8, y su historia no existe en ninguna fuente."""
    k = abs(streak(values))
    return k > 0 and k == len(values) - 1


def unreliable(values: list[float]) -> bool:
    """Censurada **y además corta**, que es cuando deja de informar.

    Una racha censurada no es lo mismo que una racha desconocida: es una **cota inferior**. Con
    siete días bajando y siete de serie, «bajando 4-7 días» se queda corto pero apunta al lado
    bueno; sustituirlo por la media general (−0,4 % frente a −6 %) haría parecer mejor al jugador
    y empujaría a comprarlo, que es justo el error contrario al que se quería evitar. Solo cuando
    la racha observada es de tres días o menos puede la verdad estar en cualquier cajón."""
    return censored(values) and abs(streak(values)) <= CENSORING_HURTS_UPTO


def expected(table: dict[str, Drift], values: list[float]) -> Drift:
    """Deriva esperada para un jugador con esta serie. Cae al baseline si la celda es pequeña o si
    la racha no es fiable por serie corta (ver `unreliable`)."""
    base = table.get("baseline", Drift(0.0, 0.0, 0, "baseline"))
    if unreliable(values):
        return Drift(base.mean, base.up_rate, base.n, UNKNOWN_STREAK, base.low, base.high)
    cell = table.get(bucket_of(streak(values)))
    return cell if cell and cell.n >= MIN_SAMPLE else base


# --- Candidato: racha **y tamaño** de la racha (2026-09-20) --------------------------------------
#
# Caso que lo motiva: Tchouaméni llevaba cinco días bajando unas décimas y el recomendador mandaba
# venderlo con la media de «bajando 4-7 días», que la ponen sobre todo los que se hunden (lesiones,
# suplencias). Cinco días de −0,3 % no son lo mismo que cinco de −4 %. Antes de publicarlo se mide
# con `python -m lfm.analysis.drift comparar` frente al modelo actual y al baseline.

MAGNITUDE_EDGES = (0.03, 0.10)  # |cambio acumulado en la racha|: leve < 3 % ≤ media < 10 % ≤ fuerte


def streak_change(values: list[float]) -> float:
    """Cambio acumulado desde que empezó la racha actual, en tanto por uno."""
    k = abs(streak(values))
    if k == 0 or len(values) <= k or values[-1 - k] <= 0:
        return 0.0
    return values[-1] / values[-1 - k] - 1


def magnitude_of(change: float) -> str:
    a = abs(change)
    if a < MAGNITUDE_EDGES[0]:
        return "leve"
    if a < MAGNITUDE_EDGES[1]:
        return "media"
    return "fuerte"


def bucket_with_magnitude(values: list[float]) -> str:
    k = streak(values)
    base = bucket_of(k)
    return base if k == 0 else f"{base} · {magnitude_of(streak_change(values))}"


def build_table_magnitude(
    series: dict[str, list[float]], *, horizon: int = HORIZON, stat: str = "mean"
) -> dict[str, Drift]:
    """Como `build_table`, pero cada racha se parte además por su tamaño.

    `stat="median"` resume cada celda con la mediana: medido el 2026-09-20, «bajando 1 día ·
    fuerte» tenía media +84 % con solo un 29 % de casos subiendo, que es una celda arrastrada por
    unos pocos saltos, no una tendencia."""
    acc: dict[str, list[float]] = defaultdict(list)
    for values in series.values():
        if len(values) < horizon + 3:
            continue
        for i in range(2, len(values) - horizon):
            base = values[i]
            if base <= 0:
                continue
            acc[bucket_with_magnitude(values[: i + 1])].append((values[i + horizon] - base) / base)

    return {b: summarize(xs, b, stat=stat) for b, xs in acc.items()}


def expected_magnitude(table_mag: dict[str, Drift], table: dict[str, Drift], values: list[float]) -> Drift:
    """Deriva con tamaño de racha; si la celda es pequeña, cae al modelo actual."""
    if unreliable(values):
        return expected(table, values)
    cell = table_mag.get(bucket_with_magnitude(values))
    return cell if cell and cell.n >= MIN_SAMPLE else expected(table, values)


# --- Arnés de comparación hacia delante ---------------------------------------------------------

SQL_SERIES_DAYS = text(
    "SELECT player_id, day, source, market_value::float8 AS v FROM player_value_daily "
    "WHERE market_value > 0 ORDER BY player_id, day"
)

SQL_AVAILABILITY_HISTORY = text(
    "SELECT player_id, day, start_prob::float8 AS p FROM player_availability "
    "WHERE start_prob IS NOT NULL ORDER BY player_id, day"
)

SELL_STREAK_RULE = 5  # la regla de venta actual (recommend.SELL_STREAK)
SELL_MATERIAL_DROP = -0.03  # candidato: vender solo si la deriva esperada pierde más de un 3 %


def compare(conn: Connection, *, step_days: int = 7, warmup_days: int = 28) -> dict:
    """Prueba hacia delante: en cada corte se construyen las tablas **solo con días anteriores** y
    se juzga el cambio real a 7 días. Devuelve error medio de los tres modelos y la calidad de las
    ventas que habría mandado cada regla."""
    from datetime import timedelta

    by_player: dict[str, dict] = defaultdict(dict)
    rows = list(conn.execute(SQL_SERIES_DAYS))
    row_by_player: dict[str, dict] = defaultdict(dict)
    for r in rows:
        by_player[r.player_id][r.day] = r.v
        row_by_player[r.player_id][r.day] = r
    days = sorted({d for s in by_player.values() for d in s})
    if len(days) < warmup_days + HORIZON + 1:
        return {"error": "hace falta más histórico"}

    errs = {"baseline": [], "racha (actual)": [], "racha + tamaño": [], "racha + tamaño (mediana)": []}
    ventas = {"actual": [], "candidato": []}
    cortes = 0
    cut = days[0] + timedelta(days=warmup_days)
    while cut + timedelta(days=HORIZON) <= days[-1]:
        cortes += 1
        pasado = consecutive_segments(r for r in rows if r.day < cut)
        table = build_table(pasado)
        table_mag = build_table_magnitude(pasado)
        table_med = build_table_magnitude(pasado, stat="median")
        base = table.get("baseline")
        for pid, s in by_player.items():
            hoy, futuro = s.get(cut), s.get(cut + timedelta(days=HORIZON))
            if not hoy or not futuro:
                continue
            # La evaluación debe usar la misma serie continua que producción.
            source = getattr(row_by_player[pid][cut], "source", None)
            serie = []
            for ago in range(40):
                r = row_by_player[pid].get(cut - timedelta(days=ago))
                if r is None or getattr(r, "source", None) != source:
                    break
                serie.append(r.v)
            serie.reverse()
            real = futuro / hoy - 1
            a = expected(table, serie)
            b = expected_magnitude(table_mag, table, serie)
            errs["baseline"].append(abs(real - (base.mean if base else 0.0)))
            errs["racha (actual)"].append(abs(real - a.mean))
            errs["racha + tamaño"].append(abs(real - b.mean))
            errs["racha + tamaño (mediana)"].append(
                abs(real - expected_magnitude(table_med, table, serie).mean)
            )
            if streak(serie) <= -SELL_STREAK_RULE:
                ventas["actual"].append(real)
                if b.mean <= SELL_MATERIAL_DROP:
                    ventas["candidato"].append(real)
        cut += timedelta(days=step_days)

    def resumen(xs: list[float]) -> dict:
        if not xs:
            return {"n": 0}
        return {
            "n": len(xs),
            "cambio_medio_7d": round(sum(xs) / len(xs), 4),
            "acabaron_subiendo": round(sum(1 for x in xs if x > 0) / len(xs), 3),
            "cayeron_mas_de_3pct": round(sum(1 for x in xs if x < -0.03) / len(xs), 3),
        }

    return {
        "cortes": cortes,
        "error_medio": {k: round(sum(v) / len(v), 4) for k, v in errs.items() if v},
        "n": len(errs["baseline"]),
        "ventas_mandadas": {k: resumen(v) for k, v in ventas.items()},
        "salto_titularidad": role_jump(conn, by_player),
    }


ROLE_JUMP = 0.30  # la probabilidad de titular sube 30 puntos o más en una semana


def role_jump(conn: Connection, by_player: dict[str, dict]) -> dict:
    """¿Anticipa el mercado un cambio de rol? Caso Adeyemi: pasa a titular y sube 2 M al día.

    Descriptivo, no un modelo: compara el cambio de valor a 7 días de quienes acaban de ganar la
    titularidad con el del resto de jugadores en los mismos días. Con poca historia de
    alineaciones (desde el 2026-09-09) la muestra es corta y se dice."""
    from datetime import timedelta

    prob: dict[str, dict] = defaultdict(dict)
    for r in conn.execute(SQL_AVAILABILITY_HISTORY):
        prob[r.player_id][r.day] = r.p
    saltan, resto = [], []
    for pid, ps in prob.items():
        vals = by_player.get(pid) or {}
        for d, p in ps.items():
            antes = ps.get(d - timedelta(days=7))
            hoy, futuro = vals.get(d), vals.get(d + timedelta(days=HORIZON))
            if antes is None or not hoy or not futuro:
                continue
            (saltan if p - antes >= ROLE_JUMP else resto).append(futuro / hoy - 1)

    def m(xs):
        return {"n": len(xs), "cambio_medio_7d": round(sum(xs) / len(xs), 4)} if xs else {"n": 0}

    return {"ganan_titularidad": m(saltan), "resto": m(resto)}


if __name__ == "__main__":  # pragma: no cover
    import json
    import sys

    from lfm.db.session import engine

    if len(sys.argv) > 1 and sys.argv[1] == "comparar":
        with engine().begin() as c:
            print(json.dumps(compare(c), indent=2, ensure_ascii=False))
    else:
        print("uso: python -m lfm.analysis.drift comparar")
