"""Puntos esperados en las próximas jornadas.

Hay dos modelos, ambos conservados para poder compararlos con `python -m lfm.analysis.points
comparar` antes de sustituir uno por el otro (regla de CLAUDE.md: ningún modelo se publica sin
superar al anterior en prueba hacia delante).

**Modelo A — media de puntos totales (el actual).**

    tasa = (puntos_del_jugador + K × media_de_su_posición) ÷ (partidos + K)
    xPts = tasa × factor_de_calendario

`K` equivale a añadirle al jugador K partidos de rendimiento medio de su posición. Con K = 3 y
cuatro partidos jugados, la media propia pesa un 57 %.

**Modelo B — componentes por jornada (el nuevo).**

Predice desde los componentes que ``player_week_stats.stats`` ya guarda para cada jornada:
minutos, goles, asistencias, nota DAZN, portería a cero y tarjetas. El motivo de la separación:

- ~70 % de los puntos vienen de partes estables (minutos + nota DAZN). El calendario casi no
  las afecta, y mezclarlas con el ruido del gol contamina la media total varios partidos.
- El factor de calendario solo se aplica a las partes que dependen del rival: goles y asistencias
  (flojera defensiva del rival) y portería a cero (peligro ofensivo del rival). Los minutos y
  la nota se ajustan al mismo valor independientemente del partido que toque.

Cada componente tiene su propia media encogida hacia la media de posición (mismo K = 3).

Todo lo que sale de aquí es una **estimación**, y se muestra siempre con su tamaño de muestra
(docs/criterio.md §0, regla 4).
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

from lfm.analysis.fixtures import HOME_ADVANTAGE as HOME_FACTOR
from lfm.analysis.fixtures import Fixture, Strength

SHRINK_GAMES = 3.0  # partidos "prestados" de la media de la posición

# Qué hacer cuando FútbolFantasy no trae al jugador y no hay probabilidad de ser titular.
#
# Antes se dejaba el valor **sin ajustar**, con la idea de no inventarse un número. En la práctica
# eso premiaba a quien menos se sabe de él: el 2026-09-09 la mejor recomendación de compra de todo
# el mercado era un jugador sin dato, y su cifra competía contra las de los demás ya rebajadas por
# su titularidad.
#
# El número no se inventa, se mide. Contando tres ventanas (J1→J2, J1-2→J3, J1-3→J4) sobre los
# jugadores que venían jugando algo —los únicos a los que esto les afecta, porque sin ninguna
# jornada puntuada ya salen a cero—:
#
#     con dato de titularidad: jugaron la jornada siguiente 733 de 967 veces  = 76 %
#     sin dato de titularidad: jugaron la jornada siguiente  24 de  56 veces  = 43 %
#
# Así que a quien no tiene dato se le aplica ese 43 % medido. Con n=56 el intervalo va de un 30 %
# a un 56 %, así que es una cifra provisional: `python -m lfm.analysis.points calibrar` la vuelve
# a medir con los datos del día.
UNKNOWN_START_PROB = 0.43
GK, DEF, MID, FWD, COACH = 1, 2, 3, 4, 5

SQL_WEEK_POINTS = text(
    "SELECT w.player_id, p.position_id, w.total_points "
    "FROM player_week_stats w JOIN players p USING (player_id) "
    "WHERE w.total_points IS NOT NULL"
)


@dataclass(frozen=True)
class Expectation:
    rate: float  # puntos por jornada, encogidos
    played: int  # jornadas del jugador con dato
    xpts: float  # puntos esperados en la próxima jornada, ya ajustados por titularidad
    fixture_factor: float  # >1 calendario favorable, <1 desfavorable
    detail: str  # texto con los rivales
    start_prob: float | None = None  # la que publica la fuente, None si no la trae
    label: str = ""  # etiqueta del calendario según su percentil en la liga
    assumed_start_prob: bool = False  # si se ha usado `UNKNOWN_START_PROB` en su lugar


def position_means(rows) -> dict[int, float]:
    acc: dict[int, list[int]] = defaultdict(list)
    for r in rows:
        acc[r.position_id].append(r.total_points)
    return {pos: sum(v) / len(v) for pos, v in acc.items() if v}


def player_history(rows) -> dict[str, list[int]]:
    acc: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        acc[r.player_id].append(r.total_points)
    return dict(acc)


def shrunk_rate(points: list[int], position_mean: float, k: float = SHRINK_GAMES) -> float:
    """Media del jugador acercada a la de su posición según lo poco que sepamos de él."""
    n = len(points)
    return (sum(points) + k * position_mean) / (n + k) if (n + k) > 0 else position_mean


def fixture_factor(
    position_id: int,
    fixtures: list[Fixture],
    mu: float,
    strength: dict[str, Strength] | None = None,
) -> tuple[float, str]:
    """Cuánto ayuda o estorba el calendario, normalizado a 1 = rival medio en campo neutral.

    **Solo mide al rival y el campo, nunca la calidad del propio equipo.** La tasa del jugador ya
    incorpora lo bueno que es su equipo: un delantero del Barcelona puntúa mucho *porque* juega en
    el Barcelona. Multiplicar además por el ataque del Barcelona contaría dos veces lo mismo.
    Medido el 2026-09-08, ese doble conteo inflaba el factor de un jugador del Barcelona de 1,06 a
    1,60 y hundía el de uno del Getafe de 0,92 a 0,61.

    - Porteros y defensas: probabilidad de portería a cero según el **ataque del rival**.
    - Medios y delanteros: **flojera defensiva del rival**.
    """
    if not fixtures or mu <= 0 or not strength:
        return (1.0, "sin calendario conocido") if not fixtures else _cap_and_label(1.0, fixtures)
    vals: list[float] = []
    for f in fixtures:
        rival = strength.get(f.opponent_id)
        if rival is None:
            continue
        campo = HOME_FACTOR if f.home else 1 / HOME_FACTOR
        if position_id in (GK, DEF):
            # goles esperados en contra = media × ataque del rival, ajustado por campo
            xga = mu * rival.attack / campo
            vals.append(math.exp(-xga) / math.exp(-mu))
        else:
            vals.append(rival.defence * campo)
    if not vals:
        return _cap_and_label(1.0, fixtures)
    return _cap_and_label(sum(vals) / len(vals), fixtures)


def _cap_and_label(factor: float, fixtures: list[Fixture]) -> tuple[float, str]:
    factor = max(0.6, min(1.6, factor))  # el calendario matiza, no decide
    detail = ", ".join(f"{'vs' if f.home else 'en'} J{f.week}" for f in fixtures)
    return factor, detail


def expected(
    points: list[int],
    position_id: int,
    fixtures: list[Fixture],
    means: dict[int, float],
    mu: float,
    strength: dict[str, Strength] | None = None,
    start_prob: float | None = None,
) -> Expectation:
    """Puntos esperados en **la próxima jornada**, no en varias.

    El horizonte tiene que ser el mismo que el de la reventa (7 días) para poder sumar las dos
    cosas; contar dos jornadas contra una semana de mercado inflaría el valor deportivo.

    Se multiplica por la **probabilidad de ser titular**, que es el factor que más pesa: un jugador
    de 6 puntos que solo sale el 60 % de las veces vale 3,6. Si no hay dato se aplica
    `UNKNOWN_START_PROB`, que **no es un supuesto sino una medición** (ver su comentario), y la
    `Expectation` lo marca con `assumed_start_prob` para que quien lo muestre pueda decirlo.

    Y si el jugador no tiene ninguna jornada registrada no se le atribuye ningún punto: no es que
    valga la media de su posición, es que **no hay evidencia de que juegue**."""
    rate = shrunk_rate(points, means.get(position_id, 0.0))
    factor, detail = fixture_factor(position_id, fixtures, mu, strength)
    played = len(points)
    base = 0.0 if played == 0 else rate * factor
    aplicada = UNKNOWN_START_PROB if start_prob is None else start_prob
    return Expectation(
        rate=rate,
        played=played,
        xpts=base * aplicada,
        fixture_factor=factor,
        detail=detail,
        start_prob=start_prob,
        assumed_start_prob=start_prob is None,
    )


def percentile_label(factor: float, universe: list[float]) -> str:
    """Etiqueta el calendario por su sitio en la liga, no por un umbral inventado.

    Decir «factor 1,22» no significa nada para nadie; decir «está entre el 15 % de calendarios más
    fáciles de la jornada» sí, porque es una comparación con lo que hay."""
    if not universe:
        return "sin comparación"
    peores = sum(1 for x in universe if x < factor)
    pct = peores / len(universe)
    if pct >= 0.9:
        return "de los más fáciles de la jornada"
    if pct >= 0.7:
        return "más fácil que la mayoría"
    if pct <= 0.1:
        return "de los más difíciles de la jornada"
    if pct <= 0.3:
        return "más difícil que la mayoría"
    return "del montón"


SQL_SCOPED_POINTS = text(
    "WITH known AS (SELECT w.player_id, p.position_id, w.total_points "
    "FROM player_week_stats w JOIN players p USING(player_id) WHERE w.total_points IS NOT NULL), "
    "hist AS (SELECT player_id,jsonb_agg(total_points) points FROM known "
    "WHERE player_id IN (SELECT jsonb_array_elements_text(CAST(:ids AS jsonb))) GROUP BY player_id), "
    "means AS (SELECT position_id,avg(total_points)::float8 mean FROM known GROUP BY position_id) "
    "SELECT COALESCE((SELECT jsonb_object_agg(player_id,points) FROM hist),'{}'::jsonb) history, "
    "COALESCE((SELECT jsonb_object_agg(position_id,mean) FROM means),'{}'::jsonb) means"
)


def load(
    conn: Connection, *, player_ids: list[str] | None = None
) -> tuple[dict[str, list[int]], dict[int, float]]:
    if player_ids is not None:
        import json

        row = conn.execute(SQL_SCOPED_POINTS, {"ids": json.dumps(player_ids)}).one()
        return dict(row.history), {int(key): value for key, value in row.means.items()}
    rows = conn.execute(SQL_WEEK_POINTS).all()
    return player_history(rows), position_means(rows)


# =============================================================================
# Modelo B — puntos por componentes
# =============================================================================
#
# Lee los mismos datos que ya guardamos en player_week_stats.stats (JSONB con
# el desglose {estadística: [valor, puntos]}) y los usa en vez de la suma total.
#
# Ventaja: separa las partes estables (minutos, nota DAZN) de las ruidosas
# (goles, asistencias, portería a cero). El factor de calendario solo se
# aplica a las que dependen del rival.
#
# Formato confirmado el 2026-09-16 contra la BD:
#   goals:          [n_goles, pts]
#   goal_assist:    [n_asist, pts]
#   mins_played:    [minutos, pts]  (1 pto si 1-59 min, 2 si ≥60)
#   yellow_card:    [n, pts]         (−1 por amarilla)
#   red_card:       [n, pts]         (−3 por roja)
#   marca_points:   [−1, pts]        (el −1 es interno de la API; 0-4 pts)
#   goals_conceded: [n_goles_enc, pts] (0→CS: GK=4,DEF=3,MID=2,FWD=1)

SQL_WEEK_COMPONENTS = text(
    "SELECT w.player_id, p.position_id, w.week, "
    "  (w.stats->'goals'->1)::int          AS goals_pts, "
    "  (w.stats->'goal_assist'->1)::int    AS assists_pts, "
    "  (w.stats->'mins_played'->1)::int    AS mins_pts, "
    "  (w.stats->'yellow_card'->1)::int    AS yellow_pts, "
    "  (w.stats->'red_card'->1)::int       AS red_pts, "
    "  (w.stats->'marca_points'->1)::int   AS marca_pts, "
    "  (w.stats->'goals_conceded'->1)::int AS cs_pts "
    "FROM player_week_stats w JOIN players p USING(player_id) "
    "WHERE w.stats IS NOT NULL"
)


def component_history(rows) -> dict[str, dict[str, list[int]]]:
    """Puntos por componente y jornada, agrupados por jugador.

    Devuelve {player_id: {componente: [pts_j1, pts_j2, ...]}} con los mismos
    componentes que SQL_WEEK_COMPONENTS. El orden dentro de cada lista sigue
    el orden de jornadas en la BD (no necesariamente cronológico, pero
    consistente entre componentes del mismo jugador).
    """
    cols = ("goals_pts", "assists_pts", "mins_pts", "yellow_pts", "red_pts", "marca_pts", "cs_pts")
    acc: dict[str, dict[str, list[int]]] = {}
    for r in rows:
        pid = r.player_id
        if pid not in acc:
            acc[pid] = {c: [] for c in cols}
        for c in cols:
            acc[pid][c].append(getattr(r, c) or 0)
    return acc


def component_position_means(rows) -> dict[int, dict[str, float]]:
    """Media por posición de cada componente, para el encogimiento de Bayes."""
    cols = ("goals_pts", "assists_pts", "mins_pts", "yellow_pts", "red_pts", "marca_pts", "cs_pts")
    acc: dict[int, dict[str, list[int]]] = {}
    for r in rows:
        pos = r.position_id
        if pos not in acc:
            acc[pos] = {c: [] for c in cols}
        for c in cols:
            acc[pos][c].append(getattr(r, c) or 0)
    return {pos: {c: sum(v) / len(v) for c, v in comp.items() if v} for pos, comp in acc.items()}


def _shrunk(values: list[int], pos_mean: float, k: float = SHRINK_GAMES) -> float:
    """Media encogida hacia pos_mean con K partidos prestados (igual que shrunk_rate)."""
    n = len(values)
    return (sum(values) + k * pos_mean) / (n + k) if (n + k) > 0 else pos_mean


@dataclass(frozen=True)
class ComponentExpectation:
    """Puntos esperados desglosados por componente.

    Permite mostrar en la ficha del jugador de dónde vienen sus puntos
    (cuánto aportan los minutos vs. los goles vs. la nota DAZN).
    """

    xpts: float  # puntos esperados totales, ya ajustados por start_prob
    played: int  # jornadas con dato de componentes
    start_prob: float | None
    assumed_start_prob: bool
    fixture_factor: float
    detail: str
    # Desglose (antes de multiplicar por start_prob)
    mins_base: float = 0.0
    marca_base: float = 0.0
    goals_base: float = 0.0
    assists_base: float = 0.0
    cs_base: float = 0.0
    cards_base: float = 0.0


def expected_from_components(
    comp: dict[str, list[int]],
    position_id: int,
    fixtures: list[Fixture],
    pos_means: dict[str, float],
    mu: float,
    strength: dict[str, Strength] | None = None,
    start_prob: float | None = None,
) -> ComponentExpectation:
    """Puntos esperados desde componentes individuales.

    El factor de calendario se aplica solo a los componentes que dependen
    del rival:
      - goles y asistencias → factor ofensivo (flojera defensiva del rival)
      - portería a cero → factor defensivo (peligro ofensivo del rival)
    Los minutos, la nota DAZN y las tarjetas no dependen del rival y se
    suman directamente.

    Si el jugador no tiene ninguna jornada con componentes, xpts = 0 (igual
    que en expected(): sin evidencia de que juegue, no se le atribuyen puntos).
    """
    played = len(comp.get("mins_pts", []))
    if played == 0:
        aplicada = UNKNOWN_START_PROB if start_prob is None else start_prob
        factor, detail = _cap_and_label(1.0, fixtures)
        return ComponentExpectation(
            xpts=0.0,
            played=0,
            start_prob=start_prob,
            assumed_start_prob=start_prob is None,
            fixture_factor=factor,
            detail=detail,
        )

    def shrunk(key: str) -> float:
        return _shrunk(comp.get(key, []), pos_means.get(key, 0.0))

    # --- Partes fijas (sin factor de calendario) ---
    mins_base = shrunk("mins_pts")
    marca_base = shrunk("marca_pts")
    cards_base = shrunk("yellow_pts") + shrunk("red_pts")

    # --- Partes dependientes del rival ---
    # Para goles y asistencias: factor ofensivo (igual que medios/delanteros)
    # Para portería a cero: factor defensivo (igual que porteros/defensas)
    # Ambos se calculan desde fixture_factor() pasando la posición adecuada.
    if fixtures and mu > 0 and strength:
        attack_factor, _ = fixture_factor(FWD, fixtures, mu, strength)  # siempre ofensivo
        defense_factor, detail = fixture_factor(GK, fixtures, mu, strength)  # siempre defensivo
    else:
        attack_factor = 1.0
        defense_factor = 1.0
        _, detail = _cap_and_label(1.0, fixtures)

    goals_base = shrunk("goals_pts") * attack_factor
    assists_base = shrunk("assists_pts") * attack_factor
    cs_base = shrunk("cs_pts") * defense_factor

    # El factor de calendario que se expone en la ficha es el propio de la posición
    pos_factor, detail = fixture_factor(position_id, fixtures, mu, strength)

    total_base = mins_base + marca_base + cards_base + goals_base + assists_base + cs_base
    aplicada = UNKNOWN_START_PROB if start_prob is None else start_prob

    return ComponentExpectation(
        xpts=total_base * aplicada,
        played=played,
        start_prob=start_prob,
        assumed_start_prob=start_prob is None,
        fixture_factor=pos_factor,
        detail=detail,
        mins_base=mins_base,
        marca_base=marca_base,
        goals_base=goals_base,
        assists_base=assists_base,
        cs_base=cs_base,
        cards_base=cards_base,
    )


def load_components(conn: Connection) -> tuple[dict[str, dict[str, list[int]]], dict[int, dict[str, float]]]:
    """Carga los componentes por jornada y las medias de posición para el modelo B."""
    rows = conn.execute(SQL_WEEK_COMPONENTS).all()
    return component_history(rows), component_position_means(rows)


SQL_CONCENTRATION = text(
    "SELECT p.team_id AS club_id, t.name AS club, count(*) AS n, "
    "       SUM(v.market_value)::float8 AS value "
    "FROM league_squad_daily q JOIN players p ON p.player_id = q.player_id "
    "JOIN teams t ON t.team_id = p.team_id "
    "JOIN player_value_daily v ON v.player_id = q.player_id "
    "     AND v.day = (SELECT max(day) FROM player_value_daily WHERE source = 'laliga_api') "
    "WHERE q.league_id = :league_id AND q.team_id = :team_id "
    "  AND q.day = (SELECT max(day) FROM league_squad_daily WHERE team_id = :team_id) "
    "GROUP BY p.team_id, t.name"
)


# Medido el 2026-09-08 sobre las jornadas jugadas: el 13,9 % de la varianza de los puntos de un
# jugador en una jornada lo explica **qué hizo su equipo esa jornada**, y la media por jugador de un
# equipo se mueve 1,41 puntos de desviación típica entre jornadas. Tener varios del mismo club no
# cambia lo que esperas ganar, pero sí multiplica lo que puedes perder en una mala tarde de ese club.
TEAM_SHARE_OF_VARIANCE = 0.139
TEAM_WEEK_SD = 1.41
CONCENTRATION_ALERT = 0.25  # cuota de valor de la plantilla a partir de la cual se avisa


def concentration(conn: Connection, *, league_id: str, team_id: str) -> dict[str, dict]:
    """Cuánto de mi plantilla está en cada club, en número y en valor."""
    rows = conn.execute(SQL_CONCENTRATION, {"league_id": league_id, "team_id": team_id}).all()
    total = sum(r.value for r in rows) or 1.0
    return {r.club_id: {"club": r.club, "n": r.n, "value": r.value, "share": r.value / total} for r in rows}


SQL_AVAILABILITY = text(
    "SELECT player_id, day, fetched_at, "
    "CASE WHEN fetched_at >= now() - interval '26 hours' AND start_prob >= 0 AND start_prob < 1 "
    "THEN start_prob::float8 END AS start_prob, "
    "injured, suspended, booking_risk, minutes, games "
    "FROM player_availability WHERE day = (SELECT max(day) FROM player_availability)"
)


def availability(conn: Connection) -> dict[str, dict]:
    """Última foto de titularidad y disponibilidad por jugador."""
    return {
        r.player_id: {
            "start_prob": r.start_prob,
            "injured": r.injured,
            "suspended": r.suspended,
            "booking_risk": r.booking_risk,
            "minutes": r.minutes,
            "games": r.games,
            "day": getattr(r, "day", None),
            "fetched_at": getattr(r, "fetched_at", None),
        }
        for r in conn.execute(SQL_AVAILABILITY)
    }


# --- Volver a medir `UNKNOWN_START_PROB` --------------------------------------------------------

SQL_CALIBRATE = text("""
    WITH v AS (SELECT max(day) AS d FROM player_value_daily WHERE source = 'laliga_api'),
         a AS (SELECT max(day) AS d FROM player_availability)
    SELECT p.player_id, av.start_prob::float8 AS start_prob
    FROM players p
    CROSS JOIN v CROSS JOIN a
    JOIN player_value_daily val ON val.player_id = p.player_id AND val.day = v.d
    LEFT JOIN player_availability av ON av.player_id = p.player_id AND av.day = a.d
    WHERE val.market_value > 0 AND p.position_id BETWEEN 1 AND 4
