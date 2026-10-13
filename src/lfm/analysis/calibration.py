"""¿Acertaban las recomendaciones? Se comprueba contra lo que pasó de verdad.

Regla 4 de `docs/criterio.md` §0: **una señal que no se mide no se publica**. Hasta ahora la
herramienta daba veredictos y nadie los revisaba nunca; esto cierra el círculo.

Cada fila de `recommendation_log` es una recomendación congelada en un ciclo de mercado. Pasado el
tiempo se puede contrastar con dos hechos que sí observamos:

- **La puja.** Si alguien fichó al jugador (actividad tipo 31), sabemos por cuánto. Entonces
  `bid_to_win` era acertado si nuestra puja habría ganado, y era caro si el jugador se fue por
  bastante menos de lo que decíamos que hacía falta.
- **El valor.** Siete días después sabemos cuánto vale. La reventa esperada se compara con la real
  y el veredicto se juzga por su consecuencia en euros, no por si "acertó" en abstracto.

Nada de esto necesita pedirle nada a la API: todo está ya en la base de datos.

Uso: `python -m lfm.analysis.calibration [--horizon 7]`
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.engine import Connection

HORIZON_DAYS = 7  # el mismo que usa el recomendador para la reventa
BUY_ACTIVITY = 31  # fichaje del mercado de la liga

# Solo se juzgan ciclos ya cerrados y con horizonte cumplido: si no, se estaría midiendo el futuro.
SQL_PENDING = text(
    "SELECT cycle_end, kind, player_id, verdict, score, subject "
    "FROM recommendation_log "
    "WHERE outcome IS NULL "
    "  AND cycle_end < now() "
    "  AND cycle_end < now() - CAST(:horizon || ' days' AS interval) "
    "ORDER BY cycle_end, kind, player_id"
)

SQL_VALUE_AT = text(
    "SELECT max(market_value)::float8 FROM player_value_daily "
    "WHERE player_id = :player_id AND day = CAST(:day AS date)"
)

# El fichaje que resolvió ese ciclo: el primero tras el cierre, dentro de una ventana corta.
SQL_TRANSFER = text(
    "SELECT amount::float8 AS amount FROM league_activity "
    "WHERE player_id = :player_id AND activity_type = :kind "
    "  AND happened_at >= :cycle_end AND happened_at < :cycle_end + interval '36 hours' "
    "ORDER BY happened_at LIMIT 1"
)

SQL_SAVE_OUTCOME = text(
    "UPDATE recommendation_log SET outcome = CAST(:outcome AS jsonb) "
    "WHERE cycle_end = :cycle_end AND kind = :kind AND player_id = :player_id"
)


@dataclass(frozen=True)
class Outcome:
    sold: bool  # ¿se lo llevó alguien en ese ciclo?
    paid: float | None  # cuánto pagó
    would_have_won: bool | None  # ¿nuestra puja habría bastado?
    value_then: float | None
    value_after: float | None
    real_return: float | None  # cambio real del valor en el horizonte
    predicted_return: float | None  # el que anunciaba la deriva
    profit_if_taken: float | None  # euros ganados o perdidos de haber seguido el consejo

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _f(subject: dict, key: str) -> float | None:
    v = subject.get(key)
    return float(v) if v is not None else None


def evaluate(conn: Connection, row, *, horizon: int = HORIZON_DAYS) -> Outcome:
    """Qué pasó con una recomendación concreta. Solo hechos observados, ningún supuesto."""
    subject = row.subject if isinstance(row.subject, dict) else json.loads(row.subject)
    cycle_day = row.cycle_end.date()
    value_then = (
        _f(subject, "value")
        or conn.execute(SQL_VALUE_AT, {"player_id": row.player_id, "day": cycle_day.isoformat()}).scalar()
    )
    value_after = conn.execute(
        SQL_VALUE_AT,
        {"player_id": row.player_id, "day": (cycle_day + timedelta(days=horizon)).isoformat()},
    ).scalar()

    paid = conn.execute(
        SQL_TRANSFER,
        {"player_id": row.player_id, "kind": BUY_ACTIVITY, "cycle_end": row.cycle_end},
    ).scalar()
    bid = _f(subject, "bid_to_win")
    real_return = (value_after - value_then) / value_then if value_then and value_after else None
    predicted = _f(subject, "drift")

    # Beneficio de haber hecho caso: lo que habría dado la operación, con las cifras reales.
    profit = None
    if row.kind == "buy" and bid and value_after is not None:
        # se compra a `bid` y se revende al sistema a lo que valga después
        profit = value_after * 1.03 - bid
    elif row.kind == "sell" and value_then is not None and value_after is not None:
        # vender evita la caída: lo ahorrado es lo que habría perdido esperando
        profit = (value_then - value_after) * 1.03

    return Outcome(
        sold=paid is not None,
        paid=paid,
        would_have_won=(bid >= paid) if (bid and paid) else None,
        value_then=value_then,
        value_after=value_after,
        real_return=real_return,
        predicted_return=predicted,
        profit_if_taken=profit,
    )


def backfill(conn: Connection, *, horizon: int = HORIZON_DAYS) -> dict:
    """Rellena el resultado de todas las recomendaciones ya juzgables."""
    pending = conn.execute(SQL_PENDING, {"horizon": str(horizon)}).all()
    for row in pending:
        outcome = evaluate(conn, row, horizon=horizon)
        conn.execute(
            SQL_SAVE_OUTCOME,
            {
                "outcome": json.dumps(outcome.as_dict()),
                "cycle_end": row.cycle_end,
                "kind": row.kind,
                "player_id": row.player_id,
            },
        )
    return {"evaluadas": len(pending)}


SQL_SCORED = text("SELECT kind, verdict, outcome, subject FROM recommendation_log WHERE outcome IS NOT NULL")


def report(conn: Connection) -> dict:
    """Cuadro de aciertos por veredicto, con las cifras que importan: euros y tamaño de muestra.

    Se informa **siempre con el n**, y con n pequeño no se saca conclusión: la propia tabla lo dice
    en vez de dar un porcentaje que suena a verdad."""
    filas = conn.execute(SQL_SCORED).all()
    por_veredicto: dict[str, dict] = {}
    for f in filas:
        o = f.outcome if isinstance(f.outcome, dict) else json.loads(f.outcome)
        vacio = {"n": 0, "beneficio": 0.0, "aciertos": 0, "con_beneficio": 0, "pujas_ok": 0, "pujas": 0}
        d = por_veredicto.setdefault(f.verdict, vacio)
        d["n"] += 1
        if o.get("profit_if_taken") is not None:
            d["con_beneficio"] += 1
            d["beneficio"] += o["profit_if_taken"]
            if o["profit_if_taken"] > 0:
                d["aciertos"] += 1
        if o.get("would_have_won") is not None:
            d["pujas"] += 1
            d["pujas_ok"] += 1 if o["would_have_won"] else 0
    for d in por_veredicto.values():
        d["beneficio_medio"] = d["beneficio"] / d["con_beneficio"] if d["con_beneficio"] else None
        d["tasa_acierto"] = d["aciertos"] / d["con_beneficio"] if d["con_beneficio"] else None
        d["puja_bastaba"] = d["pujas_ok"] / d["pujas"] if d["pujas"] else None
    return {"total": len(filas), "por_veredicto": por_veredicto}


if __name__ == "__main__":  # pragma: no cover
    import argparse

    from lfm.db.session import engine

    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, default=HORIZON_DAYS)
    args = ap.parse_args()
    with engine().begin() as conn:
        print(json.dumps(backfill(conn, horizon=args.horizon), ensure_ascii=False))
        print(json.dumps(report(conn), indent=2, ensure_ascii=False, default=float))
