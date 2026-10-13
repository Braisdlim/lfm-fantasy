"""Radar de rivales: qué le falta a cada uno, cuánto dinero tiene y cómo ficha.

Para ganar una puja o proteger una cláusula importa menos lo que vale un jugador que **quién más
lo quiere y puede pagarlo**. Este módulo reúne, por rival, tres hechos que ya estaban en la base
pero dispersos:

1. **Huecos**: con sus jugadores disponibles (sin lesionados ni sancionados), ¿puede alinear un
   once en alguna de las siete formaciones? Si no, cuántos le faltan y de qué posición. Un rival
   sin portero va a por un portero; es lo más parecido a saber su próxima puja sin adivinar.
2. **Saldo** estimado (`analysis/cash.py`) con su incertidumbre.
3. **Cómo ficha**: fichajes de los últimos 30 días y cuánto pagó sobre el valor del jugador ese día
   (mediana, con al menos tres casos). Es descriptivo, no una predicción de su próxima puja.

Con eso se cruzan los jugadores de la liga en el mercado vigente: **podría pujar** un rival que
necesita esa posición y cuyo saldo estimado (más la incertidumbre) llega al precio de salida. Se
dice «podría», nunca una probabilidad: no vemos las pujas de nadie hasta que se resuelven.

Escribe `rival_radar` (una fila por rival y día); la web solo la lee.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from statistics import median

from sqlalchemy import text
from sqlalchemy.engine import Connection

from lfm.analysis.eleven import FORMATIONS

POS_NAME = {1: "portero", 2: "defensa", 3: "centrocampista", 4: "delantero"}
POS_PLURAL = {1: "porteros", 2: "defensas", 3: "centrocampistas", 4: "delanteros"}
UNAVAILABLE_STATUS = {"injured", "suspended", "out_of_league"}
STYLE_DAYS = 30
MIN_CASES_FOR_OVERPAY = 3

SQL_SQUADS = text(
    """
WITH sq AS (
  SELECT sn.* FROM league_squad_daily sn
   WHERE sn.league_id = :league_id
     AND sn.day = (SELECT max(sm.day) FROM league_squad_daily sm
                    WHERE sm.league_id = sn.league_id AND sm.team_id = sn.team_id)
     AND NOT EXISTS (SELECT 1 FROM league_squad_daily sx
                      WHERE sx.league_id = sn.league_id AND sx.player_id = sn.player_id
                        AND sx.day > sn.day)),
d AS (SELECT max(day) AS day FROM player_value_daily WHERE source = 'laliga_api')
SELECT sq.team_id, p.player_id, p.position_id, v.status,
       a.injured, a.suspended
  FROM sq JOIN players p ON p.player_id = sq.player_id
  CROSS JOIN d
  LEFT JOIN player_value_daily v ON v.player_id = p.player_id AND v.day = d.day
  LEFT JOIN LATERAL (SELECT pa.injured, pa.suspended FROM player_availability pa
                      WHERE pa.player_id = p.player_id
                        AND pa.fetched_at >= now() - interval '26 hours'
                      ORDER BY pa.day DESC LIMIT 1) a ON true
"""
)

SQL_TEAMS = text(
    """
SELECT lt.team_id, lt.manager_id, lt.manager_name, lt.is_me,
       ce.cash_estimate::float8 AS cash, ce.uncertainty::float8 AS uncertainty
  FROM league_teams lt
  LEFT JOIN manager_cash_estimate ce ON ce.league_id = lt.league_id AND ce.team_id = lt.team_id
       AND ce.day = (SELECT max(day) FROM manager_cash_estimate WHERE league_id = :league_id)
 WHERE lt.league_id = :league_id
"""
)

# Fichajes del mercado (31) y compras a otro mánager (1, el comprador es manager_id) con el valor
# del jugador ese día en hora española.
SQL_SIGNINGS = text(
    """
SELECT a.manager_id, a.activity_type, a.amount::float8 AS amount, v.market_value::float8 AS value
  FROM league_activity a
  LEFT JOIN player_value_daily v ON v.player_id = a.player_id
       AND v.day = (a.happened_at AT TIME ZONE 'Europe/Madrid')::date
 WHERE a.league_id = :league_id AND a.activity_type IN (1, 31, 32)
   AND a.happened_at >= now() - make_interval(days => :days)
"""
)

SQL_MARKET = text(
    """
SELECT m.player_id, COALESCE(p.nickname, p.name) AS name, p.position_id,
       m.sale_price::float8 AS sale_price
  FROM market_offer m JOIN players p ON p.player_id = m.player_id
 WHERE m.league_id = :league_id AND m.kind = 'marketPlayerLeague'
   AND m.cycle_end = (SELECT max(cycle_end) FROM market_offer
                       WHERE league_id = :league_id AND kind = 'marketPlayerLeague')
   AND (m.expires_at IS NULL OR m.expires_at > now())
