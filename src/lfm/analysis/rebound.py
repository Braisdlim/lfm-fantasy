"""Posible rebote: cuándo un jugador que está bajando puede darse la vuelta (2026-09-20).

De media, quien baja sigue bajando (drift.py): con 8+ días cayendo solo sube el 6,7 % a la semana.
Pero esa media mezcla a los que se hunden con los que están a punto de girar, y lo que da la vuelta
a una tendencia casi nunca es el precio: es un **hecho** que se ve antes de que el valor se mueva
(el valor cambia una vez al día, a las 00:15). Aquí se miden cuatro:

- `vuelve_lesion`: estaba lesionado y ya no.
- `gana_titularidad`: su probabilidad de titular sube 30 puntos o más en una semana.
- `gran_jornada`: 10 puntos o más en su último partido.
- `barato_para_su_rol`: titular (≥ 70 %) que vale menos de la mitad de lo que valen los titulares
  de su posición.

El calendario fácil no se mide: el pronóstico de cada día no se guardaba, así que no hay forma de
saber cuál era el calendario «de entonces» sin mirar el futuro.

**Nada se publica sin superar la prueba** (regla de CLAUDE.md): una señal solo cuenta si, sobre
jugadores que estaban bajando, los que la tenían subieron al menos 3 puntos más a 7 días que los
que no, **en las dos mitades de la historia por separado** y con muestra suficiente. Es la mitad
antigua contra la nueva: si el efecto era de pretemporada, la segunda mitad lo tumba.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Connection

from lfm.analysis import drift as drift_mod

FALLING = -3  # racha a partir de la cual un jugador «está bajando»
HORIZON = drift_mod.HORIZON
ROLE_JUMP = 0.30
BIG_WEEK = 10
STARTER = 0.70
CHEAP_FOR_ROLE = 0.5
MIN_LIFT = 0.03  # 3 puntos más que los que bajaban sin la señal: lo que cuesta ganar su subasta
MIN_N = 30
MIN_N_HALF = 10

LABELS = {
    "vuelve_lesion": "vuelve de lesión",
    "gana_titularidad": "gana la titularidad",
    "gran_jornada": "viene de una gran jornada",
    "barato_para_su_rol": "barato para su rol",
    "frena_la_caida": "frena la caída",
}
# «Frena la caída» (caso Tchouaméni): lleva 8+ días bajando y ya ha perdido más de un 10 %, pero
# en los últimos tres días apenas se mueve. Es la intuición de «ya ha tocado suelo».
BRAKE_STREAK = 8
BRAKE_FALLEN = -0.10
# El umbral no está elegido para un jugador: medido el 2026-09-20, cuanto más despacio cae en los
# últimos tres días, menos pierde la semana siguiente, y la separación aguanta en las dos mitades con
# cualquier corte (media a 7 días frente a −10 % de los que siguen cayendo):
#     −1 %: +0,5 % (n=145)   −1,5 %: −0,2 % (n=444)   −2 %: −1,1 % (n=826)   −3 %: −2,9 % (n=2.017)
# −2 % es el punto con muestra amplia en el que la pérdida esperada ya no justifica vender.
BRAKE_LAST3 = -0.02

SQL_VALUES = text(
    "SELECT player_id, day, market_value::float8 AS v FROM player_value_daily "
    "WHERE market_value > 0 ORDER BY player_id, day"
)
SQL_ACTIVE_VALUES = text(
    "SELECT player_id, day, market_value::float8 AS v FROM player_value_daily "
    "WHERE market_value > 0 AND (player_id = ANY(:player_ids) OR day >= :since) "
    "ORDER BY player_id, day"
)
SQL_AVAIL = text(
    "SELECT a.player_id, a.day, a.start_prob::float8 AS p, a.injured, p.position_id "
    "FROM player_availability a JOIN players p USING (player_id) ORDER BY a.player_id, a.day"
)
SQL_ACTIVE_AVAIL = text(
    "SELECT a.player_id, a.day, a.start_prob::float8 AS p, a.injured, p.position_id "
    "FROM player_availability a JOIN players p USING (player_id) "
    "WHERE a.day >= :since ORDER BY a.player_id, a.day"
)
# El día que se sabe es el siguiente al partido: el valor ya lo recoge a las 00:15.
SQL_BIG_WEEKS = text(
    "SELECT s.player_id, (min(m.match_date) AT TIME ZONE 'Europe/Madrid')::date + 1 AS day "
    "FROM player_week_stats s JOIN players p USING (player_id) "
    "JOIN matches m ON m.week = s.week AND p.team_id IN (m.local_team_id, m.visitor_team_id) "
    "WHERE s.total_points >= :pts AND m.match_date IS NOT NULL "
    "GROUP BY s.player_id, s.week"
)

SQL_SAVE = text(
    "INSERT INTO signal_check (signal, n, mean_7d, up_rate, control_mean, passes, detail) "
    "SELECT r.signal, r.n, r.mean_7d, r.up_rate, r.control_mean, r.passes, r.detail "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(signal text, n int, mean_7d float8, "
    "up_rate float8, control_mean float8, passes boolean, detail jsonb) "
    "ON CONFLICT (signal) DO UPDATE SET measured_at = now(), n = EXCLUDED.n, mean_7d = EXCLUDED.mean_7d, "
    "up_rate = EXCLUDED.up_rate, control_mean = EXCLUDED.control_mean, passes = EXCLUDED.passes, "
    "detail = EXCLUDED.detail"
)
SQL_PASSING = text(
    "SELECT signal, n, mean_7d, up_rate, control_mean, passes FROM signal_check "
    "WHERE passes OR COALESCE((detail->>'separa')::boolean, false)"
)
SQL_HAS_TABLE = text("SELECT to_regclass('signal_check') IS NOT NULL")


@dataclass(frozen=True)
class Signal:
    name: str
    n: int
    mean_7d: float
    up_rate: float
    control_mean: float
    rebound: bool = True  # pasa como rebote (sube); si no, solo separa (deja de caer)

    @property
    def label(self) -> str:
        return LABELS.get(self.name, self.name)


def events(values: dict[str, dict], avail: list, big_weeks: list) -> dict[str, set[tuple[str, date]]]:
    """Qué señal tenía cada jugador cada día. Solo con datos conocidos ese día."""
    out: dict[str, set[tuple[str, date]]] = defaultdict(set)
    por_jugador: dict[str, dict] = defaultdict(dict)
    por_dia: dict[date, list] = defaultdict(list)
    for r in avail:
        por_jugador[r.player_id][r.day] = r
        por_dia[r.day].append(r)
    for pid, dias in por_jugador.items():
        for d, r in dias.items():
            ayer = dias.get(d - timedelta(days=1))
            if ayer is not None and ayer.injured and not r.injured:
                out["vuelve_lesion"].add((pid, d))
            antes = dias.get(d - timedelta(days=7))
            if antes is not None and r.p is not None and antes.p is not None and r.p - antes.p >= ROLE_JUMP:
                out["gana_titularidad"].add((pid, d))
    for d, filas in por_dia.items():
        titulares: dict[int, list[tuple[str, float]]] = defaultdict(list)
        for r in filas:
            v = values.get(r.player_id, {}).get(d)
            if v and r.p is not None and r.p >= STARTER and not r.injured:
                titulares[r.position_id].append((r.player_id, v))
        for lista in titulares.values():
            if len(lista) < 10:
                continue
            mediana = statistics.median(v for _, v in lista)
            for pid, v in lista:
                if v < CHEAP_FOR_ROLE * mediana:
                    out["barato_para_su_rol"].add((pid, d))
    for r in big_weeks:
        out["gran_jornada"].add((r.player_id, r.day))
    for pid, serie in values.items():
        dias = sorted(serie)
        vals = [serie[d] for d in dias]
        for i in range(BRAKE_STREAK + 1, len(vals)):
            w = vals[max(0, i - 39) : i + 1]
            if (
                drift_mod.streak(w) <= -BRAKE_STREAK
                and drift_mod.streak_change(w) <= BRAKE_FALLEN
                and w[-1] / w[-4] - 1 >= BRAKE_LAST3
            ):
                out["frena_la_caida"].add((pid, dias[i]))
    return out


def _known(evs: set[tuple[str, date]], pid: str, d: date) -> bool:
    """La señal apareció ese día o el anterior: fresca, y todavía sin descontar del todo."""
    return (pid, d) in evs or (pid, d - timedelta(days=1)) in evs


def measure(values: dict[str, dict], evs: dict[str, set]) -> dict[str, dict]:
    casos = []  # (día, jugador, cambio a 7 días) de todo el que estaba bajando
    for pid, serie in values.items():
        dias = sorted(serie)
        vals = [serie[d] for d in dias]
        for i, d in enumerate(dias):
            futuro = serie.get(d + timedelta(days=HORIZON))
            if not futuro or i < 3:
                continue
            ventana = vals[max(0, i - 39) : i + 1]
            if drift_mod.streak(ventana) > FALLING or drift_mod.unreliable(ventana):
                continue
            casos.append((d, pid, futuro / serie[d] - 1))
    if not casos:
        return {}

    def stats(xs):
        if not xs:
            return {"n": 0, "mean": 0.0, "median": 0.0, "up": 0.0}
        return {
            "n": len(xs),
            "mean": sum(xs) / len(xs),
            "median": statistics.median(xs),
            "up": sum(1 for x in xs if x > 0) / len(xs),
        }

    out = {}
    for name in LABELS:
        e = evs.get(name, set())
        con = [c for c in casos if _known(e, c[1], c[0])]
        sin = [c for c in casos if not _known(e, c[1], c[0])]
        # Las mitades se cortan por la fecha mediana **de los casos con la señal**, no de todos: con
        # un corte común, las jornadas (desde mediados de agosto) caían enteras en la mitad reciente
        # y la antigua era pretemporada sin ningún partido. Cada mitad se compara con el control de
        # sus mismos días. Y se exige también la **mediana**: un solo caso de +228 % no puede
        # aprobar una señal.
        corte = sorted(c[0] for c in con)[len(con) // 2] if con else None
        mitades = {}
        pasa = len(con) >= MIN_N
        # `cambia`: la señal separa de verdad a estos jugadores de los que bajan sin ella (≥ 3 puntos
        # en las dos mitades, en media y en mediana), aunque no lleguen a subir. Sirve para no
        # vender: «frena la caída» no anticipa una subida, pero sí que dejan de perder.
        cambia = len(con) >= MIN_N
        for mitad, reciente in (("antigua", False), ("reciente", True)):
            a = stats([c[2] for c in con if corte and (c[0] >= corte) == reciente])
            b = stats([c[2] for c in sin if corte and (c[0] >= corte) == reciente])
            mitades[mitad] = {
                "n": a["n"],
                "cambio_7d": round(a["mean"], 4),
                "mediana_7d": round(a["median"], 4),
                "control": round(b["mean"], 4),
                "control_mediana": round(b["median"], 4),
            }
            separa = (
                a["n"] >= MIN_N_HALF
                and a["mean"] - b["mean"] >= MIN_LIFT
                and a["median"] - b["median"] >= MIN_LIFT
            )
            cambia = cambia and separa
            pasa = pasa and separa and a["median"] > 0
        total, control = stats([c[2] for c in con]), stats([c[2] for c in sin])
        out[name] = {
            "signal": name,
            "n": total["n"],
            "mean_7d": round(total["mean"], 4),
            "up_rate": round(total["up"], 3),
            "control_mean": round(control["mean"], 4),
            "passes": pasa,
            "detail": {
                "mitades": mitades,
                "corte": str(corte),
                "mediana_7d": round(total["median"], 4),
                "separa": cambia,
                "que_es": LABELS[name],
            },
        }
    return out


def _load(conn: Connection, *, player_ids: list[str] | None = None, day: date | None = None):
    values: dict[str, dict] = defaultdict(dict)
    # active_now solo observa señales de hoy/ayer. Mantener el histórico entero
    # de los candidatos preserva sus rachas; los precios de todos los demás en
    # esos dos días preservan las medianas de «barato para su rol». El backtest
    # sigue leyendo el universo completo, sin recortes ni cambios de modelo.
    rows = (
        conn.execute(SQL_ACTIVE_VALUES, {"player_ids": player_ids, "since": day - timedelta(days=1)})
        if player_ids is not None and day is not None
        else conn.execute(SQL_VALUES)
    )
    for r in rows:
        values[r.player_id][r.day] = r.v
    # Hoy/ayer comparan lesión con el día anterior y titularidad con siete
    # días antes: el corte más antiguo necesario es hoy menos ocho días.
    avail = list(
        conn.execute(SQL_ACTIVE_AVAIL, {"since": day - timedelta(days=8)})
        if player_ids is not None and day is not None
        else conn.execute(SQL_AVAIL)
    )
    big = list(conn.execute(SQL_BIG_WEEKS, {"pts": BIG_WEEK}))
    return values, avail, big


def measure_and_save(conn: Connection) -> dict:
    values, avail, big = _load(conn)
    res = measure(values, events(values, avail, big))
    if res:
        conn.execute(SQL_SAVE, {"rows": json.dumps(list(res.values()), ensure_ascii=False)})
    return {k: {"n": v["n"], "pasa": v["passes"]} for k, v in res.items()}


def passing(conn: Connection) -> dict[str, Signal]:
    """Las señales que superaron su prueba: como rebote (`rebound=True`) o solo porque separan."""
    if not conn.execute(SQL_HAS_TABLE).scalar():
        return {}
    return {
        r.signal: Signal(
            r.signal, r.n, float(r.mean_7d), float(r.up_rate), float(r.control_mean), bool(r.passes)
        )
        for r in conn.execute(SQL_PASSING)
    }


def active_now(conn: Connection, player_ids: list[str], day: date) -> dict[str, list[str]]:
    """Qué señales tiene hoy cada uno de estos jugadores."""
    if not player_ids:
        return {}
    values, avail, big = _load(conn, player_ids=player_ids, day=day)
    evs = events(values, avail, big)
    ids = set(player_ids)
    out: dict[str, list[str]] = defaultdict(list)
    for name, e in evs.items():
        for pid in ids:
            if _known(e, pid, day):
                out[pid].append(name)
    return dict(out)


if __name__ == "__main__":  # pragma: no cover
    import sys

    from lfm.db.session import engine

    if len(sys.argv) > 1 and sys.argv[1] == "medir":
        with engine().begin() as c:
            values, avail, big = _load(c)
            res = measure(values, events(values, avail, big))
            if res:
                c.execute(SQL_SAVE, {"rows": json.dumps(list(res.values()), ensure_ascii=False)})
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print("uso: python -m lfm.analysis.rebound medir")
