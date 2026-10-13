from lfm.api import endpoints as ep


def test_read_paths_follow_competition_prefix():
    assert ep.READ.players("1") == "/v1/competition/1/players"
    assert ep.READ.standing("1", "L", 3) == "/v1/competition/1/leagues/L/standing/3"
    assert ep.READ.activity("1", "L", 2) == "/v1/competition/1/leagues/L/activity/2"
    assert ep.READ.market("1", "L") == "/v1/competition/1/league/L/market"


def test_write_paths_are_never_used_by_jobs():
    """Guardia de la regla 1 de CLAUDE.md: ningún job importa WRITE."""
    import pathlib

    jobs_dir = pathlib.Path(__file__).resolve().parents[1] / "src" / "lfm" / "jobs"
    for f in jobs_dir.glob("*.py"):
        assert "WRITE." not in f.read_text(encoding="utf-8"), f"{f.name} usa endpoints de escritura"
