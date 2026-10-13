"""Recuperación puntual del histórico oficial de precios (endpoint público).

No añade peticiones a los cron habituales. Reanudable por jugador y con pausas
de 1,5 segundos, backoff y límites explícitos para una recuperación excepcional.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime

import httpx
from sqlalchemy import text

from lfm.api import endpoints as ep
from lfm.config import settings
from lfm.db.session import engine, save_raw
from lfm.valueday import value_day

SQL_SAVE = text(
    "INSERT INTO player_value_daily (player_id,day,market_value,source) "
    "SELECT :pid,r.day,r.value,'laliga_api' "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(day date,value bigint) "
    "ON CONFLICT (player_id,day) DO UPDATE SET market_value=EXCLUDED.market_value, "
    "source='laliga_api'"
)
SQL_CHANGES = text(
    "UPDATE player_value_daily v SET change=v.market_value-p.market_value "
    "FROM player_value_daily p WHERE v.player_id=:pid AND p.player_id=v.player_id "
    "AND p.day=v.day-1 AND p.source='laliga_api' AND v.source='laliga_api'"
)


def normalize(payload, today: date) -> list[dict]:
    if not isinstance(payload, list):
        raise ValueError("Histórico oficial con formato inesperado")
    rows = {}
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("date"), str):
            raise ValueError("Punto histórico sin fecha")
        # Fecha local de LaLiga: convertir primero a UTC desplazaría un día.
        day = datetime.fromisoformat(item["date"]).date()
        value = item.get("marketValue")
        if type(value) is not int:
            raise ValueError("Valor oficial inválido")
        if value <= 0 or day >= today:
            continue  # La captura de hoy conserva estado, puntos y valor originales.
        if day in rows and rows[day] != value:
            raise ValueError("Dos valores distintos para el mismo día")
        rows[day] = value
    return [{"day": day.isoformat(), "value": value} for day, value in sorted(rows.items())]


def run(*, limit: int = 25) -> dict:
    if not 1 <= limit <= 1000:
        raise ValueError("Límite fuera del rango de recuperación")
    today = value_day()
    with engine().connect() as conn:
        ids = (
            conn.execute(
                text(
                    "SELECT p.player_id FROM players p WHERE NOT EXISTS ("
                    " SELECT 1 FROM raw_snapshots r WHERE r.source='laliga_api' "
                    " AND r.endpoint LIKE '%/market-value' "
                    " AND r.params->>'recovery_player_id'=p.player_id) "
                    "ORDER BY CASE WHEN EXISTS (SELECT 1 FROM league_squad_daily s "
                    " JOIN league_teams t USING(league_id,team_id) "
                    " WHERE s.player_id=p.player_id AND t.is_me) THEN 0 "
                    " WHEN EXISTS (SELECT 1 FROM market_offer m WHERE m.player_id=p.player_id "
                    " AND (m.expires_at IS NULL OR m.expires_at>now())) THEN 1 "
                    " WHEN EXISTS (SELECT 1 FROM league_squad_daily s "
                    " WHERE s.player_id=p.player_id) THEN 2 ELSE 3 END, p.player_id LIMIT :limit"
                ),
                {"limit": limit},
            )
            .scalars()
            .all()
        )
    report = {"players_requested": len(ids), "players_restored": 0, "value_rows": 0, "unavailable": 0}
    with httpx.Client(headers=ep.DEFAULT_HEADERS, timeout=30) as client:
        for index, pid in enumerate(ids):
            path = ep.READ.player_market_value_history(settings.competition_id, pid)
            response = None
            for attempt in range(5):
                time.sleep(1.5)
                response = client.get(ep.BASE_URL + path, params={"x-lang": "es"})
                if response.status_code not in (429, 500, 502, 503, 504):
                    break
                time.sleep(max(10, float(response.headers.get("retry-after", 10)) * (attempt + 1)))
            if response.status_code == 404:
                report["unavailable"] += 1
                continue
            response.raise_for_status()
            payload = response.json()
            # Primero el crudo, incluso si posteriormente falla el contrato.
            save_raw("laliga_api", path, {"player_id": pid}, payload)
            rows = normalize(payload, today)
            with engine().begin() as conn:
                if rows:
                    conn.execute(SQL_SAVE, {"pid": pid, "rows": json.dumps(rows)})
                    conn.execute(SQL_CHANGES, {"pid": pid})
                # Marcador solo después de cargar: un fallo se puede reanudar.
                conn.execute(
                    text(
                        "UPDATE raw_snapshots SET params=params || "
                        "jsonb_build_object('recovery_player_id',CAST(:pid AS text)) "
                        "WHERE id=(SELECT max(id) FROM raw_snapshots "
                        "WHERE source='laliga_api' AND endpoint=:endpoint)"
                    ),
                    {"pid": pid, "endpoint": path},
                )
            report["players_restored"] += 1
            report["value_rows"] += len(rows)
            if (index + 1) % 10 == 0 or index + 1 == len(ids):
                print(json.dumps({"progress": index + 1, **report}), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    print(json.dumps(run(limit=args.limit)))
