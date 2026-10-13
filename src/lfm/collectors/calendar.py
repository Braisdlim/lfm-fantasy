"""Colector de calendario: week/current + calendar?weekNumber=N → weeks + matches.

Formas reales (2026-09-08):
- week/current: {weekNumber, nextWeek, previousWeek, isLive, openingWeekDate, closingWeekDate}.
  `openingWeekDate` es el primer partido de la jornada: bloqueo del once y arranque de la
  protección automática de cláusulas 24 h antes (docs/estrategia.md §1).
- calendar?weekNumber=N: lista de {id, matchDate, localId, visitorId, matchState, localScore,
  visitorScore, featured}. `localId`/`visitorId` son ids de club (tabla teams).
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from lfm.collectors.players import _int, extract_list

SQL_WEEKS = text(
    "INSERT INTO weeks (week, opening_at, closing_at, is_live, next_week, fetched_at) "
    "SELECT r.week, CAST(r.opening_at AS timestamptz), CAST(r.closing_at AS timestamptz), r.is_live, "
    "r.next_week, now() "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r("
    "week int, opening_at text, closing_at text, is_live boolean, next_week int) "
    "ON CONFLICT (week) DO UPDATE SET opening_at = EXCLUDED.opening_at, closing_at = EXCLUDED.closing_at, "
    "is_live = EXCLUDED.is_live, next_week = EXCLUDED.next_week, fetched_at = now()"
)

SQL_MATCHES = text(
    "INSERT INTO matches (match_id, week, match_date, local_team_id, visitor_team_id, state, "
    "local_score, visitor_score, fetched_at) "
    "SELECT r.match_id, r.week, CAST(r.match_date AS timestamptz), r.local_team_id, r.visitor_team_id, "
    "r.state, r.local_score, r.visitor_score, now() "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(match_id text, week int, match_date text, "
    "local_team_id text, visitor_team_id text, state int, local_score int, visitor_score int) "
    "ON CONFLICT (match_id) DO UPDATE SET match_date = EXCLUDED.match_date, state = EXCLUDED.state, "
    "local_score = EXCLUDED.local_score, visitor_score = EXCLUDED.visitor_score, fetched_at = now()"
)


def normalize_week(payload: Any) -> dict | None:
    if not isinstance(payload, dict) or _int(payload.get("weekNumber")) is None:
        return None
    return {
        "week": _int(payload.get("weekNumber")),
        "opening_at": payload.get("openingWeekDate"),
        "closing_at": payload.get("closingWeekDate"),
        "is_live": bool(payload.get("isLive")),
        "next_week": _int(payload.get("nextWeek")),
    }


def normalize_matches(payload: Any, week: int) -> list[dict]:
    rows = []
    for m in extract_list(payload):
        if m.get("id") is None:
            continue
        rows.append(
            {
                "match_id": str(m["id"]),
                "week": week,
                "match_date": m.get("matchDate") or m.get("date"),
                "local_team_id": str(m["localId"]) if m.get("localId") is not None else None,
                "visitor_team_id": str(m["visitorId"]) if m.get("visitorId") is not None else None,
                "state": _int(m.get("matchState")),
                "local_score": _int(m.get("localScore")),
                "visitor_score": _int(m.get("visitorScore")),
            }
        )
    return rows


# Cuántas jornadas por delante se traen además de la actual. En Fantasy de élite (FPL,
# Fantasy Football Hub) el estándar de oro para planificar transferencias con el calendario
# FDR es de 5 jornadas ("fixture runs" de corto y medio plazo). Cada jornada es una petición
# ligera (~3 KB) en el job diario: 5 peticiones entran holgadamente en el límite seguro de la API.
WEEKS_AHEAD = 5
LAST_WEEK = 38


def collect_calendar(client, conn: Connection, *, weeks_ahead: int = WEEKS_AHEAD) -> dict:
    """Jornada actual y las siguientes → weeks + matches. Una petición por jornada, más una."""
    week = normalize_week(client.current_week())
    if week is None:
        return {"week": None, "matches": 0}
    conn.execute(SQL_WEEKS, {"rows": json.dumps([week])})
    # la API da la siguiente; a partir de ahí es sumar, que es como están numeradas
    siguiente = week["next_week"] or (week["week"] + 1)
    quiere = [week["week"], *range(siguiente, siguiente + weeks_ahead)]
    matches: list[dict] = []
    for w in dict.fromkeys(quiere):  # sin repetir y en orden
        if w and w <= LAST_WEEK:
            matches.extend(normalize_matches(client.calendar(w), w))
    matches = list({m["match_id"]: m for m in matches}.values())  # un id por lote
    if matches:
        conn.execute(SQL_MATCHES, {"rows": json.dumps(matches)})
    return {"week": week["week"], "opening_at": week["opening_at"], "matches": len(matches)}