""")

SQL_CALIBRATE_WEEKS = text(
    "SELECT player_id, week, total_points FROM player_week_stats WHERE total_points IS NOT NULL"
)

# Solo jornadas **enteras**. La J6 tenía un único partido adelantado (Real Sociedad 0-0 Celta el
# 2026-09-03) y contarla hundía las dos tasas por igual: casi nadie había jugado todavía.
SQL_COMPLETE_WEEKS = text("SELECT week FROM matches GROUP BY week HAVING count(*) = count(local_score)")


def calibrate(conn: Connection) -> dict:
    """¿Cuánto juegan de verdad los que no tienen probabilidad de ser titular?

    Se avanza jornada a jornada: con lo jugado hasta la J(n-1) se mira si jugó la J(n). Solo entran
    los que venían jugando algo, porque sin ninguna jornada puntuada ya salen a cero puntos
    esperados y esto no les afecta. «Jugó» es «puntuó algo»: quien no juega saca exactamente cero,
    y no tenemos minutos de toda la liga, solo de los jugadores de nuestra liga.

    Devuelve la cifra medida para poder comparar con `UNKNOWN_START_PROB` y actualizarla.
    """
    jugadores = conn.execute(SQL_CALIBRATE).all()
    puntos: dict[str, dict[int, int]] = defaultdict(dict)
    semanas: set[int] = set()
    for r in conn.execute(SQL_CALIBRATE_WEEKS):
        puntos[r.player_id][r.week] = r.total_points
        semanas.add(r.week)
    completas = set(conn.execute(SQL_COMPLETE_WEEKS).scalars())
    orden = sorted(semanas & completas)

    def jugo(pid: str, w: int) -> bool:
        return (puntos.get(pid, {}).get(w) or 0) != 0

    casos = {True: [0, 0], False: [0, 0]}  # con dato / sin dato -> [jugó, total]
    for i, objetivo in enumerate(orden):
        if i == 0:
            continue
        previas = orden[:i]
        for r in jugadores:
            if not any(jugo(r.player_id, w) for w in previas):
                continue
            celda = casos[r.start_prob is not None]
            celda[1] += 1
            celda[0] += 1 if jugo(r.player_id, objetivo) else 0

    def tasa(c: list[int]) -> float | None:
        return round(c[0] / c[1], 3) if c[1] else None

    return {
        "weeks": orden,
        "with_data": {"played": casos[True][0], "cases": casos[True][1], "rate": tasa(casos[True])},
        "without_data": {
            "played": casos[False][0],
            "cases": casos[False][1],
            "rate": tasa(casos[False]),
        },
        "in_use": UNKNOWN_START_PROB,
    }


# --- Comparación hacia delante: modelo A (media total) vs. modelo B (componentes) ---------------


def compare(conn: Connection) -> dict:
    """Prueba hacia delante: ¿cuál de los dos modelos predice mejor?

    Protocolo (criterio.md §4):
      - Ventana expansiva: entrena con J1..J(n-1), predice J(n).
      - Solo jornadas completas (sin partidos aplazados).
      - Sin factor de calendario (mu=0 y strength vacío): así el test mide el modelo estadístico
        puro, no el calendario —que es el mismo para ambos modelos—.
      - Baseline B0: predecir siempre la media de la posición.
      - Métrica: MAE (error medio absoluto).

    Devuelve los MAE de los tres modelos más el detalle por jornada.
    """
    # Puntos totales reales por jugador y jornada
    filas_totales = conn.execute(SQL_CALIBRATE_WEEKS).all()
    puntos_reales: dict[str, dict[int, int]] = defaultdict(dict)
    for r in filas_totales:
        puntos_reales[r.player_id][r.week] = r.total_points

    # Posición de cada jugador (para las medias)
    pos_jugador: dict[str, int] = {}
    for r in conn.execute(SQL_WEEK_POINTS).all():
        pos_jugador[r.player_id] = r.position_id

    # Componentes por jornada
    filas_comp = conn.execute(SQL_WEEK_COMPONENTS).all()
    comp_jugador_semana: dict[str, dict[int, dict[str, int]]] = defaultdict(lambda: defaultdict(dict))
    for r in filas_comp:
        comp_jugador_semana[r.player_id][r.week] = {
            "goals_pts": r.goals_pts or 0,
            "assists_pts": r.assists_pts or 0,
            "mins_pts": r.mins_pts or 0,
            "yellow_pts": r.yellow_pts or 0,
            "red_pts": r.red_pts or 0,
            "marca_pts": r.marca_pts or 0,
            "cs_pts": r.cs_pts or 0,
        }

    # Solo jornadas completas
    completas = sorted(set(conn.execute(SQL_COMPLETE_WEEKS).scalars()))
    if len(completas) < 2:
        return {"error": "Se necesitan al menos 2 jornadas completas para comparar"}

    cols_comp = ("goals_pts", "assists_pts", "mins_pts", "yellow_pts", "red_pts", "marca_pts", "cs_pts")

    errores_a: list[float] = []  # modelo A: media total
    errores_b: list[float] = []  # modelo B: componentes
    errores_b0: list[float] = []  # baseline: media de posición
    detalle: list[dict] = []

    for i, objetivo in enumerate(completas):
        if i == 0:
            continue
        previas = completas[:i]

        # Calcular medias de posición con datos hasta previas (modelo A y baseline)
        pts_prev: dict[str, list[int]] = defaultdict(list)
        for pid, semanas in puntos_reales.items():
            for w in previas:
                if w in semanas:
                    pts_prev[pid].append(semanas[w])
        pos_means_total: dict[int, float] = {}
        pos_acc: dict[int, list[int]] = defaultdict(list)
        for pid, pts in pts_prev.items():
            pos = pos_jugador.get(pid)
            if pos:
                pos_acc[pos].extend(pts)
        for pos, vals in pos_acc.items():
            pos_means_total[pos] = sum(vals) / len(vals) if vals else 0.0

        # Calcular medias de posición por componente (modelo B)
        comp_acc: dict[int, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
        for pid, semanas in comp_jugador_semana.items():
            pos = pos_jugador.get(pid)
            if not pos:
                continue
            for w in previas:
                if w in semanas:
                    for c in cols_comp:
                        comp_acc[pos][c].append(semanas[w].get(c, 0))
        pos_means_comp: dict[int, dict[str, float]] = {
            pos: {c: sum(v) / len(v) for c, v in comp.items() if v} for pos, comp in comp_acc.items()
        }

        # Puntuar cada jugador que tiene dato en la jornada objetivo
        n_j, err_a_j, err_b_j, err_b0_j = 0, 0.0, 0.0, 0.0
        jugadores_obj = [pid for pid, s in puntos_reales.items() if objetivo in s]
        for pid in jugadores_obj:
            real = puntos_reales[pid][objetivo]
            pos = pos_jugador.get(pid)
            if pos is None:
                continue
            pos_mean_a = pos_means_total.get(pos, 0.0)

            # Modelo A
            hist_a = [puntos_reales[pid][w] for w in previas if w in puntos_reales[pid]]
            pred_a = shrunk_rate(hist_a, pos_mean_a) if hist_a else pos_mean_a

            # Modelo B
            hist_b: dict[str, list[int]] = {c: [] for c in cols_comp}
            for w in previas:
                if w in comp_jugador_semana.get(pid, {}):
                    for c in cols_comp:
                        hist_b[c].append(comp_jugador_semana[pid][w].get(c, 0))
            pm_comp = pos_means_comp.get(pos, {})
            pred_b = (
                sum(_shrunk(hist_b[c], pm_comp.get(c, 0.0)) for c in cols_comp)
                if any(hist_b[c] for c in cols_comp)
                else pos_mean_a
            )

            err_a_j += abs(real - pred_a)
            err_b_j += abs(real - pred_b)
            err_b0_j += abs(real - pos_mean_a)
            n_j += 1

        if n_j:
            errores_a.append(err_a_j / n_j)
            errores_b.append(err_b_j / n_j)
            errores_b0.append(err_b0_j / n_j)
            detalle.append(
                {
                    "jornada_objetivo": objetivo,
                    "entrenamiento": previas,
                    "n_jugadores": n_j,
                    "mae_modelo_a": round(err_a_j / n_j, 3),
                    "mae_modelo_b": round(err_b_j / n_j, 3),
                    "mae_baseline": round(err_b0_j / n_j, 3),
                }
            )

    def mae(errs: list[float]) -> float | None:
        return round(sum(errs) / len(errs), 3) if errs else None

    gana_b = mae(errores_b) is not None and mae(errores_a) is not None and mae(errores_b) <= mae(errores_a)  # type: ignore[operator]
    return {
        "jornadas_evaluadas": [d["jornada_objetivo"] for d in detalle],
        "mae_baseline_b0": mae(errores_b0),
        "mae_modelo_a_media_total": mae(errores_a),
        "mae_modelo_b_componentes": mae(errores_b),
        "modelo_b_supera_a_modelo_a": gana_b,
        "veredicto": (
            "[OK] Modelo B (componentes) bate al modelo A: se puede sustituir"
            if gana_b
            else "[NO] Modelo B NO mejora al modelo A: no sustituir todavia"
        ),
        "detalle_por_jornada": detalle,
    }


if __name__ == "__main__":  # pragma: no cover
    import json
    import sys

    from lfm.db.session import engine

    if len(sys.argv) > 1 and sys.argv[1] == "calibrar":
        with engine().begin() as conn:
            print(json.dumps(calibrate(conn), indent=2, ensure_ascii=False))
    elif len(sys.argv) > 1 and sys.argv[1] == "comparar":
        with engine().begin() as conn:
            print(json.dumps(compare(conn), indent=2, ensure_ascii=False))
    else:
        print("uso: python -m lfm.analysis.points calibrar|comparar")
