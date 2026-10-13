"""Diario de decisiones: qué te ha dado de verdad cada fichaje y cada venta.

«¿Acertó?» (`analysis/calibration.py`) mide las recomendaciones como hipótesis: qué habría pasado
de seguirlas. Esto mide **lo que hiciste**: cada jugador que entró en tu plantilla, cuánto pagaste,
cuánto recuperaste (o vale hoy si sigue), los puntos que hizo mientras era tuyo y si ese día el
recomendador decía lo mismo que tú.

Para que una cifra suelta no engañe, cada operación se compara con una referencia sencilla: la
mediana de lo que cambió el valor de **todos los jugadores de su posición** en el mismo periodo.
Ganar 1 M con un jugador en una semana en la que todos subieron un 15 % no es mérito del fichaje.

Todo sale del feed de actividad y de las series que ya guardamos; no pide nada a la API. Se
reconstruye entero en cada pasada del diario (es derivado) en `decision_journal`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Connection

from lfm.db.batch_reads import BatchReads

MARKET_BUY, MANAGER_DEAL, CLAUSE_PAID, SOLD = 31, 1, 32, 33
ENTRY_KIND = {MARKET_BUY: "mercado", MANAGER_DEAL: "manager", CLAUSE_PAID: "clausula"}

SQL_ME = text("SELECT manager_id, team_id FROM league_teams WHERE league_id = :league_id AND is_me LIMIT 1")

# Operaciones que me afectan. `was_mine` detecta el clausulazo que me hicieron aunque el feed no
# diga a quién se lo quitaron: el jugador estaba en mi plantilla el día anterior.
SQL_EVENTS = text(
    """
SELECT a.activity_id, a.activity_type, a.manager_id, a.manager2_id, a.player_id,
       a.amount::float8 AS amount, a.happened_at,
       EXISTS (SELECT 1 FROM league_squad_daily s
                WHERE s.league_id = a.league_id AND s.team_id = :team_id AND s.player_id = a.player_id
                  AND s.day = (a.happened_at AT TIME ZONE 'Europe/Madrid')::date - 1) AS was_mine
  FROM league_activity a
 WHERE a.league_id = :league_id AND a.player_id IS NOT NULL
   AND a.activity_type IN (1, 31, 32, 33)
   AND (a.manager_id = :me OR a.manager2_id = :me OR a.activity_type = 32)
 ORDER BY a.happened_at, a.activity_id
"""
)


@dataclass
class Holding:
    player_id: str
    entry_at: datetime | None  # None: venía en la plantilla inicial
    entry_kind: str  # mercado | manager | clausula | inicial
    paid: float | None
    exit_at: datetime | None = None
    exit_kind: str | None = None  # venta_sistema | venta_manager | me_clausularon
    received: float | None = None


def build_holdings(events: list[dict], me: str) -> list[Holding]:
    """Empareja entradas y salidas de cada jugador en orden. Pura: se prueba sin base de datos."""
    abiertas: dict[str, Holding] = {}
    out: list[Holding] = []

    def cerrar(pid: str, at, kind: str, amount) -> None:
        h = abiertas.pop(pid, None) or Holding(pid, None, "inicial", None)
        h.exit_at, h.exit_kind, h.received = at, kind, amount
        out.append(h)

    for e in events:
        t, pid, at, amount = e["activity_type"], e["player_id"], e["happened_at"], e.get("amount")
        compra = t in (MARKET_BUY, CLAUSE_PAID, MANAGER_DEAL) and e["manager_id"] == me
        if compra:
            abiertas[pid] = Holding(pid, at, ENTRY_KIND[t], amount)
        elif t == SOLD and e["manager_id"] == me:
            cerrar(pid, at, "venta_sistema", amount)
        elif t == MANAGER_DEAL and e.get("manager2_id") == me:
            cerrar(pid, at, "venta_manager", amount)
        elif t == CLAUSE_PAID and e["manager_id"] != me and (e.get("manager2_id") == me or e.get("was_mine")):
            cerrar(pid, at, "me_clausularon", amount)
    return out + list(abiertas.values())


SQL_VALUE_ON = text(
    "SELECT market_value::float8 FROM player_value_daily WHERE player_id = :pid "
    "AND day <= (CAST(:at AS timestamptz) AT TIME ZONE 'Europe/Madrid')::date AND market_value > 0 "
    "ORDER BY day DESC LIMIT 1"
)
SQL_VALUE_NOW = text(
    "SELECT market_value::float8, day FROM player_value_daily WHERE player_id = :pid AND market_value > 0 "
    "ORDER BY day DESC LIMIT 1"
)
SQL_PLAYER = text("SELECT COALESCE(nickname, name) AS name, position_id FROM players WHERE player_id = :pid")

# Jornadas que arrancaron mientras era tuyo (el once se bloquea en el primer partido).
SQL_POINTS = text(
    """
