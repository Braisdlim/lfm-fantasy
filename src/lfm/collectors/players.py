"""Colector de jugadores: /players → players + player_value_daily + player_week_stats.

Forma real de la respuesta (captura del 2026-09-08; fixture tests/fixtures/players.json): lista
plana de ~840 objetos con casi todos los números como texto:
  id, positionId ("1" portero … "5" entrenador), nickname (NO hay `name`), playerStatus
  (ok | injured | doubtful | suspended | out_of_league), marketValue, points, averagePoints,
  weekPoints [{weekNumber, points}], image (URL), teamId, lastSeasonPoints (opcional).
No trae el nombre del club: eso vendrá de /v3/teams-master (pendiente). El adaptador es
tolerante: si falta un campo deja NULL y lo cuenta en `warnings`.

Escritura: una sentencia por tabla. Las filas viajan como un único parámetro JSON y Postgres las
despliega con `jsonb_to_recordset`, así que el job hace 4 viajes a Neon en vez de ~3.500.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

# Claves bajo las que la API podría envolver la lista (hoy la devuelve plana)
LIST_KEYS = ("data", "elements", "players", "items")


def extract_list(payload: Any) -> list[dict]:
    """Lista plana o envuelta en {'data': [...]} y similares."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in LIST_KEYS:
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def _int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None


def _float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def normalize_player(p: dict) -> dict:
    team = p.get("team") or {}
    team_id = p.get("teamId", team.get("id"))
    image = p.get("image")
    images = p.get("images")
    if not image and isinstance(images, dict):
        image = (images.get("transparent") or {}).get("256x256") or (images.get("big") or {}).get("256x256")
    week_points = {
        int(w["weekNumber"]): _int(w.get("points"))
        for w in (p.get("weekPoints") or [])
        if isinstance(w, dict) and w.get("weekNumber") is not None
    }
    return {
        "player_id": str(p["id"]) if p.get("id") is not None else None,
        "name": p.get("name") or p.get("nickname") or "",
        "nickname": p.get("nickname"),
        "team_id": str(team_id) if team_id not in (None, "") else None,
        "team_name": team.get("name"),
        "position_id": _int(p.get("positionId")),
        "image_url": image or None,
        "market_value": _int(p.get("marketValue")),
        "status": p.get("playerStatus") or p.get("status"),
        "points_total": _int(p.get("points")),
        "average_points": _float(p.get("averagePoints")),
        "last_season_points": _int(p.get("lastSeasonPoints")),
        "week_points": week_points,
    }


def summarize(items: list[dict]) -> dict:
    """Cobertura de campos: qué claves trae la API y qué le falta a nuestro adaptador (dry-run)."""
    rows = [normalize_player(p) for p in items]
    keys = Counter(k for p in items for k in p)
    tracked = ("market_value", "team_id", "position_id", "status", "points_total", "average_points")
    return {
        "count": len(items),
        "keys": dict(keys.most_common()),
        "missing": {f: sum(1 for r in rows if r[f] is None) for f in tracked},
        "positions": dict(Counter(str(r["position_id"]) for r in rows).most_common()),
        "statuses": dict(Counter(str(r["status"]) for r in rows).most_common()),
        "weeks_seen": sorted({w for r in rows for w in r["week_points"]}),
    }


# --- SQL por lotes: un parámetro JSON por tabla -------------------------------------------------

SQL_TEAMS = text(
    "INSERT INTO teams (team_id, name) "
    "SELECT DISTINCT r.team_id, COALESCE(r.team_name, r.team_id) "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(team_id text, team_name text) "
    "WHERE r.team_id IS NOT NULL "
    "ON CONFLICT (team_id) DO NOTHING"  # el nombre real lo pondrá el colector de teams-master
)

