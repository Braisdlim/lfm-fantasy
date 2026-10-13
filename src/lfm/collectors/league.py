"""Colectores de mi liga: standing, plantillas, actividad y mercado.

Formas reales (capturas del 2026-09-08; fixtures anonimizados en tests/fixtures/):

- standing: lista de {position, previousPosition, points, team{id, managerId, manager{id, managerName},
  teamValue, teamPoints, teamMoney}}. `teamMoney` es null para los rivales.
- teams/{id}: {id, managerId, manager{}, teamMoney (solo el propio), teamValue, teamPoints, position,
  players[{buyoutClause, buyoutClauseLockedEndTime, isShielded, playerTeamId, playerMaster{id, name,
  nickname, positionId, marketValue, points, team{id, name, slug, badgeColor},
  lastStats[{weekNumber, totalPoints, stats{estadística: [valor, puntos]}}]}}]}.
  Es la única respuesta con nombre de club y con el desglose de puntos por jornada.
- activity/{index}: páginas de 50, más recientes primero: {id, activityTypeId, user1Id,
  user2Id (tipo 1: vendedor), playerMasterId, amount, weekNumber (tipo 6), createdAt}.
- market: lista de {id, discr (marketPlayerLeague = del sistema | marketPlayerTeam = de un manager),
  status, salePrice, expirationDate, numberOfBids, playerMaster{...}, sellerTeam{id, manager},
  playerTeam{buyoutClause, isShielded, buyoutClauseLockedEndTime}, directOffer (booleano),
  numberOfOffers}. `expirationDate` es el plazo de esa oferta; el de los que vende la liga marca
  el cierre del ciclo (ver market_cycle_end).

Escritura por lotes con jsonb_to_recordset (una sentencia por tabla, ver collectors/players.py).
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from lfm.collectors.players import _int, extract_list


def _s(v: Any) -> str | None:
    return None if v is None or v == "" else str(v)


def _json(rows: list[dict]) -> str:
    return json.dumps(rows, ensure_ascii=False)


# --- normalizadores puros --------------------------------------------------------------------------


def normalize_standing(payload: Any) -> list[dict]:
    rows = []
    for s in extract_list(payload):
        t = s.get("team") or {}
        m = t.get("manager") or {}
        points = s.get("points") if s.get("points") is not None else t.get("teamPoints")
        rows.append(
            {
                "team_id": _s(t.get("id")),
                "manager_id": _s(m.get("id") or t.get("managerId")),
                "manager_name": m.get("managerName"),
                "position": _int(s.get("position")),
                "previous_position": _int(s.get("previousPosition")),
                "points": _int(points),
                "team_value": _int(t.get("teamValue")),
            }
        )
    return [r for r in rows if r["team_id"]]


def normalize_squad(payload: Any) -> dict:
    """teams/{id} → equipo, jugadores con cláusula, clubes vistos y desglose por jornada."""
    payload = payload if isinstance(payload, dict) else {}
    m = payload.get("manager") or {}
    team = {
        "team_id": _s(payload.get("id")),
        "manager_id": _s(m.get("id") or payload.get("managerId")),
        "manager_name": m.get("managerName"),
        "team_money": _int(payload.get("teamMoney")),
        "team_value": _int(payload.get("teamValue")),
        "team_points": _int(payload.get("teamPoints")),
        "position": _int(payload.get("position")),
    }
    players: list[dict] = []
    clubs: dict[str, dict] = {}
    week_stats: list[dict] = []
    for pt in payload.get("players") or []:
        pm = pt.get("playerMaster") or {}
        pid = _s(pm.get("id"))
        if not pid:
            continue
        club = pm.get("team") or {}
        club_id = _s(club.get("id"))
        if club_id:
            clubs[club_id] = {
                "team_id": club_id,
                "name": club.get("name"),
                "slug": club.get("slug"),
                "badge_url": club.get("badgeColor"),
            }
        shielded = pt.get("isShielded")
        players.append(
            {
                "player_id": pid,
                "name": pm.get("name") or pm.get("nickname") or "",
                "nickname": pm.get("nickname"),
                "club_id": club_id,
                "position_id": _int(pm.get("positionId")),
                "market_value": _int(pm.get("marketValue")),
                "buyout_clause": _int(pt.get("buyoutClause")),
                "clause_locked_until": pt.get("buyoutClauseLockedEndTime"),
                "is_shielded": bool(shielded) if shielded is not None else None,
            }
        )
        for ws in pm.get("lastStats") or []:
            if not isinstance(ws, dict) or ws.get("weekNumber") is None:
                continue
            week_stats.append(
                {
                    "player_id": pid,
                    "week": int(ws["weekNumber"]),
                    "total_points": _int(ws.get("totalPoints")),
                    "stats": ws.get("stats") if isinstance(ws.get("stats"), dict) else None,
                }
            )
    # Sin deduplicar, un `ON CONFLICT` con la misma clave dos veces en el mismo lote revienta con
    # «cannot affect row a second time», y como es determinista **se lleva por delante todos los
    # reintentos**: el 2026-09-15 tumbó los cinco del job diario y la app pasó el día sin datos.
    # Pasó con la jornada 6, que tuvo un partido adelantado el día 3 y el resto el 15: un jugador
    # puede venir con dos entradas de la misma jornada. Se queda la más informada.
    return {
        "team": team,
        "players": _unique(players, lambda r: r["player_id"]),
        "clubs": list(clubs.values()),
        "week_stats": _unique(week_stats, lambda r: (r["player_id"], r["week"]), richer=_richness),
    }


def _richness(row: dict) -> tuple:
    """Cuánto sabemos de una fila, para quedarnos con la mejor de las repetidas."""
    return (row.get("stats") is not None, row.get("total_points") is not None)


def _unique(rows: list[dict], key, richer=None) -> list[dict]:
    """Una fila por clave, conservando el orden. `richer` decide cuál gana si hay repetidas."""
    out: dict = {}
    for r in rows:
        k = key(r)
        previa = out.get(k)
        if previa is None or (richer is not None and richer(r) > richer(previa)):
            out[k] = r
    return list(out.values())


def normalize_activity(item: dict) -> dict:
    return {
        "activity_id": _s(item.get("id")),
        "activity_type": _int(item.get("activityTypeId")),
        "manager_id": _s(item.get("user1Id")),
        "manager2_id": _s(item.get("user2Id")),
        "player_id": _s(item.get("playerMasterId")),
        "amount": _int(item.get("amount")),
        "week": _int(item.get("weekNumber")),
        "happened_at": item.get("createdAt"),
        "raw": item,
    }


KIND_LEAGUE = "marketPlayerLeague"  # lo vende la liga: puja ciega, todos expiran a la vez
KIND_TEAM = "marketPlayerTeam"  # lo vende un manager: oferta directa, plazo propio


def normalize_market(item: dict) -> dict:
    pm = item.get("playerMaster") or {}
    seller = item.get("sellerTeam") or {}
    pt = item.get("playerTeam") or {}
    # OJO: en este endpoint `directOffer` es un booleano (hay oferta o no), no trae el importe.
    # `numberOfOffers` sí dice cuántas. El importe habría que pedirlo a otro endpoint (pendiente).
    offer = item.get("directOffer")
    offer = offer if isinstance(offer, dict) else {}
    return {
        "market_id": _s(item.get("id")),
        "player_id": _s(pm.get("id")),
        "sale_price": _int(item.get("salePrice")),
        "owner_team_id": _s(seller.get("id")),
        "expires_at": item.get("expirationDate"),
        "kind": item.get("discr"),
        "num_bids": _int(item.get("numberOfBids")),
        "num_offers": _int(item.get("numberOfOffers")),
        "offer_money": _int(offer.get("money")),
        "buyout_clause": _int(pt.get("buyoutClause")),
        "raw": item,
    }


def market_cycle_end(rows: list[dict]) -> str | None:
    """Cuándo cierra el ciclo de mercado actual, o `None` si la captura no permite saberlo.

    El mercado de la liga rota a la hora en que se creó la liga (19:21 en la nuestra), no a
    medianoche: todos los jugadores que vende la liga comparten `expirationDate`, y ese instante
    identifica el ciclo. Ver docs/plan-app.md §A1.

    **Sin jugadores de la liga no hay ciclo.** Antes se usaba el plazo más próximo de las ventas de
    managers, y eso fabricaba ciclos falsos: mientras LaLiga rota el mercado (a veces tarda horas)
    la captura solo trae ventas de managers, su plazo pasaba a ser el «ciclo más reciente» y la web,
    las recomendaciones y los avisos se anclaban en un mercado con tres jugadores. Mejor no saber el
    ciclo que inventarlo."""
    league = sorted(r["expires_at"] for r in rows if r["kind"] == KIND_LEAGUE and r["expires_at"])
    return league[0] if league else None


# Estados de una captura del mercado (ver `assess_market`).
MARKET_OK = "ok"  # ciclo vigente con los jugadores de la liga: se puede guardar y recomendar
MARKET_ROTATING = "rotating"  # LaLiga aún no ha publicado el ciclo nuevo: no se toca nada
MARKET_EMPTY = "empty"  # respuesta vacía: tampoco se toca nada

# Sin ningún jugador de la liga no hay ciclo. No se exige un número mayor: la liga saca 13 por
# ciclo, pero el tamaño lo decide LaLiga y un umbral alto daría falsos «rotando». La señal fuerte
# es la otra: que su cierre todavía no haya pasado.
MIN_LEAGUE_PLAYERS = 1


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def assess_market(rows: list[dict], *, now: datetime | None = None) -> dict:
    """¿Es esta captura un mercado de verdad o LaLiga está a medio rotar?

    Es la pregunta que decide si se escribe algo. Una captura mala guardada es peor que ninguna:
    se convierte en «el mercado actual» y la app se desestabiliza hasta la siguiente pasada buena.
    Sana solo si trae jugadores de la liga y su cierre **todavía no ha pasado**."""
    now = now or datetime.now(UTC)
    if not rows:
        return {"state": MARKET_EMPTY, "why": "LaLiga devolvió el mercado vacío"}
    league_rows = [r for r in rows if r["kind"] == KIND_LEAGUE]
    if len(league_rows) < MIN_LEAGUE_PLAYERS:
        return {
            "state": MARKET_ROTATING,
            "why": f"solo {len(league_rows)} jugador(es) de la liga: el ciclo nuevo aún no está publicado",
        }
    cycle = _parse_ts(market_cycle_end(rows))
    if cycle is None or cycle <= now:
        return {
            "state": MARKET_ROTATING,
            "why": "el ciclo que devuelve LaLiga ya ha cerrado y todavía no ha rotado al nuevo",
        }
    return {"state": MARKET_OK, "why": None}


# --- SQL por lotes --------------------------------------------------------------------------------

SQL_LEAGUE_TEAMS = text(
    "INSERT INTO league_teams (league_id, team_id, manager_id, manager_name, is_me) "
    "SELECT :league_id, r.team_id, r.manager_id, r.manager_name, "
    "COALESCE(r.manager_id = CAST(:me AS text), false) "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(team_id text, manager_id text, manager_name text) "
    "ON CONFLICT (league_id, team_id) DO UPDATE SET manager_id = EXCLUDED.manager_id, "
    "manager_name = EXCLUDED.manager_name, is_me = EXCLUDED.is_me"
)

SQL_STANDING_DAILY = text(
    "INSERT INTO league_standing_daily "
    "(league_id, team_id, day, position, previous_position, points, team_value) "
    "SELECT :league_id, r.team_id, CAST(:day AS date), r.position, r.previous_position, r.points, "
    "r.team_value "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r("
    "team_id text, position int, previous_position int, points int, team_value bigint) "
    "ON CONFLICT (league_id, team_id, day) DO UPDATE SET position = EXCLUDED.position, "
    "previous_position = EXCLUDED.previous_position, points = EXCLUDED.points, "
    "team_value = EXCLUDED.team_value"
)

SQL_CLUBS = text(
    "INSERT INTO teams (team_id, name, slug, badge_url) "
    "SELECT r.team_id, COALESCE(r.name, r.team_id), r.slug, r.badge_url "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(team_id text, name text, slug text, badge_url text) "
    "ON CONFLICT (team_id) DO UPDATE SET name = EXCLUDED.name, slug = COALESCE(EXCLUDED.slug, teams.slug), "
    "badge_url = COALESCE(EXCLUDED.badge_url, teams.badge_url), updated_at = now()"
)

# Garantiza la FK y aporta el nombre completo (el colector de /players solo tiene el apodo)
SQL_SQUAD_PLAYERS = text(
    "INSERT INTO players (player_id, name, nickname, team_id, position_id) "
    "SELECT r.player_id, r.name, r.nickname, r.club_id, r.position_id "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r("
    "player_id text, name text, nickname text, club_id text, position_id int) "
    "ON CONFLICT (player_id) DO UPDATE SET name = EXCLUDED.name, nickname = EXCLUDED.nickname, "
    "updated_at = now()"
)

SQL_SQUAD_DAILY = text(
    "INSERT INTO league_squad_daily "
    "(league_id, team_id, player_id, day, buyout_clause, clause_locked_until, is_shielded, market_value) "
    "SELECT :league_id, :team_id, r.player_id, CAST(:day AS date), r.buyout_clause, "
    "CAST(r.clause_locked_until AS timestamptz), r.is_shielded, r.market_value "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(player_id text, buyout_clause bigint, "
    "clause_locked_until text, is_shielded boolean, market_value bigint) "
    "ON CONFLICT (league_id, team_id, player_id, day) DO UPDATE SET buyout_clause = EXCLUDED.buyout_clause, "
    "clause_locked_until = EXCLUDED.clause_locked_until, is_shielded = EXCLUDED.is_shielded, "
    "market_value = EXCLUDED.market_value"
)

SQL_WEEK_STATS = text(
    "INSERT INTO player_week_stats (player_id, week, total_points, stats) "
    "SELECT r.player_id, r.week, r.total_points, r.stats "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r("
    "player_id text, week int, total_points int, stats jsonb) "
    "ON CONFLICT (player_id, week) DO UPDATE SET "
    "total_points = COALESCE(EXCLUDED.total_points, player_week_stats.total_points), "
    "stats = COALESCE(EXCLUDED.stats, player_week_stats.stats), fetched_at = now()"
)

SQL_TEAM_MONEY = text(
    "UPDATE league_standing_daily SET team_money = :money "
    "WHERE league_id = :league_id AND team_id = :team_id AND day = CAST(:day AS date)"
)

SQL_CURRENT_MONEY = text(
    "UPDATE league_teams SET team_money = :money, money_fetched_at = now() "
    "WHERE league_id = :league_id AND team_id = :team_id"
)

SQL_ACTIVITY = text(
    "INSERT INTO league_activity (league_id, activity_id, activity_type, manager_id, manager2_id, "
    "player_id, amount, week, happened_at, raw) "
    "SELECT :league_id, r.activity_id, r.activity_type, r.manager_id, r.manager2_id, r.player_id, "
    "r.amount, r.week, CAST(r.happened_at AS timestamptz), r.raw "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(activity_id text, activity_type int, "
    "manager_id text, manager2_id text, player_id text, amount bigint, week int, happened_at text, "
    "raw jsonb) "
    "ON CONFLICT (league_id, activity_id) DO NOTHING"
)

SQL_MARKET = text(
    "INSERT INTO market_offer (league_id, cycle_end, player_id, market_id, kind, sale_price, "
    "owner_team_id, expires_at, num_bids, num_offers, offer_money, buyout_clause, raw) "
    "SELECT :league_id, CAST(:cycle_end AS timestamptz), r.player_id, r.market_id, r.kind, r.sale_price, "
    "r.owner_team_id, CAST(r.expires_at AS timestamptz), r.num_bids, r.num_offers, r.offer_money, "
    "r.buyout_clause, r.raw "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(market_id text, player_id text, sale_price bigint, "
    "owner_team_id text, expires_at text, kind text, num_bids int, num_offers int, offer_money bigint, "
    "buyout_clause bigint, raw jsonb) "
    # un jugador aparece una vez por ciclo: la lectura más reciente sustituye a la anterior
    "ON CONFLICT (league_id, cycle_end, player_id) DO UPDATE SET market_id = EXCLUDED.market_id, "
    "kind = EXCLUDED.kind, sale_price = EXCLUDED.sale_price, owner_team_id = EXCLUDED.owner_team_id, "
    "expires_at = EXCLUDED.expires_at, num_bids = EXCLUDED.num_bids, num_offers = EXCLUDED.num_offers, "
    "offer_money = EXCLUDED.offer_money, buyout_clause = EXCLUDED.buyout_clause, raw = EXCLUDED.raw, "
    "last_seen_at = now()"
)

# El snapshot de plantilla se reemplaza entero: si no, un jugador vendido se queda congelado
# en el día (docs/plan-app.md §A2).
SQL_SQUAD_CLEAR = text(
    "DELETE FROM league_squad_daily WHERE league_id = :league_id AND team_id = :team_id "
    "AND day = CAST(:day AS date)"
)


# --- colectores -----------------------------------------------------------------------------------


def collect_standing(
    client, conn: Connection, *, league_id: str, day: date, my_manager_id: str | None = None
) -> dict:
    """standing → league_teams + league_standing_daily. Devuelve los team_ids para las plantillas."""
    rows = normalize_standing(client.standing(league_id))
    conn.execute(SQL_LEAGUE_TEAMS, {"league_id": league_id, "me": my_manager_id, "rows": _json(rows)})
    conn.execute(SQL_STANDING_DAILY, {"league_id": league_id, "day": day.isoformat(), "rows": _json(rows)})
    mine = [r["team_id"] for r in rows if my_manager_id and r["manager_id"] == my_manager_id]
    return {
        "teams": len(rows),
        "team_ids": [r["team_id"] for r in rows],
        "my_team_id": mine[0] if mine else None,
    }


def collect_squads(client, conn: Connection, *, league_id: str, team_ids: list[str], day: date) -> dict:
    """teams/{id} de cada equipo → teams (nombres de club), players (nombre completo),
    league_squad_daily (cláusulas, bloqueo, blindaje) y player_week_stats (desglose)."""
    totals = Counter()
    for team_id in team_ids:
        sq = normalize_squad(client.team(league_id, team_id))
        tid = sq["team"]["team_id"] or team_id
        # Una plantilla vacía no existe en el juego (el mínimo son once): es LaLiga devolviendo una
        # respuesta a medias. Borrar y no insertar nada dejaba la app diciendo que no tienes
        # jugadores hasta la siguiente pasada, así que se conserva la foto anterior.
        if not sq["players"]:
            totals["empty_skipped"] += 1
            continue
        # el snapshot se reemplaza: así desaparecen los vendidos y los clausulados
        conn.execute(SQL_SQUAD_CLEAR, {"league_id": league_id, "team_id": tid, "day": day.isoformat()})
        if sq["clubs"]:
            conn.execute(SQL_CLUBS, {"rows": _json(sq["clubs"])})
        if sq["players"]:
            conn.execute(SQL_SQUAD_PLAYERS, {"rows": _json(sq["players"])})
            conn.execute(
                SQL_SQUAD_DAILY,
                {
                    "league_id": league_id,
                    "team_id": tid,
                    "day": day.isoformat(),
                    "rows": _json(sq["players"]),
                },
            )
        if sq["week_stats"]:
            conn.execute(SQL_WEEK_STATS, {"rows": _json(sq["week_stats"])})
        if sq["team"]["team_money"] is not None:
            money_params = {
                "money": sq["team"]["team_money"],
                "league_id": league_id,
                "team_id": tid,
                "day": day.isoformat(),
            }
            conn.execute(SQL_CURRENT_MONEY, money_params)
            conn.execute(
                SQL_TEAM_MONEY,
                money_params,
            )
        totals["players"] += len(sq["players"])
        totals["shielded"] += sum(1 for p in sq["players"] if p["is_shielded"])
        totals["week_stats"] += len(sq["week_stats"])
    return {"teams": len(team_ids), **totals}


def collect_activity(
    client, conn: Connection, *, league_id: str, full: bool = False, max_pages: int = 200
) -> dict:
    """activity/{index} paginado → league_activity (dedupe por id).

    Incremental: avanza mientras una página sea toda nueva y para en la primera que ya conocía en
    parte. `full=True` recorre hasta la primera página vacía aunque no inserte nada (rellena huecos).
    En la primera ejecución ambos modos recuperan toda la temporada."""
    inserted = pages = 0
    for index in range(max_pages):
        items = extract_list(client.activity(league_id, index))
        pages += 1
        if not items:
            break
        rows = [r for r in (normalize_activity(i) for i in items) if r["activity_id"]]
        result = conn.execute(SQL_ACTIVITY, {"league_id": league_id, "rows": _json(rows)})
        new = result.rowcount if result.rowcount is not None and result.rowcount >= 0 else 0
        inserted += new
        if not full and new < len(rows):
            break
    return {"pages": pages, "inserted": inserted}


def collect_market(
    client, conn: Connection, *, league_id: str, day: date | None = None, now: datetime | None = None
) -> dict:
    """market → market_offer, una fila por jugador y ciclo de mercado.

    Solo escribe si la captura está sana (`assess_market`). Si LaLiga está rotando, el crudo ya
    quedó en `raw_snapshots` y la tabla se queda con el último ciclo bueno, que es lo que la app
    debe seguir enseñando. El resumen lleva `state` para que el job decida si reintenta.

    `day` ya no se usa para la clave (el ciclo no coincide con el día natural); se acepta por
    compatibilidad con la firma anterior."""
    rows = [normalize_market(i) for i in extract_list(client.market(league_id))]
    rows = _unique([r for r in rows if r["market_id"] and r["player_id"]], key=lambda r: r["player_id"])
    health = assess_market(rows, now=now)
    cycle_end = market_cycle_end(rows) if health["state"] == MARKET_OK else None
    if cycle_end:
        conn.execute(SQL_MARKET, {"league_id": league_id, "cycle_end": cycle_end, "rows": _json(rows)})
    return {
        "state": health["state"],
        "why": health["why"],
        "players": len(rows),
        "cycle_end": cycle_end,
        "kinds": dict(Counter(r["kind"] for r in rows)),
        "with_offer": sum(1 for r in rows if r["offer_money"]),
    }
