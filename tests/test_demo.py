"""The public demo must never seed a user's existing database."""

import json

import pytest

from lfm.demo import DATA, demo_url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user:pass@localhost/production",
        "postgresql://owner:pass@localhost/lfm_demo",
        "sqlite:///lfm_demo",
    ],
)
def test_demo_rejects_production_database_names_and_roles(url):
    with pytest.raises(ValueError):
        demo_url(url)


def test_demo_accepts_its_explicit_disposable_database():
    url = demo_url("postgresql://lfm_demo:lfm_demo@database:5432/lfm_demo")
    assert url.drivername == "postgresql+psycopg"
    assert url.database == "lfm_demo"


def test_real_snapshot_contains_only_allowlisted_sports_data():
    snapshot = json.loads(DATA.read_text(encoding="utf-8"))
    assert snapshot["metadata"]["private_tables_exported"] == []
    assert set(snapshot["tables"]) == {
        "players",
        "teams",
        "player_value_daily",
        "player_week_stats",
        "player_availability",
        "matches",
        "weeks",
        "player_set_pieces",
        "team_set_pieces",
        "player_season_stats",
    }
    players = snapshot["tables"]["players"]
    assert len(players) == 64
    assert all(not p["player_id"].startswith("demo-") for p in players)
    assert any("Mbapp" in p["name"] for p in players)
    days = {v["day"] for v in snapshot["tables"]["player_value_daily"]}
    assert max(days) == snapshot["metadata"]["prices_as_of"]