WITH wk AS (SELECT week, min(match_date) AS starts FROM matches GROUP BY week)
SELECT wk.week, s.total_points,
       (SELECT l.current FROM lineup_daily l
         WHERE l.team_id = :team_id AND l.player_id = :pid
           AND l.day <= (wk.starts AT TIME ZONE 'Europe/Madrid')::date
           AND l.day >= (wk.starts AT TIME ZONE 'Europe/Madrid')::date - 3
         ORDER BY l.day DESC LIMIT 1) AS aligned
  FROM wk JOIN player_week_stats s ON s.week = wk.week AND s.player_id = :pid
 WHERE wk.starts >= CAST(:entry AS timestamptz) AND wk.starts < CAST(:exit AS timestamptz)
"""
)

# Referencia: mediana del cambio de valor de su posición en el mismo periodo.
SQL_BASELINE = text(
    """
SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY b.market_value::float8 / a.market_value - 1)
  FROM player_value_daily a
  JOIN player_value_daily b ON b.player_id = a.player_id AND b.source = a.source
       AND b.day = (CAST(:d1 AS timestamptz) AT TIME ZONE 'Europe/Madrid')::date
  JOIN players p ON p.player_id = a.player_id
 WHERE a.day = (CAST(:d0 AS timestamptz) AT TIME ZONE 'Europe/Madrid')::date
   AND a.market_value > 0 AND p.position_id = :pos
