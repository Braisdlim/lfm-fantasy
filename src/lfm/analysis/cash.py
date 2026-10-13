"""Saldo estimado de cada rival a partir del feed y las cláusulas observadas.

La API solo da `teamMoney` del equipo propio (verificado 2026-09-08: `null` para los rivales), así
que el saldo ajeno se reconstruye sumando el feed desde la creación de la liga:

    saldo estimado = presupuesto inicial + ingresos − gastos − subidas de cláusula observadas

- ingresos: ventas al sistema (33), ganancia por jornada (6) y ventas a otro mánager (1 siendo
  `user2Id`, el vendedor).
- gastos: fichajes en el mercado (31), compras a otro mánager (1 siendo `user1Id`, el comprador) y
  clausulazos pagados (32).
- El feed NO refleja las subidas de cláusula. Se detectan solo las que dejan una señal clara entre
  dos capturas de la misma plantilla. LaLiga cobra la mitad del aumento (regla oficial 1:2).
- Las capturas empiezan después de la creación de la liga; tampoco conocemos la compensación
  inicial de cada equipo. La diferencia con mi saldo real es una referencia, no una cota del error.

La diferencia observada en el equipo propio se recalcula en cada ejecución del job. Es una
referencia de incertidumbre, no un margen garantizado para los demás equipos.

Uso: `python -m lfm.analysis.cash` (recalcula y muestra el resultado).
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

INITIAL_BUDGET = 100_000_000  # docs/estrategia.md §1
INCOME_TYPES = (6, 33)  # ganancia por jornada, vendió
EXPENSE_TYPES = (31, 32)  # fichó del mercado, pagó cláusula

SQL_FLOWS = text(
    "SELECT lt.team_id, lt.manager_id, lt.manager_name, lt.is_me, "
    "COALESCE(SUM(a.amount) FILTER "
    "  (WHERE a.activity_type = ANY(:income) AND a.manager_id = lt.manager_id), 0) "
    "  + COALESCE(SUM(a.amount) FILTER "
    "  (WHERE a.activity_type = 1 AND a.manager2_id = lt.manager_id), 0) AS income, "
    "COALESCE(SUM(a.amount) FILTER "
    "  (WHERE a.activity_type = ANY(:expense) AND a.manager_id = lt.manager_id), 0) "
    "  + COALESCE(SUM(a.amount) FILTER "
    "  (WHERE a.activity_type = 1 AND a.manager_id = lt.manager_id), 0) AS expense, "
    "COUNT(a.activity_id) FILTER "
    "  (WHERE a.manager_id = lt.manager_id OR a.manager2_id = lt.manager_id) AS events "
    "FROM league_teams lt "
    "LEFT JOIN league_activity a ON a.league_id = lt.league_id "
    "WHERE lt.league_id = :league_id "
    "GROUP BY lt.team_id, lt.manager_id, lt.manager_name, lt.is_me "
    "ORDER BY lt.team_id"
)

SQL_MY_MONEY = text(
    "SELECT COALESCE(lt.team_money, (SELECT s.team_money FROM league_standing_daily s "
    "WHERE s.league_id = lt.league_id AND s.team_id = lt.team_id AND s.team_money IS NOT NULL "
    "ORDER BY s.day DESC LIMIT 1)) FROM league_teams lt "
    "WHERE lt.league_id = :league_id AND lt.team_id = :team_id"
)

SQL_SQUAD_SNAPSHOTS = text(
    # Conservar todas las capturas para detectar cláusulas, pero transferir solo lo que usa _players.
    # El JSON crudo almacenado queda intacto. Mantener el orden también dentro de cada plantilla.
    "SELECT endpoint, fetched_at, CASE WHEN jsonb_typeof(payload) = 'object' THEN "
    "jsonb_build_object('players', (SELECT COALESCE(jsonb_agg(jsonb_build_object("
    "'buyoutClause', p.player->'buyoutClause', 'playerMaster', jsonb_build_object("
    "'id', p.player#>'{playerMaster,id}', 'marketValue', p.player#>'{playerMaster,marketValue}'"
    ")) ORDER BY p.ordinality), '[]'::jsonb) "
    "FROM jsonb_array_elements(CASE WHEN jsonb_typeof(payload->'players') = 'array' "
    "THEN payload->'players' ELSE '[]'::jsonb END) WITH ORDINALITY AS p(player, ordinality))) "
    "ELSE payload END AS payload FROM raw_snapshots "
    "WHERE source = 'laliga_api' AND endpoint LIKE :endpoint AND fetched_at < :until "
    "ORDER BY endpoint, fetched_at"
)

SQL_PLAYER_TRANSFERS = text(
    "SELECT player_id, happened_at FROM league_activity "
    "WHERE league_id = :league_id AND activity_type IN (1, 31, 32, 33) "
    "AND player_id IS NOT NULL AND happened_at IS NOT NULL ORDER BY happened_at"
)

# La misma detección, dentro de Postgres: devuelve una fila por equipo en vez
# de volver a transferir todas las capturas y todos los traspasos cada hora.
# Conservar las capturas vacías y las fechas intermedias es esencial: quitarlas
# atribuiría subidas a jugadores que salieron de la plantilla o fueron vendidos.
SQL_CLAUSE_SPEND = text("""
WITH snapshots AS MATERIALIZED (
    SELECT id, endpoint, fetched_at, payload,
           regexp_replace(endpoint, '^.*/', '') AS team_id,
           row_number() OVER (
               PARTITION BY regexp_replace(endpoint, '^.*/', '')
               ORDER BY endpoint, fetched_at, id
           ) AS seq
    FROM raw_snapshots
    WHERE source = 'laliga_api' AND endpoint LIKE :endpoint AND fetched_at < :until
      AND jsonb_typeof(payload) = 'object'
      AND regexp_replace(endpoint, '^.*/', '') = ANY(:team_ids)
), players AS MATERIALIZED (
    SELECT DISTINCT ON (s.team_id, s.seq, p.player#>>'{playerMaster,id}')
           s.team_id, s.seq, s.fetched_at,
           p.player#>>'{playerMaster,id}' AS player_id,
           CASE WHEN jsonb_typeof(p.player->'buyoutClause') = 'number'
                THEN trunc((p.player->>'buyoutClause')::numeric)::bigint
                WHEN p.player->'buyoutClause' = 'true'::jsonb THEN 1
                WHEN p.player->'buyoutClause' = 'false'::jsonb THEN 0
                ELSE (p.player->>'buyoutClause')::bigint END AS clause,
           CASE WHEN jsonb_typeof(p.player#>'{playerMaster,marketValue}') = 'number'
                THEN trunc((p.player#>>'{playerMaster,marketValue}')::numeric)::bigint
                WHEN p.player#>'{playerMaster,marketValue}' = 'true'::jsonb THEN 1
                WHEN p.player#>'{playerMaster,marketValue}' IN ('false'::jsonb, '[]'::jsonb, '{}'::jsonb)
                THEN 0
                ELSE COALESCE(NULLIF(p.player#>>'{playerMaster,marketValue}', ''), '0')::bigint
           END AS value
    FROM snapshots s CROSS JOIN LATERAL jsonb_array_elements(
        CASE WHEN jsonb_typeof(s.payload->'players') = 'array'
             THEN s.payload->'players' ELSE '[]'::jsonb END
    ) WITH ORDINALITY p(player, ordinality)
    WHERE p.player#>>'{playerMaster,id}' IS NOT NULL
      AND p.player->>'buyoutClause' IS NOT NULL
    ORDER BY s.team_id, s.seq, p.player#>>'{playerMaster,id}', p.ordinality DESC
), pairs AS (
    SELECT p.team_id, p.clause, p.value, old.clause AS old_clause, old.value AS old_value
    FROM players p JOIN players old
      ON old.team_id = p.team_id AND old.seq = p.seq - 1 AND old.player_id = p.player_id
    WHERE NOT EXISTS (
        SELECT 1 FROM league_activity a
        WHERE a.league_id = :league_id AND a.activity_type IN (1, 31, 32, 33)
          AND a.player_id = p.player_id
          AND a.happened_at > old.fetched_at AND a.happened_at <= p.fetched_at
    )
), rounded AS (
    SELECT *, ((clause - old_clause + 25000) / 50000) * 50000 AS direct,
              ((clause - value + 25000) / 50000) * 50000 AS indirect
    FROM pairs
)
SELECT team_id, SUM(CASE
    WHEN clause <= greatest(old_clause, value) THEN 0
    WHEN direct >= 500000 AND abs(clause - old_clause - direct) <= 1000 THEN direct / 2
    WHEN old_clause <= old_value + 1000 AND value >= old_value
         AND indirect >= 500000 AND abs(clause - value - indirect) <= 1000 THEN indirect / 2
    ELSE 0 END)::bigint AS spend
FROM rounded GROUP BY team_id ORDER BY team_id
""")

SQL_SAVE = text(
    "INSERT INTO manager_cash_estimate "
    "(league_id, team_id, day, cash_estimate, uncertainty, method, clause_spend_observed) "
    "SELECT :league_id, r.team_id, CAST(:day AS date), r.cash_estimate, r.uncertainty, r.method, "
    "r.clause_spend_observed "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r("
    "team_id text, cash_estimate bigint, uncertainty bigint, method text, clause_spend_observed bigint) "
    "ON CONFLICT (league_id, team_id, day) DO UPDATE SET cash_estimate = EXCLUDED.cash_estimate, "
    "uncertainty = EXCLUDED.uncertainty, method = EXCLUDED.method, "
    "clause_spend_observed = EXCLUDED.clause_spend_observed"
)


def _players(payload: dict) -> dict[str, tuple[int, int]]:
    result = {}
    for player in payload.get("players") or []:
        master = player.get("playerMaster") or {}
        if master.get("id") is not None and player.get("buyoutClause") is not None:
            result[str(master["id"])] = (int(player["buyoutClause"]), int(master.get("marketValue") or 0))
    return result


def _rounded_manual_raise(amount: int) -> int:
    """Solo importes en pasos de 50 k€, como los aumentos observados en esta liga."""
    rounded = ((amount + 25_000) // 50_000) * 50_000
    return rounded if rounded >= 500_000 and abs(amount - rounded) <= 1_000 else 0


def manual_raise(old_clause: int, old_value: int, clause: int, value: int) -> int:
    """Solo una subida clara: la automática no supera max(cláusula previa, valor actual)."""
    if clause <= max(old_clause, value):
        return 0
    # Una subida manual sobre una cláusula ya alta deja un incremento redondo.
    direct = _rounded_manual_raise(clause - old_clause)
    if direct:
        return direct
    # Si antes la cláusula seguía al mercado, pudo moverse el valor entre capturas.
    if old_clause <= old_value + 1_000 and value >= old_value:
        return _rounded_manual_raise(clause - value)
    return 0


def observed_clause_spend(snapshots: list, transfers: list, team_ids: set[str]) -> dict[str, int]:
    """Gasto detectable desde la primera captura; no atribuye gastos a movimientos ambiguos."""
    by_player: dict[str, list[datetime]] = defaultdict(list)
    for player_id, happened_at in transfers:
        by_player[str(player_id)].append(happened_at)
    previous: dict[str, tuple[datetime, dict[str, tuple[int, int]]]] = {}
    spend: dict[str, int] = defaultdict(int)
    for endpoint, fetched_at, payload in snapshots:
        team_id = endpoint.rsplit("/", 1)[-1]
        if team_id not in team_ids or not isinstance(payload, dict):
            continue
        players = _players(payload)
        if team_id in previous:
            prior_at, prior_players = previous[team_id]
            for player_id, (clause, value) in players.items():
                if player_id not in prior_players:
                    continue
                if any(prior_at < t <= fetched_at for t in by_player[player_id]):
                    continue
                old_clause, old_value = prior_players[player_id]
                spend[team_id] += manual_raise(old_clause, old_value, clause, value) // 2
        previous[team_id] = fetched_at, players
    return dict(spend)


def estimate(
    flows: list[dict], my_money: int | None, clause_spend: dict[str, int] | None = None
) -> list[dict]:
    """Reconstruye cada saldo con importes reales del feed y calibra el error con mi saldo."""
    clause_spend = clause_spend or {}
    rows = []
    raw = {
        f["team_id"]: INITIAL_BUDGET
        + int(f["income"])
        - int(f["expense"])
        - clause_spend.get(f["team_id"], 0)
        for f in flows
    }
    mine = next((f for f in flows if f["is_me"]), None)
    observed_gap = 0
    if mine is not None and my_money is not None:
        observed_gap = int(my_money) - raw[mine["team_id"]]
    uncertainty = abs(observed_gap)
    for f in flows:
        exact = bool(f["is_me"] and my_money is not None)
        rows.append(
            {
                "team_id": f["team_id"],
                "manager_name": f["manager_name"],
                "is_me": bool(f["is_me"]),
                "income": int(f["income"]),
                "expense": int(f["expense"]),
                "clause_spend_observed": clause_spend.get(f["team_id"], 0),
                "events": int(f["events"]),
                "cash_estimate": int(my_money) if exact else raw[f["team_id"]],
                "uncertainty": 0 if exact else uncertainty,
                "method": "api" if exact else f"activity;observed_clauses;own_gap:{observed_gap}",
            }
        )
    return rows


def recompute(conn: Connection, *, league_id: str, day: date, team_id: str | None = None) -> dict[str, Any]:
    flows = [
        dict(r._mapping)
        for r in conn.execute(
            SQL_FLOWS, {"league_id": league_id, "income": list(INCOME_TYPES), "expense": list(EXPENSE_TYPES)}
        )
    ]
    if not flows:
        return {"teams": 0}
    my_team = team_id or next((f["team_id"] for f in flows if f["is_me"]), None)
    my_money = None
    if my_team:
        my_money = conn.execute(SQL_MY_MONEY, {"league_id": league_id, "team_id": my_team}).scalar()
    until = datetime.combine(day + timedelta(days=1), time.min, UTC)
    clause_spend = {
        row.team_id: int(row.spend)
        for row in conn.execute(
            SQL_CLAUSE_SPEND,
            {
                "endpoint": f"%/leagues/{league_id}/teams/%",
                "until": until,
                "league_id": league_id,
                "team_ids": [f["team_id"] for f in flows],
            },
        )
    }
    rows = estimate(flows, int(my_money) if my_money is not None else None, clause_spend)
    conn.execute(
        SQL_SAVE,
        {
            "league_id": league_id,
            "day": day.isoformat(),
            "rows": json.dumps(
                [
                    {
                        k: r[k]
                        for k in (
                            "team_id",
                            "cash_estimate",
                            "uncertainty",
                            "method",
                            "clause_spend_observed",
                        )
                    }
                    for r in rows
                ]
            ),
        },
    )
    return {
        "teams": len(rows),
        "uncertainty": rows[0]["uncertainty"] if rows else 0,
        "estimates": {r["manager_name"]: r["cash_estimate"] for r in rows},
        "observed_clause_spend": {r["manager_name"]: r["clause_spend_observed"] for r in rows},
    }


if __name__ == "__main__":  # pragma: no cover
    from datetime import UTC, datetime

    from lfm.config import settings
    from lfm.db.session import engine

    with engine().begin() as conn:
        print(
            json.dumps(
                recompute(conn, league_id=settings.league_id, day=datetime.now(UTC).date()),
                indent=2,
                ensure_ascii=False,
            )
        )
