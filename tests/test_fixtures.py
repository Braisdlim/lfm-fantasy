"""Anonimizador y muestreo de fixtures (lfm.fixtures)."""

import json

from lfm.fixtures import Anonymizer, sample_players, write_fixture

PLAYER = {
    "id": 42,
    "name": "Nombre Real",
    "nickname": "Apodo",
    "slug": "nombre-real",
    "positionId": 3,
    "marketValue": 1_000_000,
    "points": 5,
    "playerStatus": "ok",
    "team": {
        "id": 15,
        "name": "Real Madrid",
        "badge": "https://assets-fantasy.llt-services.com/t/15/badge.png",
    },
    "images": {"transparent": {"256x256": "https://assets-fantasy.llt-services.com/players/42/256x256.png"}},
}


def test_anonymize_replaces_person_names_but_keeps_structure_ids_and_values():
    out = Anonymizer().anonymize({"data": [PLAYER], "total": 1})
    assert out["total"] == 1
    p = out["data"][0]
    assert (p["id"], p["marketValue"], p["points"], p["positionId"], p["playerStatus"]) == (
        42,
        1_000_000,
        5,
        3,
        "ok",
    )
    assert (p["name"], p["nickname"], p["slug"]) == ("Jugador 001", "J001", "jugador-001")
    assert p["team"]["id"] == 15
    assert p["team"]["name"] == "Real Madrid"  # los clubes no son personas
    assert p["images"]["transparent"]["256x256"].endswith("/256x256.png")
    dumped = json.dumps(out)
    assert "Nombre Real" not in dumped and "Apodo" not in dumped and "llt-services" not in dumped


def test_anonymize_is_deterministic_per_person_id():
    out = Anonymizer().anonymize([PLAYER, {**PLAYER, "id": 7, "name": "Otro"}, PLAYER])
    assert [p["name"] for p in out] == ["Jugador 001", "Jugador 002", "Jugador 001"]


def test_anonymize_hides_image_files_named_after_the_player():
    out = Anonymizer().anonymize({**PLAYER, "images": {"big": "https://x.test/players/nombre-real.png?v=3"}})
    assert out["images"]["big"].endswith("/image.png")
    assert "nombre-real" not in out["images"]["big"]


def _players(n: int) -> list[dict]:
    return [
        {
            **PLAYER,
            "id": i,
            "positionId": 1 + i % 4,
            "playerStatus": ["ok", "injured"][(i // 4) % 2],
            "marketValue": i,
        }
        for i in range(n)
    ]


def test_sample_players_covers_every_position_status_combo_and_respects_n():
    out = sample_players({"data": _players(600), "total": 600}, n=20)
    assert out["total"] == 600
    sample = out["data"]
    assert len(sample) == 20
    combos = {(p["positionId"], p["playerStatus"]) for p in sample}
    assert combos == {(pos, st) for pos in (1, 2, 3, 4) for st in ("ok", "injured")}
    ids = [p["id"] for p in sample]
    assert ids == sorted(ids)  # conserva el orden original


def test_sample_players_keeps_bare_list_shape_and_never_drops_a_combo():
    out = sample_players(_players(50), n=5)
    assert isinstance(out, list)
    assert len(out) == 8  # 8 combinaciones > n


def test_write_fixture_embeds_meta_in_dicts_and_uses_sidecar_for_lists(tmp_path):
    p = write_fixture(tmp_path / "a.json", {"data": []}, {"k": 1})
    assert json.loads(p.read_text(encoding="utf-8")) == {"_meta": {"k": 1}, "data": []}
    p = write_fixture(tmp_path / "b.json", [], {"k": 2})
    assert json.loads(p.read_text(encoding="utf-8")) == []
    assert json.loads((tmp_path / "b.meta.json").read_text(encoding="utf-8")) == {"k": 2}
