"""El dry-run completo contra una API simulada (respx): auth falsa, los cinco endpoints servidos
desde los fixtures, volcado crudo a un directorio temporal y fixtures anonimizados regenerados.
Solo la autenticación real queda fuera; lo demás es el mismo camino que
`python -m lfm.jobs.daily --dry-run --save-fixture`."""

import json
import pathlib
import time

import httpx
import respx

from lfm.api import endpoints as ep
from lfm.api.auth import Tokens
from lfm.jobs import daily

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@respx.mock
def test_dry_run_writes_raw_and_anonymized_fixtures(tmp_path, monkeypatch):
    players_payload = load("players")
    standing = load("standing")
    first_team_id = standing[0]["team"]["id"]
    routes = {
        "players": respx.get(f"{ep.BASE_URL}{ep.READ.players('1')}").mock(
            return_value=httpx.Response(200, json=players_payload)
        ),
        "standing": respx.get(f"{ep.BASE_URL}{ep.READ.standing('1', 'L')}").mock(
            return_value=httpx.Response(200, json=standing)
        ),
        "team": respx.get(f"{ep.BASE_URL}{ep.READ.team('1', 'L', first_team_id)}").mock(
            return_value=httpx.Response(200, json=load("team"))
        ),
        "market": respx.get(f"{ep.BASE_URL}{ep.READ.market('1', 'L')}").mock(
            return_value=httpx.Response(200, json=load("market"))
        ),
        "activity": respx.get(f"{ep.BASE_URL}{ep.READ.activity('1', 'L', 0)}").mock(
            return_value=httpx.Response(200, json=load("activity"))
        ),
    }

    fake = Tokens(access_token="tok", id_token="", refresh_token="r", expires_at=time.time() + 3600)
    monkeypatch.setattr("lfm.api.client.get_tokens", lambda **kw: fake)
    monkeypatch.setattr(daily.settings, "league_id", "L")
    monkeypatch.setattr(daily.settings, "competition_id", "1")
    monkeypatch.setattr(daily.settings, "request_pause_seconds", 0.0)
    monkeypatch.setattr(daily, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(daily, "FIXTURES_DIR", tmp_path / "fixtures")

    summary = daily.dry_run(save_fixture=True)

    assert all(r.called for r in routes.values())
    req = routes["players"].calls.last.request
    assert req.headers["authorization"] == "Bearer tok"
    assert req.url.params["x-lang"] == "es" and req.headers["x-lang"] == "es"

    assert summary["envelope"] == "list" and summary["players"]["count"] == len(players_payload)
    assert all(v == 0 for v in summary["players"]["missing"].values())
    assert len(summary["standing"]) == len(standing) and summary["team"]["players"] > 0
    assert summary["market"]["players"] == len(load("market")) and summary["activity"]["items"] == len(
        load("activity")
    )

    raw = json.loads(
        (tmp_path / "raw" / f"{summary['day']}_v1_competition_1_players.json").read_text("utf-8")
    )
    assert raw == players_payload  # el crudo se guarda intacto (regla 2)
    assert (
        tmp_path / "raw" / f"{summary['day']}_v1_competition_1_leagues_L_teams_{first_team_id}.json"
    ).exists()

    assert set(summary["fixtures"]) == {"players", "standing", "team", "market", "activity"}
    # lista plana: los metadatos van en el sidecar .meta.json; dict: en _meta
    fixture = json.loads((tmp_path / "fixtures" / "players.json").read_text(encoding="utf-8"))
    meta = json.loads((tmp_path / "fixtures" / "players.meta.json").read_text(encoding="utf-8"))
    assert meta["anonymized"] is True and meta["total_items"] == len(players_payload)
    assert [p["nickname"] for p in fixture[:2]] == ["J001", "J002"]
    assert [p["id"] for p in fixture] == [p["id"] for p in players_payload]  # los ids no se tocan
    team = json.loads((tmp_path / "fixtures" / "team.json").read_text(encoding="utf-8"))
    assert team["_meta"]["endpoint"].endswith(f"/teams/{first_team_id}") and team["players"]
