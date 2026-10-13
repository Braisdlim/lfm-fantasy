"""Backfill de FútbolFantasy: parseo del mercado y del detalle (fixtures HTML reales recortados),
asignación de años, casado de clubes y jugadores, y carga por lotes con una conexión falsa."""

import json
import pathlib
from datetime import date

import pytest

from lfm.sources import futbolfantasy as ff

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
TODAY = date(2026, 9, 8)

# Nombres reales de club de la API (tabla teams) y nombres cortos de FútbolFantasy
API_CLUBS = {
    "3": "Athletic Club",
    "2": "Atlético de Madrid",
    "13": "C.A. Osasuna",
    "6": "Celta",
    "21": "Deportivo Alavés",
    "7": "Elche CF",
    "4": "FC Barcelona",
    "9": "Getafe CF",
    "11": "Levante UD",
    "12": "Málaga CF",
    "49": "R. Racing Club",
    "26": "RC Deportivo",
    "8": "RCD Espanyol",
    "14": "Rayo Vallecano",
    "5": "Real Betis",
    "15": "Real Madrid",
    "16": "Real Sociedad",
    "17": "Sevilla FC",
    "18": "Valencia CF",
    "20": "Villarreal CF",
}


def market_html():
    return (FIXTURES / "futbolfantasy_mercado.html").read_text(encoding="utf-8")


def test_parse_market_rows_and_teams():
    rows = ff.parse_market(market_html())
    assert len(rows) == 6
    assert {r.position for r in rows} == set(ff.POSITION_IDS)
    for r in rows:
        assert r.ff_id and r.name.startswith("jugador ") and r.ff_team_id
        assert r.value > 0 and set(r.values) == set(ff.HORIZONS)
    coach = next(r for r in rows if r.position == "Entrenador")
    assert coach.ff_id.startswith("e") and coach.position_id == 5
    teams = ff.parse_market_teams(market_html())
    assert len(teams) == 20 and teams["28"] == "Alavés" and "0" not in teams


def test_match_clubs_resolves_all_twenty_including_the_deportivo_ambiguity():
    teams = ff.parse_market_teams(market_html())
    m = ff.match_clubs(teams, API_CLUBS)
    assert len(m) == 20
    assert m["28"] == "21"  # Alavés → Deportivo Alavés
    assert m["6"] == "26"  # Deportivo → RC Deportivo
    assert m["15"] == "15" and m["16"] == "16"  # Real Madrid / Real Sociedad
    assert m["42"] == "49"  # Racing → R. Racing Club


def test_parse_detail_gives_the_full_daily_series_oldest_first():
    html = (FIXTURES / "futbolfantasy_detalle.html").read_text(encoding="utf-8")
    series = ff.parse_detail(html, TODAY)
    assert len(series) == 70
    days = [d for d, _ in series]
    assert days[0] == date(2026, 7, 1) and days[-1] == TODAY
    assert all((b - a).days == 1 for a, b in zip(days, days[1:], strict=False))  # sin huecos
    assert series[-1][1] == 42_511_616 and all(v > 0 for _, v in series)


def test_assign_years_crosses_the_year_boundary_backwards():
    days = ff.assign_years(["02/01", "01/01", "31/12", "30/12"], today=date(2027, 1, 2))
    assert days == [date(2027, 1, 2), date(2027, 1, 1), date(2026, 12, 31), date(2026, 12, 30)]


def _api(pid, name, nick, pos, team):
    return ff.ApiPlayer(pid, name, nick, pos, team)


def test_match_players_by_full_name_nickname_and_fuzzy_within_club():
    rows = [
        ff.MarketRow("1", "antonio sivera", "Portero", "28", 1),
        ff.MarketRow("2", "kylian mbappé", "Delantero", "15", 1),
        ff.MarketRow("3", "iñigo sainz-maza", "Mediocampista", "42", 1),
        ff.MarketRow("4", "raphinha", "Delantero", "3", 1),
        ff.MarketRow("5", "desconocido total", "Defensa", "3", 1),
    ]
    api = [
        _api("100", "Antonio Sivera", "Sivera", 1, "21"),
        _api("101", "Kylian Mbappé", "Mbappé", 4, "15"),
        _api("102", "Sainz-Maza", "Sainz-Maza", 3, "49"),
        _api("103", "Raphael Dias Belloli", "Raphinha", 4, "4"),
        _api("104", "Otro", "Otro", 2, "4"),
    ]
    club_map = {"28": "21", "15": "15", "42": "49", "3": "4"}
    matches, unmatched = ff.match_players(rows, api, club_map)
    assert {k: v[0] for k, v in matches.items()} == {"1": "100", "2": "101", "3": "102", "4": "103"}
    assert all(c >= 0.9 for _, c in matches.values())
    assert [r.ff_id for r in unmatched] == ["5"]


def test_match_players_is_one_to_one_and_prefers_same_position():
    rows = [ff.MarketRow("a", "garcia", "Defensa", "1", 1), ff.MarketRow("b", "garcia", "Delantero", "1", 1)]
    api = [_api("d", "García", "García", 2, "T"), _api("f", "García", "García", 4, "T")]
    matches, unmatched = ff.match_players(rows, api, {"1": "T"})
    assert {k: v[0] for k, v in matches.items()} == {"a": "d", "b": "f"} and not unmatched


