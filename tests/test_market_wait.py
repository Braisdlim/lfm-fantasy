"""El diario espera a que LaLiga publique el mercado nuevo en vez de guardar uno a medias.

Y mientras no llega, la recomendación vigente no se toca (2026-09-20)."""

from datetime import UTC, date, datetime, timedelta

from lfm.analysis import recommend
from lfm.collectors import league
from lfm.jobs import daily


def _recoger_con(states):
    """Un `recoger` falso que devuelve los estados en orden, como pasadas sucesivas del mercado."""
    calls = []

    def recoger(nombre, fn):
        calls.append(nombre)
        state = states[min(len(calls), len(states)) - 1]
        return None if state is None else {"state": state, "why": "prueba"}

    return recoger, calls


def test_waits_until_laliga_publishes_the_new_market(monkeypatch):
    sleeps = []
    monkeypatch.setattr(daily, "_sleep", sleeps.append)
    recoger, calls = _recoger_con([league.MARKET_ROTATING, league.MARKET_ROTATING, league.MARKET_OK])
    out = daily.wait_for_market(recoger, lambda c: None, max_wait_min=60)
    assert out["state"] == league.MARKET_OK and out["attempts"] == 3
    assert len(calls) == 3 and sleeps == [daily.MARKET_POLL_SECONDS] * 2


def test_a_healthy_market_costs_a_single_request(monkeypatch):
    monkeypatch.setattr(daily, "_sleep", lambda s: (_ for _ in ()).throw(AssertionError("no debía esperar")))
    recoger, calls = _recoger_con([league.MARKET_OK])
    assert daily.wait_for_market(recoger, lambda c: None)["attempts"] == 1 and calls == ["market"]


def test_gives_up_when_the_wait_runs_out(monkeypatch):
    monkeypatch.setattr(daily, "_sleep", lambda s: None)
    recoger, calls = _recoger_con([league.MARKET_ROTATING])
    out = daily.wait_for_market(recoger, lambda c: None, max_wait_min=0)
    assert out["state"] == league.MARKET_ROTATING and len(calls) == 1


def test_a_broken_market_request_is_retried_too(monkeypatch):
    monkeypatch.setattr(daily, "_sleep", lambda s: None)
    recoger, calls = _recoger_con([None, league.MARKET_OK])  # None = el colector reventó
    assert daily.wait_for_market(recoger, lambda c: None, max_wait_min=60)["state"] == league.MARKET_OK


class _Conn:
    def __init__(self, cycle_end):
        self.cycle_end = cycle_end
        self.sql = []

    def execute(self, stmt, params=None):
        self.sql.append(str(stmt))
        conn = self

        class R:
            def scalar(self_inner):
                return conn.cycle_end

        return R()


def test_recompute_keeps_the_last_good_recommendations_while_the_market_rotates():
    conn = _Conn(datetime.now(UTC) - timedelta(minutes=30))
    out = recommend.recompute(conn, league_id="L", day=date(2026, 9, 20), team_id="T")
    assert "skipped" in out
    assert not any("DELETE FROM recommendations" in s for s in conn.sql)