SQL_PLAYERS = text(
    "INSERT INTO players (player_id, name, nickname, team_id, position_id, image_url) "
    "SELECT r.player_id, r.name, r.nickname, r.team_id, r.position_id, r.image_url "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r("
    "player_id text, name text, nickname text, team_id text, position_id int, image_url text) "
    # /players solo trae el apodo; si ya tenemos el nombre completo (plantillas), no lo pisamos
    "ON CONFLICT (player_id) DO UPDATE SET "
    "name = CASE WHEN players.name = '' OR players.name = players.nickname "
    "THEN EXCLUDED.name ELSE players.name END, "
    "nickname = EXCLUDED.nickname, team_id = EXCLUDED.team_id, position_id = EXCLUDED.position_id, "
    "image_url = EXCLUDED.image_url, updated_at = now()"
)

SQL_WEEK_STATS = text(
    "INSERT INTO player_week_stats (player_id, week, total_points) "
    "SELECT r.player_id, r.week, r.points "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(player_id text, week int, points int) "
    "ON CONFLICT (player_id, week) DO UPDATE SET total_points = EXCLUDED.total_points, fetched_at = now()"
)

# El cambio se guarda al escribir y **solo contra el día anterior de la API**: si ese día falta, o
# es de FútbolFantasy, queda NULL. Ninguna pantalla vuelve a restar valores por su cuenta.
SQL_VALUE_DAILY = text(
    "INSERT INTO player_value_daily "
    "(player_id, day, market_value, status, points_total, average_points, source, change, captured_at) "
    "SELECT r.player_id, CAST(:day AS date), r.market_value, r.status, r.points_total, r.average_points, "
    "'laliga_api', r.market_value - prev.market_value, now() "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r("
    "player_id text, market_value bigint, status text, points_total int, average_points numeric) "
    "LEFT JOIN player_value_daily prev ON prev.player_id = r.player_id "
    "  AND prev.day = CAST(:day AS date) - 1 AND prev.source = 'laliga_api' "
    "ON CONFLICT (player_id, day) DO UPDATE SET market_value = EXCLUDED.market_value, "
    "status = EXCLUDED.status, points_total = EXCLUDED.points_total, "
    "average_points = EXCLUDED.average_points, source = 'laliga_api', change = EXCLUDED.change, "
    "captured_at = EXCLUDED.captured_at"
)

# Al escribir el día D, el D+1 (si ya existía, p. ej. al rehacer un hueco) recalcula su cambio.
SQL_NEXT_CHANGE = text(
    "UPDATE player_value_daily n SET change = n.market_value - d.market_value "
    "FROM player_value_daily d WHERE d.day = CAST(:day AS date) AND n.day = d.day + 1 "
    "AND n.player_id = d.player_id AND n.source = d.source"
)

# Los valores del día de referencia con los que se compara una captura nueva.
SQL_LATEST_API_DAY = text(
    "SELECT max(day) FROM player_value_daily WHERE source = 'laliga_api' AND day < CAST(:day AS date)"
)
SQL_VALUES_OF_DAY = text(
    "SELECT player_id, market_value FROM player_value_daily WHERE day = CAST(:day AS date) "
    "AND source = 'laliga_api'"
)


def _json(rows: list[dict]) -> str:
    return json.dumps(rows, ensure_ascii=False)


def collect_players_from_payload(payload: Any, conn: Connection, *, day: date) -> dict:
    rows = [normalize_player(p) for p in extract_list(payload)]
    # Un jugador repetido en la respuesta haría que el ON CONFLICT toque la misma fila dos veces en
    # el mismo lote, y eso tumba la transacción entera (el fallo del 2026-09-15 en otra tabla).
    rows = list({r["player_id"]: r for r in rows if r["player_id"]}.values())
    warnings = [f"sin marketValue: {r['player_id']}" for r in rows if r["market_value"] is None]
    week_rows = [
        {"player_id": r["player_id"], "week": week, "points": points}
        for r in rows
        for week, points in r["week_points"].items()
    ]
    # Un valor nulo o cero es un dato que falta, no un precio: no se escribe.
    value_rows = [r for r in rows if r["market_value"] is not None and r["market_value"] > 0]

    conn.execute(
        SQL_TEAMS, {"rows": _json([{"team_id": r["team_id"], "team_name": r["team_name"]} for r in rows])}
    )
    conn.execute(SQL_PLAYERS, {"rows": _json(rows)})
    if week_rows:
        conn.execute(SQL_WEEK_STATS, {"rows": _json(week_rows)})
    if value_rows:
        conn.execute(SQL_VALUE_DAILY, {"rows": _json(value_rows), "day": day.isoformat()})
        conn.execute(SQL_NEXT_CHANGE, {"day": day.isoformat()})

    return {
        "players": len(rows),
        "week_rows": len(week_rows),
        "warnings": warnings[:10],
        "warnings_total": len(warnings),
    }


# LaLiga Fantasy tiene ~670 jugadores. Una respuesta con muchos menos es una respuesta a medias
# (pasa mientras recalculan valores), y guardarla deja el día con huecos que además bloquean el
# reintento: el job ve «ya hay valores de hoy» y no vuelve a pedirlos.
MIN_PLAYERS = 400


class IncompleteResponse(Exception):
    """La API respondió 200 pero con datos que no pueden ser la foto completa."""


class StaleSnapshot(Exception):
    """Los valores son los del día anterior: LaLiga aún no los ha cambiado (o ya los teníamos)."""


# Medido del 08/09 al 19/09: cada cambio diario mueve entre 559 y 578 de ~850 jugadores (≈ 67 %), y
# dos capturas del mismo día difieren en 0-2. Por debajo de un 5 % no es un día nuevo.
MIN_CHANGED_SHARE = 0.05


def is_stale(new: dict[str, int], previous: dict[str, int]) -> tuple[bool, float]:
    """¿Son estos valores los mismos que los del último día guardado? Devuelve (rancio, % cambiado)."""
    comunes = [k for k in new if k in previous]
    if len(comunes) < 100:
        return False, 1.0  # sin referencia suficiente no se puede afirmar nada
    cambiados = sum(1 for k in comunes if new[k] != previous[k])
    share = cambiados / len(comunes)
    return share < MIN_CHANGED_SHARE, share


def collect_players(client, conn: Connection, *, day: date, min_players: int = MIN_PLAYERS) -> dict:
    """/players → valores del **día de valor** `day` (ver `lfm.valueday`).

    Tres comprobaciones antes de escribir, porque un día mal escrito ya no se arregla solo:
    completa (≥ `min_players`), sin ceros, y **nueva**: si se parece al último día guardado es que
    LaLiga todavía no ha cambiado los valores y guardarla duplicaría ese día con otra fecha."""
    payload = client.players()
    items = [p for p in extract_list(payload) if isinstance(p, dict) and p.get("id") is not None]
    if len(items) < min_players:
        raise IncompleteResponse(f"/players devolvió {len(items)} jugadores (mínimo esperado {min_players})")
    ultimo = conn.execute(SQL_LATEST_API_DAY, {"day": day.isoformat()}).scalar()
    if ultimo is not None:
        previos = {
            r.player_id: int(r.market_value) for r in conn.execute(SQL_VALUES_OF_DAY, {"day": str(ultimo)})
        }
        nuevos = {str(p["id"]): _int(p.get("marketValue")) for p in items if _int(p.get("marketValue"))}
        rancio, share = is_stale(nuevos, previos)
        if rancio:
            raise StaleSnapshot(
                f"los valores son los del {ultimo} (solo cambió el {share * 100:.1f} %): "
                f"LaLiga aún no ha publicado los del {day}"
            )
    return collect_players_from_payload(payload, conn, day=day)
