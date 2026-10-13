"""Real public sports snapshot in an isolated, fictional fantasy league.

No external requests, private league records or production credentials are needed.
Stored sporting dates are preserved; the snapshot does not pretend to update itself.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import Date, DateTime, MetaData, create_engine, inspect, text
from sqlalchemy.engine import make_url

from lfm.analysis import bargains, eleven, fixtures, journal, recommend, rivals
from lfm.config import settings
from lfm.db.migrate import SCHEMA, statements

LEAGUE = "demo-league"
MY_TEAM = "demo-team-1"
DATA = Path(__file__).with_name("demo_data.json")


def demo_url(value: str):
    """An explicitly named, empty demo database is required."""
    url = make_url(value)
    if url.database != "lfm_demo" or url.username != "lfm_demo":
        raise ValueError("Demo requires database and username 'lfm_demo'; refuses production URLs.")
    if url.get_backend_name() not in ("postgres", "postgresql"):
        raise ValueError("Demo requires PostgreSQL.")
    return url.set(drivername="postgresql+psycopg")


def seed(value: str) -> dict:
    engine = create_engine(demo_url(value))
    snapshot = json.loads(DATA.read_text(encoding="utf-8"))
    public = snapshot["tables"]
    now = datetime.now(UTC).replace(microsecond=0)
    day = date.fromisoformat(snapshot["metadata"]["prices_as_of"])
    with engine.begin() as conn:
        tables = inspect(conn).get_table_names()
        if "lfm_demo_metadata" in tables:
            return {
                "status": "already_seeded",
                "note": "Use a fresh demo volume to regenerate the example league.",
            }
        if tables:
            raise ValueError("Refusing to seed a nonempty database without the demo marker.")
        for stmt in statements(SCHEMA.read_text(encoding="utf-8")):
            conn.execute(text(stmt))
        metadata = MetaData()
        metadata.reflect(conn)

        def insert(table: str, rows: list[dict]) -> None:
            converted = []
            for row in rows:
                clean = dict(row)
                for col in metadata.tables[table].columns:
                    if isinstance(clean.get(col.name), str):
                        if isinstance(col.type, DateTime):
                            clean[col.name] = datetime.fromisoformat(clean[col.name])
                        elif isinstance(col.type, Date):
                            clean[col.name] = date.fromisoformat(clean[col.name])
                converted.append(clean)
            if converted:
                conn.execute(metadata.tables[table].insert(), converted)

        # Explicit allowlist; no private league, raw capture or authentication tables are imported.
        for table in (
            "teams",
            "players",
            "player_value_daily",
            "player_week_stats",
            "player_availability",
            "matches",
            "weeks",
            "player_set_pieces",
            "team_set_pieces",
            "player_season_stats",
        ):
            insert(table, public[table])
        latest = {v["player_id"]: v for v in public["player_value_daily"] if v["day"] == str(day)}
        players = public["players"]
        pool = list(players)
        rosters = []
        for _ in range(3):
            roster = []
            for position, count in ((1, 2), (2, 5), (3, 5), (4, 4)):
                picked = [p for p in pool if p["position_id"] == position][:count]
                roster.extend(picked)
                pool = [p for p in pool if p not in picked]
            rosters.append(roster)
        insert(
            "league_teams",
            [
                {
                    "league_id": LEAGUE,
                    "team_id": f"demo-team-{i + 1}",
                    "manager_id": f"demo-manager-{i + 1}",
                    "manager_name": ["Mi equipo", "Laura Demo", "Pablo Demo"][i],
                    "team_name": ["Equipo Horizonte", "Once del Sur", "Club del Puerto"][i],
                    "is_me": i == 0,
                    "team_money": 48_000_000 if i == 0 else None,
                }
                for i in range(3)
            ],
        )
        insert(
            "league_standing_daily",
            [
                {
                    "league_id": LEAGUE,
                    "team_id": f"demo-team-{i + 1}",
                    "day": day,
                    "position": i + 1,
                    "previous_position": [2, 1, 3][i],
                    "points": 325 - i * 18,
                    "team_value": sum(latest[p["player_id"]]["market_value"] for p in rosters[i]),
                    "team_money": 48_000_000 if i == 0 else None,
                }
                for i in range(3)
            ],
        )
        insert(
            "league_standing_week",
            [
                {"league_id": LEAGUE, "team_id": f"demo-team-{i + 1}", "week": w, "points": 38 + (i + w) % 12}
                for i in range(3)
                for w in range(1, 9)
            ],
        )
        squads, activities = [], []
        value_by_day = {(v["player_id"], v["day"]): v["market_value"] for v in public["player_value_daily"]}
        for manager, roster in enumerate(rosters):
            for index, p in enumerate(roster):
                pid = p["player_id"]
                price = latest[pid]["market_value"]
                squads.append(
                    {
                        "league_id": LEAGUE,
                        "team_id": f"demo-team-{manager + 1}",
                        "player_id": pid,
                        "day": day,
                        "buyout_clause": round(price * 1.25),
                        "buy_price": round(price * 0.85),
                        "market_value": price,
                        "is_shielded": False,
                        "clause_locked_until": now + timedelta(hours=(index % 5) * 12 - 6),
                        "fetched_at": now,
                    }
                )
                at = datetime.combine(day - timedelta(days=10 + index), datetime.min.time(), UTC).replace(
                    hour=12
                )
                historical = value_by_day.get((pid, str(at.date())))
                if historical is not None:
                    activities.append(
                        {
                            "league_id": LEAGUE,
                            "activity_id": f"demo-activity-{manager}-{index}",
                            "activity_type": 31,
                            "manager_id": f"demo-manager-{manager + 1}",
                            "team_id": f"demo-team-{manager + 1}",
                            "player_id": pid,
                            "amount": round(historical * (1.005 + (index % 6) * 0.003)),
                            "happened_at": at,
                            "raw": {"example_league": True},
                        }
                    )
        insert("league_squad_daily", squads)
        insert("league_activity", activities)
        insert(
            "manager_cash_estimate",
            [
                {
                    "league_id": LEAGUE,
                    "team_id": f"demo-team-{i + 1}",
                    "day": day,
                    "cash_estimate": 48_000_000 - i * 10_000_000,
                    "uncertainty": 2_000_000,
                    "method": "example_league",
                }
                for i in range(3)
            ],
        )
        cycle = now + timedelta(hours=6)
        insert(
            "market_offer",
            [
                {
                    "league_id": LEAGUE,
                    "cycle_end": cycle,
                    "player_id": p["player_id"],
                    "market_id": f"demo-offer-{i}",
                    "kind": "marketPlayerLeague",
                    "sale_price": round(latest[p["player_id"]]["market_value"] * 0.98),
                    "owner_team_id": None,
                    "expires_at": cycle,
                    "num_bids": i % 3,
                    "num_offers": 0,
                    "raw": {"example_league": True},
                }
                for i, p in enumerate(pool)
            ],
        )
        formation = {
            name: [
                {"playerMaster": {"id": p["player_id"]}} for p in rosters[0] if p["position_id"] == position
            ][:count]
            for name, position, count in (
                ("goalkeeper", 1, 1),
                ("defender", 2, 4),
                ("midfield", 3, 4),
                ("striker", 4, 2),
            )
        }
        insert(
            "raw_snapshots",
            [
                {
                    "source": "laliga_api",
                    "endpoint": f"/demo/teams/{MY_TEAM}/lineup",
                    "payload": {"example_league": True, "formation": formation},
                }
            ],
        )
        if pool:
            pid = pool[0]["player_id"]
            insert(
                "watchlist",
                [
                    {
                        "player_id": pid,
                        "max_price": round(latest[pid]["market_value"] * 1.03),
                        "min_start_prob": 0.7,
                        "note": "Seguimiento de ejemplo; no es una puja real",
                        "state": "cumple",
                        "detail": {},
                        "value_at_add": latest[pid]["market_value"],
                        "checked_at": now,
                    }
                ],
            )
        fixtures.save_forecast(conn)
        bargains.save(conn, day=day)
        once = eleven.refresh(conn, team_id=MY_TEAM, day=day)
        recs = recommend.recompute(conn, league_id=LEAGUE, day=day, team_id=MY_TEAM)
        conn.execute(
            text(
                "UPDATE recommendations SET reasons = (SELECT jsonb_agg("
                "r || jsonb_build_object('source', CASE WHEN r->>'code' IN ('PUJA','REVENTA') "
                "THEN 'liga de ejemplo · ' ELSE 'muestra deportiva · ' END || "
                "COALESCE(r->>'source','regla del modelo'))) "
                "FROM jsonb_array_elements(reasons) r)"
            )
        )
        rivals.recompute(conn, league_id=LEAGUE, day=day)
        journal.recompute(conn, league_id=LEAGUE)
        insert(
            "job_runs",
            [
                {
                    "job": "demo",
                    "status": "ok",
                    "started_at": now,
                    "finished_at": now,
                    "summary": {
                        "real_sports_snapshot": True,
                        "example_league": True,
                        "market": {"state": "ok"},
                    },
                }
            ],
        )
        conn.execute(
            text("CREATE TABLE lfm_demo_metadata (version int NOT NULL, seeded_at timestamptz NOT NULL)")
        )
        conn.execute(text("INSERT INTO lfm_demo_metadata VALUES (2, now())"))
    engine.dispose()
    return {
        "status": "seeded",
        "players": len(players),
        "sports_as_of": str(day),
        "example_league": True,
        "eleven": once,
        "recommendations": recs,
    }


if __name__ == "__main__":
    print(json.dumps(seed(settings.database_url), ensure_ascii=False, default=str))