"""
)

SQL_DELETE = text("DELETE FROM rival_radar WHERE league_id = :league_id AND day = CAST(:day AS date)")
SQL_SAVE = text(
    "INSERT INTO rival_radar (league_id, team_id, day, detail) "
    "VALUES (:league_id, :team_id, CAST(:day AS date), CAST(:detail AS jsonb))"
)


@dataclass
class Needs:
    can_field: bool
    missing: dict[int, int]  # posición -> cuántos le faltan en la formación más cercana
    formation: tuple[int, int, int] | None  # la formación que menos le cuesta completar


def needs(counts: dict[int, int]) -> Needs:
    """Lo mínimo que le falta para alinear un once, mirando las siete formaciones del juego."""
    mejor: tuple[int, dict[int, int], tuple[int, int, int]] | None = None
    for f in FORMATIONS:
        req = {1: 1, 2: f[0], 3: f[1], 4: f[2]}
        falta = {pos: max(0, n - counts.get(pos, 0)) for pos, n in req.items()}
        total = sum(falta.values())
        if mejor is None or total < mejor[0]:
            mejor = (total, falta, f)
    assert mejor is not None
    total, falta, f = mejor
    return Needs(total == 0, {p: n for p, n in falta.items() if n}, f)


def needs_text(n: Needs) -> str:
    if n.can_field:
        return "Puede alinear un once completo."
    partes = [f"{k} {POS_NAME[p] if k == 1 else POS_PLURAL[p]}" for p, k in sorted(n.missing.items())]
    lista = partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " y " + partes[-1]
    return f"Le falta {lista} para alinear."


@dataclass
class Style:
    signings: int = 0
    clauses: int = 0
    overpay_median: float | None = None  # 0.12 = paga de mediana un 12 % sobre el valor
    overpay_cases: int = 0
    ratios: list[float] = field(default_factory=list)


def style(rows: list[dict]) -> Style:
    s = Style()
    for r in rows:
        if r["activity_type"] == 32:
            s.clauses += 1
            continue
        s.signings += 1
        if r["activity_type"] == 31 and r.get("value") and r.get("amount"):
            s.ratios.append(r["amount"] / r["value"] - 1)
    s.overpay_cases = len(s.ratios)
    if s.overpay_cases >= MIN_CASES_FOR_OVERPAY:
        s.overpay_median = round(median(s.ratios), 4)
    return s


def could_bid(n: Needs, cash: float | None, market: list[dict]) -> list[dict]:
    """Jugadores del mercado de la liga de una posición que le falta y a los que llega su saldo."""
    if n.can_field or cash is None:
        return []
    # La diferencia de mi saldo no es crédito demostrado para este rival.
    tope = cash
    out = [
        {
            "player_id": m["player_id"],
            "name": m["name"],
            "position_id": m["position_id"],
            "price": m["sale_price"],
        }
        for m in market
        if m["position_id"] in n.missing and m["sale_price"] is not None and m["sale_price"] <= tope
    ]
    return sorted(out, key=lambda x: -x["price"])


def _available(r: dict) -> bool:
    return not (r.get("injured") or r.get("suspended") or r.get("status") in UNAVAILABLE_STATUS)


def build(teams: list[dict], squads: list[dict], signings: list[dict], market: list[dict]) -> list[dict]:
    """Una ficha por rival. Pura: se prueba sin base de datos."""
    por_equipo: dict[str, dict[int, int]] = {}
    plantilla: dict[str, int] = {}
    for r in squads:
        plantilla[r["team_id"]] = plantilla.get(r["team_id"], 0) + 1
        if r.get("position_id") in POS_NAME and _available(r):
            c = por_equipo.setdefault(r["team_id"], {})
            c[r["position_id"]] = c.get(r["position_id"], 0) + 1
    por_manager: dict[str, list[dict]] = {}
    for s in signings:
        por_manager.setdefault(s["manager_id"], []).append(s)

    out = []
    for t in teams:
        if t["is_me"]:
            continue
        counts = por_equipo.get(t["team_id"], {})
        n = needs(counts)
        st = style(por_manager.get(t["manager_id"], []))
        out.append(
            {
                "team_id": t["team_id"],
                "manager_name": t["manager_name"],
                "squad_size": plantilla.get(t["team_id"], 0),
                "available": {POS_NAME[p]: counts.get(p, 0) for p in POS_NAME},
                "can_field": n.can_field,
                "missing": {POS_NAME[p]: k for p, k in n.missing.items()},
                "needs_text": needs_text(n),
                "cash": t["cash"],
                "cash_uncertainty": t["uncertainty"],
                "signings_30d": st.signings,
                "clauses_30d": st.clauses,
                "overpay_median": st.overpay_median,
                "overpay_cases": st.overpay_cases,
                "could_bid": could_bid(n, t["cash"], market),
            }
        )
    return out


def recompute(conn: Connection, *, league_id: str, day: date) -> dict:
    if conn.execute(text("SELECT to_regclass('rival_radar') IS NOT NULL")).scalar() is not True:
        return {"skipped": "sin tabla rival_radar (falta migrar)"}
    teams = [dict(r) for r in conn.execute(SQL_TEAMS, {"league_id": league_id}).mappings()]
    squads = [dict(r) for r in conn.execute(SQL_SQUADS, {"league_id": league_id}).mappings()]
    if not squads:
        return {"skipped": "sin plantillas"}
    signings = [
        dict(r) for r in conn.execute(SQL_SIGNINGS, {"league_id": league_id, "days": STYLE_DAYS}).mappings()
    ]
    market = [dict(r) for r in conn.execute(SQL_MARKET, {"league_id": league_id}).mappings()]
    fichas = build(teams, squads, signings, market)
    conn.execute(SQL_DELETE, {"league_id": league_id, "day": day.isoformat()})
    for f in fichas:
        conn.execute(
            SQL_SAVE,
            {
                "league_id": league_id,
                "team_id": f["team_id"],
                "day": day.isoformat(),
                "detail": json.dumps(f, ensure_ascii=False),
            },
        )
    return {"rivals": len(fichas), "short": sum(not f["can_field"] for f in fichas)}