class FakeConn:
    def __init__(self):
        self.calls = []

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params))

        class R:
            rowcount = len(json.loads(params["rows"])) if params and "rows" in params else 0

            def all(self_inner):
                return []

            def scalars(self_inner):
                return []

        return R()


def test_backfill_dry_run_only_matches(monkeypatch):
    monkeypatch.setattr(ff, "fetch_market_html", market_html)
    api = [_api(str(i), f"Jugador {i:03d}", f"Jugador {i:03d}", None, None) for i in range(1, 7)]
    monkeypatch.setattr(ff, "load_api_players", lambda conn: (api, API_CLUBS))
    conn = FakeConn()
    s = ff.backfill(conn, dry_run=True, today=TODAY)
    assert s["ff_players"] == 6 and s["clubs_matched"] == "20/20" and conn.calls == []


def test_backfill_writes_aliases_raw_and_values_without_overwriting(monkeypatch):
    monkeypatch.setattr(ff, "fetch_market_html", market_html)
    rows = ff.parse_market(market_html())
    teams = ff.parse_market_teams(market_html())
    club_map = ff.match_clubs(teams, API_CLUBS)
    api = [
        _api(f"p{r.ff_id}", r.name.title(), r.name.title(), r.position_id, club_map[r.ff_team_id])
        for r in rows
    ]
    monkeypatch.setattr(ff, "load_api_players", lambda conn: (api, API_CLUBS))
    detail = (FIXTURES / "futbolfantasy_detalle.html").read_text(encoding="utf-8")

    async def fake_fetch(ids, concurrency=3, retries=4, rate=None):
        return {i: detail for i in ids}

    monkeypatch.setattr(ff, "fetch_details", fake_fetch)
    conn = FakeConn()
    s = ff.backfill(conn, today=TODAY)
    writes = [(sql, params) for sql, params in conn.calls if sql.startswith(("INSERT", "UPDATE"))]
    assert [sql.split(" ")[2] for sql, _ in writes] == [
        "player_aliases",
        "raw_snapshots",
        "player_value_daily",
    ]
    assert "ON CONFLICT (player_id, day) DO NOTHING" in writes[2][0]
    assert s["players_matched"] == 6 and s["series_fetched"] == 6 and s["value_points"] == 6 * 70
    assert s["first_day"] == "2026-07-01"
    values = json.loads(writes[2][1]["rows"])
    first = next(v for v in values if v["player_id"] == "p" + rows[0].ff_id and v["day"] == "2026-07-01")
    assert first["market_value"] == 15_000_000


@pytest.mark.parametrize("s", ["Kylian Mbappé", "  IÑIGO  Sainz-Maza ", "C.A. Osasuna"])
def test_norm_strips_accents_case_and_punctuation(s):
    assert ff.norm(s) in ("kylian mbappe", "inigo sainz maza", "c a osasuna")


def test_match_players_handles_initials_prefixes_and_coaches():
    rows = [
        ff.MarketRow("1", "kiko femenia", "Defensa", "8", 1),
        ff.MarketRow("2", "antonio martinez bastida", "Mediocampista", "8", 1),
        ff.MarketRow("3", "vinicius junior", "Delantero", "8", 1),
        ff.MarketRow("4", "jon gorrotxategi", "Mediocampista", "8", 1),
        ff.MarketRow("5", "quique sanchez", "Entrenador", "8", 1),
        ff.MarketRow("6", "alberto collado", "Mediocampista", "8", 1),
        ff.MarketRow("7", "job ochieng", "Mediocampista", "8", 1),
    ]
    api = [
        _api("a", "Kiko F.", "Kiko F.", 2, "T"),
        _api("b", "A. Martinez", "A. Martinez", 3, "T"),
        _api("c", "Vini Jr.", "Vini Jr.", 4, "T"),
        _api("d", "Gorrotxa", "Gorrotxa", 3, "T"),
        _api("e", "Sánchez Flores", "Sánchez Flores", 5, "T"),
        _api("f", "Alberto F.", "Alberto F.", 3, "T"),
        _api("g", "Ochieng", "Ochieng", 4, "T"),  # posición distinta en la API: penaliza, no descarta
    ]
    matches, unmatched = ff.match_players(rows, api, {"8": "T"})
    assert {k: v[0] for k, v in matches.items()} == {
        "1": "a",
        "2": "b",
        "3": "c",
        "4": "d",
        "5": "e",
        "7": "g",
    }
    assert [r.ff_id for r in unmatched] == ["6"]  # 'Alberto F.' no es Alberto Collado


def test_fetch_details_waits_and_retries_on_429(monkeypatch):
    import asyncio

    import httpx
    import respx

    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(ff.asyncio, "sleep", fake_sleep)
    with respx.mock:
        respx.get(ff.DETAIL_URL.format(ff_id="1")).mock(
            side_effect=[
                httpx.Response(429, headers={"retry-after": "3"}),
                httpx.Response(200, text='player_chartjs.push({date: "08/09", value: 5});'),
            ]
        )
        respx.get(ff.DETAIL_URL.format(ff_id="2")).mock(return_value=httpx.Response(404))
        out = asyncio.run(ff.fetch_details(["1", "2"], rate=0))
    assert "value: 5" in out["1"] and out["2"] == ""
    assert 3.0 in sleeps  # esperó lo que pidió el servidor antes de reintentar