"""
)

# Lo que decía el recomendador en el ciclo de esa operación.
SQL_VERDICT = text(
    "SELECT verdict FROM recommendation_log WHERE player_id = :pid AND kind = :kind "
    "AND cycle_end >= CAST(:at AS timestamptz) - interval '5 minutes' "
    "AND cycle_end <= CAST(:at AS timestamptz) + interval '36 hours' ORDER BY cycle_end LIMIT 1"
)

SQL_DELETE = text("DELETE FROM decision_journal WHERE league_id = :league_id")
SQL_SAVE_BATCH = text(
    "INSERT INTO decision_journal (league_id, player_id, entry_at, open, detail) "
    "SELECT :league_id, r.pid, CAST(r.entry_at AS timestamptz), r.open, r.detail "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(pid text, entry_at text, open boolean, detail jsonb)"
)

FAR = "9999-12-31T00:00:00+00:00"
EPOCH = "2000-01-01T00:00:00+00:00"


def _iso(t) -> str | None:
    return t.isoformat() if t else None


def enrich(conn: Connection, h: Holding, *, team_id: str) -> dict:
    p = conn.execute(SQL_PLAYER, {"pid": h.player_id}).mappings().first() or {}
    entry = _iso(h.entry_at)
    exit_ = _iso(h.exit_at)
    v_entry = conn.execute(SQL_VALUE_ON, {"pid": h.player_id, "at": entry}).scalar() if entry else None
    now_row = conn.execute(SQL_VALUE_NOW, {"pid": h.player_id}).first()
    v_now = now_row[0] if now_row else None
    v_exit = conn.execute(SQL_VALUE_ON, {"pid": h.player_id, "at": exit_}).scalar() if exit_ else v_now

    # Dinero: lo recibido (o lo que vale hoy si sigue) menos lo pagado.
    salida = h.received if h.exit_at else v_now
    pnl = salida - h.paid if (salida is not None and h.paid is not None) else None
    ret = (salida / h.paid - 1) if (pnl is not None and h.paid) else None

    base = None
    if entry and p.get("position_id") is not None:
        fin = exit_ or (now_row[1].isoformat() + "T12:00:00+00:00" if now_row else None)
        if fin:
            base = conn.execute(SQL_BASELINE, {"d0": entry, "d1": fin, "pos": p["position_id"]}).scalar()

    semanas = (
        conn.execute(
            SQL_POINTS,
            {"pid": h.player_id, "team_id": team_id, "entry": entry or EPOCH, "exit": exit_ or FAR},
        )
        .mappings()
        .all()
    )
    puntos = sum(s["total_points"] or 0 for s in semanas)
    conocidas = [s for s in semanas if s["aligned"] is not None]
    alineado = sum((s["total_points"] or 0) for s in conocidas if s["aligned"])

    v_buy = (
        conn.execute(SQL_VERDICT, {"pid": h.player_id, "kind": "buy", "at": entry}).scalar()
        if entry
        else None
    )
    v_sell = (
        conn.execute(SQL_VERDICT, {"pid": h.player_id, "kind": "sell", "at": exit_}).scalar()
        if exit_
        else None
    )

    return {
        **{k: (_iso(v) if isinstance(v, datetime) else v) for k, v in asdict(h).items()},
        "name": p.get("name"),
        "position_id": p.get("position_id"),
        "open": h.exit_at is None,
        "value_at_entry": v_entry,
        "value_at_exit": v_exit,
        "value_now": v_now,
        "pnl": pnl,
        "return": ret,
        "baseline_return": base,
        # Diferencia con su posición en el mismo periodo: lo que aportó el fichaje en sí.
        "vs_baseline": (ret - base) if (ret is not None and base is not None) else None,
        "weeks": len(semanas),
        "points": puntos,
        "weeks_known_lineup": len(conocidas),
        "points_aligned": alineado if conocidas else None,
        "rec_at_entry": v_buy,
        "rec_at_exit": v_sell,
    }


def enrich_many(conn: Connection, holdings: list[Holding], *, team_id: str) -> list[dict]:
    reads = BatchReads(conn)
    reads.prefetch(SQL_PLAYER, [{"pid": h.player_id} for h in holdings], {"pid": "text"})
    reads.prefetch(SQL_VALUE_NOW, [{"pid": h.player_id} for h in holdings], {"pid": "text"})
    reads.prefetch(
        SQL_VALUE_ON,
        [{"pid": h.player_id, "at": _iso(at)} for h in holdings for at in (h.entry_at, h.exit_at) if at],
        {"pid": "text", "at": "text"},
    )
    reads.prefetch(
        SQL_POINTS,
        [
            {
                "pid": h.player_id,
                "team_id": team_id,
                "entry": _iso(h.entry_at) or EPOCH,
                "exit": _iso(h.exit_at) or FAR,
            }
            for h in holdings
        ],
        {"pid": "text", "team_id": "text", "entry": "text", "exit": "text"},
    )
    reads.prefetch(
        SQL_VERDICT,
        [
            {"pid": h.player_id, "at": _iso(at), "kind": kind}
            for h in holdings
            for at, kind in ((h.entry_at, "buy"), (h.exit_at, "sell"))
            if at
        ],
        {"pid": "text", "at": "text", "kind": "text"},
    )
    baselines = []
    for h in holdings:
        player = reads.execute(SQL_PLAYER, {"pid": h.player_id}).mappings().first()
        now = reads.execute(SQL_VALUE_NOW, {"pid": h.player_id}).first()
        if h.entry_at and player and player.get("position_id") is not None:
            end = _iso(h.exit_at) or (now[1].isoformat() + "T12:00:00+00:00" if now else None)
            if end:
                baselines.append({"d0": _iso(h.entry_at), "d1": end, "pos": player["position_id"]})
    reads.prefetch(SQL_BASELINE, baselines, {"d0": "text", "d1": "text", "pos": "int"})
    return [enrich(reads, h, team_id=team_id) for h in holdings]


def recompute(conn: Connection, *, league_id: str) -> dict:
    if conn.execute(text("SELECT to_regclass('decision_journal') IS NOT NULL")).scalar() is not True:
        return {"skipped": "sin tabla decision_journal (falta migrar)"}
    me_row = conn.execute(SQL_ME, {"league_id": league_id}).first()
    if not me_row:
        return {"skipped": "mi equipo aún no está en league_teams"}
    me, team_id = me_row
    events = [
        dict(r)
        for r in conn.execute(SQL_EVENTS, {"league_id": league_id, "me": me, "team_id": team_id}).mappings()
    ]
    holdings = build_holdings(events, me)
    filas = enrich_many(conn, holdings, team_id=team_id)
    conn.execute(SQL_DELETE, {"league_id": league_id})
    if filas:
        conn.execute(
            SQL_SAVE_BATCH,
            {
                "league_id": league_id,
                "rows": json.dumps(
                    [
                        {
                            "pid": f["player_id"],
                            "entry_at": f["entry_at"] or EPOCH,
                            "open": f["open"],
                            "detail": f,
                        }
                        for f in filas
                    ],
                    ensure_ascii=False,
                    default=str,
                ),
            },
        )
    return {"operations": len(filas), "open": sum(f["open"] for f in filas)}


if __name__ == "__main__":  # pragma: no cover
    from lfm.config import settings
    from lfm.db.session import engine

    with engine().begin() as c:
        print(json.dumps(recompute(c, league_id=settings.league_id), ensure_ascii=False))
