"""Contrato de los adaptadores de mi liga contra las capturas reales anonimizadas
(tests/fixtures/standing.json, team.json, activity.json, market.json) y escritura por lotes."""

import json
import pathlib
from datetime import UTC, date, datetime

from lfm.api import endpoints as ep
from lfm.collectors import league

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
DAY = date(2026, 9, 8)
BEFORE_CLOSE = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)  # el ciclo del fixture cierra a las 17:21 UTC
AFTER_CLOSE = datetime(2026, 9, 8, 17, 30, tzinfo=UTC)


def load(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


# --- normalizadores ------------------------------------------------------------------------------


def test_standing_fixture_contract():
    rows = league.normalize_standing(load("standing"))
    assert len(rows) >= 2
    for r in rows:
        assert r["team_id"] and r["manager_id"] and r["manager_name"]
        assert isinstance(r["position"], int) and isinstance(r["points"], int)
        assert isinstance(r["team_value"], int) and r["team_value"] > 0
    assert [r["position"] for r in rows] == sorted(r["position"] for r in rows)


def test_squad_fixture_contract():
    sq = league.normalize_squad(load("team"))
    assert sq["team"]["team_id"] and sq["team"]["manager_id"]
    assert isinstance(sq["team"]["team_value"], int)
    assert sq["players"]
    for p in sq["players"]:
        assert p["player_id"] and p["name"] and p["club_id"]
        assert isinstance(p["buyout_clause"], int) and p["buyout_clause"] > 0
        assert p["clause_locked_until"] and isinstance(p["is_shielded"], bool)
        assert isinstance(p["market_value"], int) and p["position_id"] in ep.POSITIONS
    assert sq["clubs"] and all(c["name"] and c["slug"] for c in sq["clubs"])  # nombres reales de club
    ws = sq["week_stats"]
    assert ws and all(isinstance(w["week"], int) and isinstance(w["total_points"], int) for w in ws)
    assert "mins_played" in ws[0]["stats"] and len(ws[0]["stats"]["mins_played"]) == 2  # [valor, puntos]


def test_activity_fixture_contract():
    rows = [league.normalize_activity(a) for a in load("activity")]
    for r in rows:
        assert r["activity_id"] and r["activity_type"] in ep.ACTIVITY_TYPES
        assert r["manager_id"] and r["happened_at"] and r["raw"]
    types = {r["activity_type"] for r in rows}
    assert {1, 6, 31, 33} <= types  # compra a manager, ganancia jornada, fichaje, venta
    buy = next(r for r in rows if r["activity_type"] == 1)
    assert buy["manager2_id"] and buy["amount"] > 0 and buy["player_id"]  # user2Id = vendedor
    income = next(r for r in rows if r["activity_type"] == 6)
    assert income["week"] and income["amount"] > 0 and income["player_id"] is None


def test_market_fixture_contract():
    rows = [league.normalize_market(m) for m in load("market")]
    assert {r["kind"] for r in rows} == {"marketPlayerLeague", "marketPlayerTeam"}
    for r in rows:
        assert r["market_id"] and r["player_id"] and r["expires_at"]
        assert isinstance(r["sale_price"], int) and r["sale_price"] > 0
    system = next(r for r in rows if r["kind"] == "marketPlayerLeague")
    assert system["owner_team_id"] is None
    manager = next(r for r in rows if r["kind"] == "marketPlayerTeam")
    assert manager["owner_team_id"] and isinstance(manager["buyout_clause"], int)


# --- colectores (conexión falsa) -----------------------------------------------------------------


class Result:
    def __init__(self, rowcount):
        self.rowcount = rowcount


class FakeConn:
    def __init__(self, rowcount=None):
        self.calls: list[tuple[str, dict]] = []
        self.rowcount = rowcount  # None → tantas filas como se envían

    def execute(self, stmt, params):
        self.calls.append((str(stmt), params))
        n = len(json.loads(params["rows"])) if "rows" in params else 1
        return Result(n if self.rowcount is None else self.rowcount)

    def tables(self) -> list[str]:
        return [sql.split(" ")[2] for sql, _ in self.calls]  # "INSERT INTO x" / "UPDATE x SET"


class FakeClient:
    def __init__(self):
        self.activity_calls = 0

    def standing(self, league_id):
        return load("standing")

    def team(self, league_id, team_id):
        return load("team")

    def market(self, league_id):
        return load("market")

    def activity(self, league_id, index):
        self.activity_calls += 1
        return load("activity") if index == 0 else []


def test_collect_standing_marks_my_team_and_writes_two_tables():
    conn = FakeConn()
    rows = league.normalize_standing(load("standing"))
    me = rows[1]["manager_id"]
    summary = league.collect_standing(FakeClient(), conn, league_id="L", day=DAY, my_manager_id=me)
    assert conn.tables() == ["league_teams", "league_standing_daily"]
    assert conn.calls[0][1]["me"] == me and conn.calls[1][1]["day"] == "2026-09-08"
    assert summary["team_ids"] == [r["team_id"] for r in rows]
    assert summary["my_team_id"] == rows[1]["team_id"]


def test_collect_squads_writes_clubs_players_clauses_and_week_stats_per_team():
    conn = FakeConn()
    summary = league.collect_squads(FakeClient(), conn, league_id="L", team_ids=["A", "B"], day=DAY)
    per_team = ["league_squad_daily", "teams", "players", "league_squad_daily", "player_week_stats"]
    assert conn.tables() == per_team * 2  # el fixture es de un rival: sin teamMoney → sin UPDATE
    assert summary["teams"] == 2 and summary["players"] > 0 and summary["week_stats"] > 0
    squad_params = conn.calls[3][1]
    assert squad_params["league_id"] == "L" and squad_params["day"] == "2026-09-08"
    assert squad_params["team_id"] == league.normalize_squad(load("team"))["team"]["team_id"]


def test_collect_squads_saves_current_money_even_without_todays_standing():
    class MyClient(FakeClient):
        def team(self, league_id, team_id):
            squad = load("team")
            squad["teamMoney"] = 31_905_130
            return squad

    conn = FakeConn()
    league.collect_squads(MyClient(), conn, league_id="L", team_ids=["A"], day=DAY)
    current = [(sql, params) for sql, params in conn.calls if "UPDATE league_teams SET team_money" in sql]
    history = [
        (sql, params) for sql, params in conn.calls if "UPDATE league_standing_daily SET team_money" in sql
    ]
    assert len(current) == len(history) == 1
    assert current[0][1]["money"] == 31_905_130


def test_collect_activity_paginates_until_an_empty_page_when_everything_is_new():
    client, conn = FakeClient(), FakeConn()
    summary = league.collect_activity(client, conn, league_id="L")
    assert client.activity_calls == 2 and summary["pages"] == 2
    assert summary["inserted"] == len(load("activity"))
    assert conn.tables() == ["league_activity"]


def test_collect_activity_stops_at_the_first_page_already_seen():
    client, conn = FakeClient(), FakeConn(rowcount=0)
    summary = league.collect_activity(client, conn, league_id="L")
    assert client.activity_calls == 1 and summary["inserted"] == 0


def test_collect_activity_full_mode_keeps_going_over_known_pages():
    client, conn = FakeClient(), FakeConn(rowcount=0)
    summary = league.collect_activity(client, conn, league_id="L", full=True)
    assert client.activity_calls == 2 and summary["pages"] == 2


def test_collect_market_writes_one_row_per_player_and_cycle():
    conn = FakeConn()
    summary = league.collect_market(FakeClient(), conn, league_id="L", day=DAY, now=BEFORE_CLOSE)
    assert summary["state"] == league.MARKET_OK
    assert conn.tables() == ["market_offer"]
    assert summary["players"] == len(load("market")) and set(summary["kinds"]) == {
        league.KIND_LEAGUE,
        league.KIND_TEAM,
    }
    # la clave es el ciclo, no el día natural: un jugador no puede salir dos veces
    assert "ON CONFLICT (league_id, cycle_end, player_id)" in conn.calls[0][0]
    assert conn.calls[0][1]["cycle_end"] == summary["cycle_end"]


def test_market_cycle_end_is_the_league_market_close():
    rows = [league.normalize_market(m) for m in load("market")]
    cycle = league.market_cycle_end(rows)
    league_rows = [r["expires_at"] for r in rows if r["kind"] == league.KIND_LEAGUE]
    # todos los que vende la liga cierran a la vez, y ese instante identifica el ciclo
    assert len(set(league_rows)) == 1 and cycle == league_rows[0]
    # los de manager duran más: no deben mandar sobre el ciclo
    assert all(r["expires_at"] >= cycle for r in rows if r["kind"] == league.KIND_TEAM)


def test_direct_offer_is_a_boolean_flag_not_an_amount():
    # la API devuelve directOffer: false / true; el importe no viene en este endpoint
    assert (
        league.normalize_market({"id": "1", "playerMaster": {"id": "9"}, "directOffer": False})["offer_money"]
        is None
    )
    assert (
        league.normalize_market({"id": "1", "playerMaster": {"id": "9"}, "directOffer": True})["offer_money"]
        is None
    )
    assert (
        league.normalize_market({"id": "1", "playerMaster": {"id": "9"}, "directOffer": {"money": 5}})[
            "offer_money"
        ]
        == 5
    )


def test_market_cycle_end_does_not_invent_a_cycle_from_manager_listings():
    # Mientras LaLiga rota solo quedan ventas de managers. Antes su plazo se tomaba como ciclo y
    # se convertía en «el mercado actual» con tres jugadores: mejor no saberlo que inventarlo.
    rows = [
        {"kind": league.KIND_TEAM, "expires_at": "2026-09-10T17:19:00+00:00"},
        {"kind": league.KIND_TEAM, "expires_at": "2026-09-09T17:19:00+00:00"},
    ]
    assert league.market_cycle_end(rows) is None
    assert league.market_cycle_end([]) is None


def test_assess_market_tells_a_live_market_from_one_being_rotated():
    rows = [league.normalize_market(m) for m in load("market")]
    assert league.assess_market(rows, now=BEFORE_CLOSE)["state"] == league.MARKET_OK
    # LaLiga todavía devuelve el ciclo que ya cerró: está rotando
    assert league.assess_market(rows, now=AFTER_CLOSE)["state"] == league.MARKET_ROTATING
    only_managers = [r for r in rows if r["kind"] == league.KIND_TEAM]
    assert league.assess_market(only_managers, now=BEFORE_CLOSE)["state"] == league.MARKET_ROTATING
    assert league.assess_market([], now=BEFORE_CLOSE)["state"] == league.MARKET_EMPTY


def test_collect_market_writes_nothing_while_laliga_is_rotating():
    conn = FakeConn()
    summary = league.collect_market(FakeClient(), conn, league_id="L", now=AFTER_CLOSE)
    assert summary["state"] == league.MARKET_ROTATING and summary["cycle_end"] is None
    assert conn.calls == []  # el último ciclo bueno sigue siendo el vigente


def test_collect_market_dedupes_a_player_listed_twice():
    # Un ON CONFLICT con la misma clave dos veces en un lote revienta (2026-09-15)
    class Twice(FakeClient):
        def market(self, league_id):
            m = load("market")
            return m + [m[0]]

    conn = FakeConn()
    league.collect_market(Twice(), conn, league_id="L", now=BEFORE_CLOSE)
    rows = json.loads(conn.calls[0][1]["rows"])
    assert len(rows) == len({r["player_id"] for r in rows})


def test_collect_squads_keeps_the_previous_snapshot_if_laliga_returns_an_empty_squad():
    class Empty(FakeClient):
        def team(self, league_id, team_id):
            t = load("team")
            t["players"] = []
            return t

    conn = FakeConn()
    summary = league.collect_squads(Empty(), conn, league_id="L", team_ids=["A"], day=DAY)
    assert conn.calls == [] and summary["empty_skipped"] == 1


def test_collect_squads_replaces_the_snapshot_so_sold_players_disappear():
    conn = FakeConn()
    league.collect_squads(FakeClient(), conn, league_id="L", team_ids=["A"], day=DAY)
    sqls = [sql for sql, _ in conn.calls]
    assert sqls[0].startswith("DELETE FROM league_squad_daily")  # borra antes de insertar
    assert conn.calls[0][1] == {"league_id": "L", "team_id": "90000006", "day": "2026-09-08"}


def test_a_player_with_two_entries_for_the_same_week_does_not_break_the_insert():
    """El fallo real del 2026-09-15: «ON CONFLICT DO UPDATE command cannot affect row a second
    time». Es determinista, asi que tumbo los cinco reintentos del job y la app paso el dia sin
    datos. La jornada 6 tuvo un partido adelantado el dia 3 y el resto el 15."""
    filas = [
        {"player_id": "1", "week": 6, "total_points": 4, "stats": None},
        {"player_id": "1", "week": 6, "total_points": 4, "stats": {"mins_played": [90, 2]}},
        {"player_id": "2", "week": 6, "total_points": 1, "stats": None},
    ]
    fuera = league._unique(filas, lambda r: (r["player_id"], r["week"]), richer=league._richness)
    assert len(fuera) == 2
    # y se queda la que trae las estadisticas, no la primera que llego
    assert fuera[0]["stats"] == {"mins_played": [90, 2]}


def test_unique_keeps_the_order_and_the_first_when_there_is_no_tiebreak():
    filas = [{"player_id": "a"}, {"player_id": "b"}, {"player_id": "a"}]
    assert [r["player_id"] for r in league._unique(filas, lambda r: r["player_id"])] == ["a", "b"]
