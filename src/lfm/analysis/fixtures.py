"""Dificultad de calendario a partir de los resultados oficiales.

Modelo de Poisson con fuerza de ataque y de defensa por equipo y ventaja de campo, encogido hacia
la media de la liga porque con cuatro o cinco jornadas la muestra es pequeña (docs/criterio.md
§6.2). Solo usa datos de la API oficial: no depende de ninguna fuente externa.

    goles_esperados(local) = media_liga × ataque(local) × defensa(visitante) × ventaja_de_campo

De ahí sale la probabilidad de portería a cero, que es lo que decide los puntos de porteros y
defensas: `P(0 goles) = e^(−goles_esperados_en_contra)`.

Nunca usa el día del partido dentro de la jornada como criterio (regla 4 de CLAUDE.md).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

HOME_ADVANTAGE = 1.10
SHRINK = 4.0  # equivale a 4 partidos de "equipo medio" añadidos a cada equipo

SQL_PLAYED = text(
    "SELECT local_team_id AS l, visitor_team_id AS v, local_score AS ls, visitor_score AS vs "
    "FROM matches WHERE local_score IS NOT NULL AND visitor_score IS NOT NULL"
)

# La jornada que toca preparar: la primera cuyo once todavía no se ha bloqueado. En cuanto una
# arranca ya no se puede tocar su alineación, así que lo accionable pasa a ser la siguiente, y los
# puntos esperados tienen que mirar **esa**. El bloqueo es `weeks.opening_at` cuando lo tenemos —es
# el dato oficial— y si no, el primer partido: la J6 se bloqueó el 15 a las 17:00 aunque tenía un
# partido adelantado al día 3, así que la diferencia importa.
SQL_NEXT_WEEK = text(
    "SELECT m.week, COALESCE(w.opening_at, min(m.match_date)) AS lock_at "
    "FROM matches m LEFT JOIN weeks w ON w.week = m.week "
    "GROUP BY m.week, w.opening_at "
    "HAVING COALESCE(w.opening_at, min(m.match_date)) > now() "
    "ORDER BY m.week LIMIT 1"
)


def next_week(conn: Connection):
    """(jornada, cuándo se bloquea) de la próxima que se puede preparar. `None` si no queda ninguna."""
    return conn.execute(SQL_NEXT_WEEK).first()


SQL_UPCOMING = text(
    "SELECT m.match_id, m.week, m.local_team_id AS l, m.visitor_team_id AS v, m.match_date "
    "FROM matches m WHERE m.local_score IS NULL AND m.week >= :from_week "
    "ORDER BY m.week, m.match_date"
)


@dataclass(frozen=True)
class Strength:
    attack: float  # >1 marca más que la media
    defence: float  # >1 encaja más que la media
    played: int


@dataclass(frozen=True)
class Fixture:
    week: int
    team_id: str
    opponent_id: str
    home: bool
    xgf: float  # goles esperados a favor
    xga: float  # goles esperados en contra
    clean_sheet: float  # probabilidad de portería a cero


def team_strength(matches: list, *, shrink: float = SHRINK) -> tuple[dict[str, Strength], float]:
    """Devuelve la fuerza de cada equipo y la media de goles por equipo y partido."""
    if not matches:
        return {}, 0.0
    goals: dict[str, list[int]] = {}
    for m in matches:
        goals.setdefault(m.l, [0, 0, 0])
        goals.setdefault(m.v, [0, 0, 0])
        goals[m.l][0] += m.ls
        goals[m.l][1] += m.vs
        goals[m.l][2] += 1
        goals[m.v][0] += m.vs
        goals[m.v][1] += m.ls
        goals[m.v][2] += 1
    mu = sum(m.ls + m.vs for m in matches) / (2 * len(matches))
    if mu <= 0:
        return {}, 0.0
    out = {
        t: Strength(
            attack=(gf + shrink * mu) / ((n + shrink) * mu),
            defence=(ga + shrink * mu) / ((n + shrink) * mu),
            played=n,
        )
        for t, (gf, ga, n) in goals.items()
    }
    return out, mu


def expected_goals(strength: dict[str, Strength], mu: float, team: str, opponent: str, home: bool) -> float:
    a, d = strength.get(team), strength.get(opponent)
    if not a or not d:
        return mu
    return mu * a.attack * d.defence * (HOME_ADVANTAGE if home else 1 / HOME_ADVANTAGE)


def clean_sheet(xga: float) -> float:
    """Probabilidad de que el rival no marque, bajo Poisson."""
    return math.exp(-max(0.0, xga))


MAX_GOLES = 10  # con 4 goles esperados, la cola por encima de 10 pesa menos de una diezmilésima


def _poisson(k: int, lam: float) -> float:
    return math.exp(-lam) * lam**k / math.factorial(k)


def outcome(xgf: float, xga: float, *, max_goals: int = MAX_GOLES) -> tuple[float, float, float]:
    """(ganar, empatar, perder) sumando las dos Poisson marcador a marcador.

    Se tratan los goles de los dos equipos como independientes. Es la simplificación habitual y
    aquí no compensa refinarla: con cuatro jornadas, el encogimiento hacia la media de la liga
    mueve el resultado mucho más que la corrección de Dixon-Coles para marcadores bajos.

    Las tres probabilidades se normalizan para que sumen 1 y la cola que se queda fuera de
    `max_goals` no las deje cojas."""
    f = [_poisson(k, max(0.0, xgf)) for k in range(max_goals + 1)]
    a = [_poisson(k, max(0.0, xga)) for k in range(max_goals + 1)]
    ganar = sum(f[i] * a[j] for i in range(max_goals + 1) for j in range(i))
    empatar = sum(f[k] * a[k] for k in range(max_goals + 1))
    perder = sum(f[i] * a[j] for i in range(max_goals + 1) for j in range(i + 1, max_goals + 1))
    total = ganar + empatar + perder
    if total <= 0:
        return (0.0, 1.0, 0.0)
    return (ganar / total, empatar / total, perder / total)


def scores(xgf: float) -> float:
    """Probabilidad de que el equipo marque al menos un gol."""
    return 1 - math.exp(-max(0.0, xgf))


def upcoming(
    conn: Connection, strength: dict[str, Strength], mu: float, limit_weeks: int = 2
) -> dict[str, list[Fixture]]:
    """Próximos partidos por equipo, desde la jornada que toca preparar.

    Antes se tomaban «los partidos futuros», y eso metía los que quedaban de una jornada **ya
    bloqueada**: el once se calculaba contra rivales que ya no podías aprovechar."""
    proxima = next_week(conn)
    if proxima is None:
        return {}
    rows = conn.execute(SQL_UPCOMING, {"from_week": proxima.week}).all()
    weeks = sorted({r.week for r in rows})[:limit_weeks]
    out: dict[str, list[Fixture]] = {}
    for r in rows:
        if r.week not in weeks:
            continue
        for team, opp, home in ((r.l, r.v, True), (r.v, r.l, False)):
            xgf = expected_goals(strength, mu, team, opp, home)
            xga = expected_goals(strength, mu, opp, team, not home)
            out.setdefault(team, []).append(Fixture(r.week, team, opp, home, xgf, xga, clean_sheet(xga)))
    for fixtures in out.values():
        fixtures.sort(key=lambda f: f.week)
    return out


def load(
    conn: Connection, *, limit_weeks: int = 2
) -> tuple[dict[str, Strength], float, dict[str, list[Fixture]]]:
    strength, mu = team_strength(conn.execute(SQL_PLAYED).all())
    return strength, mu, upcoming(conn, strength, mu, limit_weeks) if strength else {}


# --- Dejarlo escrito para la web ---------------------------------------------------------------
#
# La PWA solo lee tablas: si tuviera que calcular esto, habría dos implementaciones del modelo y
# tarde o temprano dirían cosas distintas. El job lo calcula una vez al día y lo deja aquí.

SQL_CLEAR_FORECAST = text("DELETE FROM match_forecast")

SQL_SAVE_FORECAST = text(
    "INSERT INTO match_forecast (match_id, week, xg_local, xg_visitor, p_local, p_draw, p_visitor, "
    "cs_local, cs_visitor, played, computed_at) "
    "SELECT r.match_id, r.week, r.xg_local, r.xg_visitor, r.p_local, r.p_draw, r.p_visitor, "
    "r.cs_local, r.cs_visitor, r.played, now() "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(match_id text, week int, "
    "xg_local numeric, xg_visitor numeric, p_local numeric, p_draw numeric, p_visitor numeric, "
    "cs_local numeric, cs_visitor numeric, played int) "
    "ON CONFLICT (match_id) DO UPDATE SET week = EXCLUDED.week, xg_local = EXCLUDED.xg_local, "
    "xg_visitor = EXCLUDED.xg_visitor, p_local = EXCLUDED.p_local, p_draw = EXCLUDED.p_draw, "
    "p_visitor = EXCLUDED.p_visitor, cs_local = EXCLUDED.cs_local, cs_visitor = EXCLUDED.cs_visitor, "
    "played = EXCLUDED.played, computed_at = now()"
)


def forecast_rows(rows: list, strength: dict[str, Strength], mu: float, *, weeks: int) -> list[dict]:
    """Un pronóstico por partido de las próximas `weeks` jornadas."""
    if not strength:
        return []
    proximas = sorted({r.week for r in rows})[:weeks]
    out = []
    for r in rows:
        if r.week not in proximas:
            continue
        xg_l = expected_goals(strength, mu, r.l, r.v, True)
        xg_v = expected_goals(strength, mu, r.v, r.l, False)
        p_l, p_e, p_v = outcome(xg_l, xg_v)
        # `played` es el mínimo de los dos: la confianza la marca el equipo del que menos sabemos
        jugados = min((strength[t].played for t in (r.l, r.v) if t in strength), default=0)
        out.append(
            {
                "match_id": r.match_id,
                "week": r.week,
                "xg_local": round(xg_l, 3),
                "xg_visitor": round(xg_v, 3),
                "p_local": round(p_l, 3),
                "p_draw": round(p_e, 3),
                "p_visitor": round(p_v, 3),
                "cs_local": round(clean_sheet(xg_v), 3),
                "cs_visitor": round(clean_sheet(xg_l), 3),
                "played": jugados,
            }
        )
    return out


def save_forecast(conn: Connection, *, weeks: int = 6) -> int:
    """Recalcula y reescribe el pronóstico de las próximas jornadas. Devuelve cuántos partidos."""
    strength, mu = team_strength(conn.execute(SQL_PLAYED).all())
    proxima = next_week(conn)
    if proxima is None:
        return 0
    filas = forecast_rows(
        conn.execute(SQL_UPCOMING, {"from_week": proxima.week}).all(), strength, mu, weeks=weeks
    )
    if not filas:
        # sin partidos por delante no se borra lo que hay: preferimos un pronóstico de ayer a nada
        return 0
    conn.execute(SQL_CLEAR_FORECAST)
    conn.execute(SQL_SAVE_FORECAST, {"rows": json.dumps(filas)})
    return len(filas)
