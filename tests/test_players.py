"""Contrato del adaptador de /players contra la captura real anonimizada (tests/fixtures/players.json).
Falla alto si la API deja de traer un campo que usamos (CLAUDE.md)."""

import json
import pathlib

from lfm.api.endpoints import POSITIONS
from lfm.collectors.players import extract_list, normalize_player, summarize

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
STATUSES = {"ok", "injured", "doubtful", "suspended", "out_of_league"}


def _payload():
    return json.loads((FIXTURES / "players.json").read_text(encoding="utf-8"))


def test_fixture_is_a_real_anonymized_capture_with_the_flat_shape():
    assert isinstance(_payload(), list)  # la API devuelve la lista plana, sin envoltorio
    meta = json.loads((FIXTURES / "players.meta.json").read_text(encoding="utf-8"))
    assert meta["endpoint"] == "/v1/competition/1/players" and meta["anonymized"] is True


def test_every_player_has_the_fields_we_store():
    items = extract_list(_payload())
    assert len(items) >= 20
    for r in (normalize_player(p) for p in items):
        assert r["player_id"] and r["player_id"] != "None"
        assert r["name"]  # viene de nickname: la API no trae `name`
        assert isinstance(r["market_value"], int) and r["market_value"] > 0
        assert r["position_id"] in POSITIONS
        assert r["team_id"]
        assert r["status"] in STATUSES
        assert isinstance(r["points_total"], int)
        assert isinstance(r["average_points"], float)
        assert r["image_url"].startswith("https://")
    assert all(v == 0 for v in summarize(items)["missing"].values())


def test_numeric_strings_are_cast_and_week_points_are_indexed_by_week():
    p = next(p for p in extract_list(_payload()) if p["weekPoints"])
    r = normalize_player(p)
    assert r["market_value"] == int(p["marketValue"])
    assert r["position_id"] == int(p["positionId"])
    assert r["week_points"] == {int(w["weekNumber"]): w["points"] for w in p["weekPoints"]}
    assert r["last_season_points"] == int(p["lastSeasonPoints"])


def test_fixture_covers_every_position_and_the_main_statuses():
    rows = [normalize_player(p) for p in extract_list(_payload())]
    assert {r["position_id"] for r in rows} == set(POSITIONS)
    assert {r["status"] for r in rows} >= {"ok", "injured", "out_of_league"}


def test_normalize_tolerates_missing_fields():
    r = normalize_player({"id": 7, "nickname": "X"})
    assert r["market_value"] is None and r["team_id"] is None and r["week_points"] == {}
    assert normalize_player({"nickname": "X"})["player_id"] is None
    assert normalize_player({"id": 1, "marketValue": "abc"})["market_value"] is None
