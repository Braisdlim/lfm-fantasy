"""El job ligero actualiza mercado, equipo y actividad sin repetir valores de mercado."""

import json
import pathlib

import pytest

from lfm.jobs import light

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class FakeConn:
    def __init__(self, team_id="90000007", has_values=True):
        self.calls: list[str] = []
        self.team_id = team_id
        self.has_values = has_values

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append(sql)
        conn = self

        class R:
            rowcount = 1

            def first(self_inner):
                return (1,)

            def scalar_one(self_inner):
                return 1

            def scalar(self_inner):
                if "FROM player_value_daily" in sql:
                    return conn.has_values
                return conn.team_id

        return R()


class FakeEngine:
    def __init__(self, conn):
        self.conn = conn

    def begin(self):
        conn = self.conn

        class Ctx:
            def __enter__(self_inner):
                return conn

            def __exit__(self_inner, *a):
                return False

        return Ctx()


class FakeClient:
    def __init__(self):
        self.asked: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def market(self, league_id):
        self.asked.append("market")
        return load("market")

    def team(self, league_id, team_id):
        self.asked.append(f"team:{team_id}")
        return load("team")

    def activity(self, league_id, index):
        self.asked.append(f"activity:{index}")
        return load("activity") if index == 0 else []

    def players(self):  # solo cuando todavía no están los valores del día
        self.asked.append("players")
        return load("players")


@pytest.fixture(autouse=True)
def no_live_lineup_fetch(monkeypatch):
    monkeypatch.setattr(light.lineups, "refresh", lambda *a, **k: {"cached": True})
    monkeypatch.setattr(light.eleven, "refresh", lambda *a, **k: {"formation": "5-3-2"})


def test_light_refreshes_lineups_before_recommendations(wired, monkeypatch):
    calls = []
    monkeypatch.setattr(light.lineups, "refresh", lambda *a, **k: calls.append("lineups") or {"matched": 510})
    monkeypatch.setattr(light.recommend, "recompute", lambda *a, **k: calls.append("recommend") or {})
    light.run()
    assert calls == ["lineups", "recommend"]


def test_lineup_failure_is_recorded_without_discarding_market(wired, monkeypatch):
    def fail(*a, **k):
        raise ValueError("fuente incompleta")

    monkeypatch.setattr(light.lineups, "refresh", fail)
    summary = light.run()
    assert summary["market"]["players"] > 0
    assert "lineups" in summary["collect_errors"]
    assert "fuente incompleta" in summary["collect_error_details"]["lineups"]


@pytest.fixture
def wired(monkeypatch):
    conn = FakeConn()
    client = FakeClient()
    monkeypatch.setattr(light.settings, "league_id", "L")
    monkeypatch.setattr(light, "engine", lambda: FakeEngine(conn))
    monkeypatch.setattr(light, "LaLigaClient", lambda **kw: client)
    monkeypatch.setattr(light, "save_raw", lambda *a, **k: None)
    # el recomendador tiene sus propios tests; aquí solo importa que el job no gaste peticiones
    monkeypatch.setattr(light.recommend, "recompute", lambda conn, **kw: {"saved": 0})
    monkeypatch.setattr(light.cash, "recompute", lambda conn, **kw: {"teams": 5})
    return conn, client


def test_light_job_refreshes_activity_and_cash(wired):
    conn, client = wired
    summary = light.run()
    assert client.asked == ["market", "team:90000007", "activity:0"]
    assert summary["market"]["players"] == len(load("market"))
    assert summary["squad"]["teams"] == 1
    assert summary["cash"]["teams"] == 5


def test_light_updates_eleven_after_new_squad_and_availability(wired, monkeypatch):
    calls = []
    monkeypatch.setattr(light.lineups, "refresh", lambda *a, **k: calls.append("availability") or {})
    monkeypatch.setattr(
        light.eleven, "refresh", lambda *a, **k: calls.append("eleven") or {"formation": "5-3-2"}
    )
    result = light.run()
    assert calls == ["availability", "eleven"]
    assert result["eleven"]["formation"] == "5-3-2"
    assert wired[1].asked == ["market", "team:90000007", "activity:0"]


def test_eleven_failure_does_not_discard_collection_or_recommendations(wired, monkeypatch):
    def fail(*a, **k):
        raise ValueError("once incompleto")

    monkeypatch.setattr(light.eleven, "refresh", fail)
    result = light.run()
    assert result["market"]["players"] > 0
    assert result["recommendations"] == {"saved": 0}
    assert result["eleven"] == {"error": True}


def test_light_job_records_itself_in_job_runs(wired):
    conn, _ = wired
    light.run()
    assert any("INSERT INTO job_runs (job) VALUES ('light')" in c for c in conn.calls)
    assert any("UPDATE job_runs SET finished_at" in c for c in conn.calls)


def test_light_job_replaces_the_squad_snapshot(wired):
    conn, _ = wired
    light.run()
    assert any(c.startswith("DELETE FROM league_squad_daily") for c in conn.calls)


def test_light_job_skips_the_squad_when_my_team_is_unknown(monkeypatch):
    conn = FakeConn(team_id=None)
    client = FakeClient()
    monkeypatch.setattr(light.settings, "league_id", "L")
    monkeypatch.setattr(light, "engine", lambda: FakeEngine(conn))
    monkeypatch.setattr(light, "LaLigaClient", lambda **kw: client)
    monkeypatch.setattr(light, "save_raw", lambda *a, **k: None)
    monkeypatch.setattr(light.recommend, "recompute", lambda conn, **kw: {"saved": 0})
    monkeypatch.setattr(light.cash, "recompute", lambda conn, **kw: {"teams": 5})
    summary = light.run()
    assert client.asked == ["market", "activity:0"]
    assert "skipped" in summary["squad"]


def test_light_job_does_nothing_without_a_league(monkeypatch):
    monkeypatch.setattr(light.settings, "league_id", "")
    assert light.run() == {"status": "skipped"}


# --- el guardián que hace gratis programar varios intentos ------------------------------------------


def test_the_guard_reports_the_last_good_run_inside_the_window():
    from types import SimpleNamespace

    from lfm.jobs import guard

    class Conn:
        def __init__(self, valor):
            self.valor = valor
            self.params = None

        def execute(self, stmt, params=None):
            self.params = params
            return SimpleNamespace(scalar=lambda: self.valor)

    c = Conn("2026-09-09T10:00:00Z")
    assert guard.recently_done(c, "light", minutes=45) == "2026-09-09T10:00:00Z"
    assert c.params == {"job": "light", "window": "45 minutes"}
    assert guard.recently_done(Conn(None), "light", minutes=45) is None


def test_a_second_attempt_within_the_window_does_no_work(monkeypatch):
    """Es lo que permite pedir tres disparos por hora sin gastar tres veces las peticiones."""
    from datetime import UTC, datetime

    from lfm.jobs import light as light_mod

    hace_diez = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)
    monkeypatch.setattr(light_mod.settings, "league_id", "L", raising=False)
    monkeypatch.setattr(light_mod.guard, "recently_done", lambda *a, **k: hace_diez)
    monkeypatch.setattr(light_mod, "engine", lambda: _NullEngine())
    monkeypatch.setattr(
        light_mod, "LaLigaClient", lambda **k: pytest.fail("no debe tocar la API si ya se recogió")
    )
    assert light_mod.run(skip_if_recent=True) == {"status": "skipped"}


class _NullEngine:
    def begin(self):
        from contextlib import nullcontext
        from types import SimpleNamespace

        return nullcontext(SimpleNamespace(execute=lambda *a, **k: None))


def test_light_job_fetches_todays_values_once_laliga_publishes_them(monkeypatch):
    # Caso Ryan (2026-09-20): sin esto la app enseñaba el cambio de ayer como «hoy» hasta las 19:25
    conn = FakeConn(has_values=False)
    client = FakeClient()
    monkeypatch.setattr(light.settings, "league_id", "L")
    monkeypatch.setattr(light, "engine", lambda: FakeEngine(conn))
    monkeypatch.setattr(light, "LaLigaClient", lambda **kw: client)
    monkeypatch.setattr(light, "save_raw", lambda *a, **k: None)
    monkeypatch.setattr(light.recommend, "recompute", lambda conn, **kw: {"saved": 0})
    monkeypatch.setattr(light.cash, "recompute", lambda conn, **kw: {"teams": 5})
    seen = {}

    def fake_collect(client, c, day):
        seen["day"] = day
        return {"players": 1}

    monkeypatch.setattr(light.players, "collect_players", fake_collect)
    summary = light.run()
    assert seen["day"] == light.value_day() and summary["players"] == {"players": 1}


def test_the_light_job_runs_the_full_collection_when_the_cycle_has_none(monkeypatch):
    # Autonomía: GitHub se salta disparos, así que el diario no puede depender de su propio cron.
    # El primer ligero que ve un ciclo nuevo sin recogida completa la lanza él.
    lanzado = {}

    class Conn(FakeConn):
        def execute(self, stmt, params=None):
            sql = str(stmt)
            if "job = 'daily'" in sql:  # nadie ha recogido este ciclo todavía
                conn = self

                class R:
                    def first(self_inner):
                        return None

                    def scalar(self_inner):
                        return conn.team_id

                    def scalar_one(self_inner):
                        return 1

                return R()
            return super().execute(stmt, params)

    conn = Conn()
    monkeypatch.setattr(light.settings, "league_id", "L")
    monkeypatch.setattr(light, "engine", lambda: FakeEngine(conn))
    monkeypatch.setattr(light, "LaLigaClient", lambda **kw: FakeClient())
    monkeypatch.setattr(light, "save_raw", lambda *a, **k: None)
    monkeypatch.setattr(light.recommend, "recompute", lambda conn, **kw: {"saved": 0})
    monkeypatch.setattr(
        light.league,
        "collect_market",
        lambda *a, **k: {"state": "ok", "cycle_end": "2026-09-20T17:21:00+00:00"},
    )

    import lfm.jobs.daily as daily_job

    monkeypatch.setattr(daily_job, "run", lambda **kw: lanzado.setdefault("kw", kw) or {"status": "ok"})
    light.run()
    assert lanzado["kw"] == {"skip_if_recent": False}


def test_it_does_not_repeat_the_full_collection_within_the_same_cycle(monkeypatch):
    conn = FakeConn()  # el FakeConn devuelve fila para cualquier consulta: el ciclo ya está recogido
    monkeypatch.setattr(light.settings, "league_id", "L")
    monkeypatch.setattr(light, "engine", lambda: FakeEngine(conn))
    monkeypatch.setattr(light, "LaLigaClient", lambda **kw: FakeClient())
    monkeypatch.setattr(light, "save_raw", lambda *a, **k: None)
    monkeypatch.setattr(light.recommend, "recompute", lambda conn, **kw: {"saved": 0})
    monkeypatch.setattr(
        light.league,
        "collect_market",
        lambda *a, **k: {"state": "ok", "cycle_end": "2026-09-20T17:21:00+00:00"},
    )

    import lfm.jobs.daily as daily_job

    monkeypatch.setattr(
        daily_job, "run", lambda **kw: (_ for _ in ()).throw(AssertionError("no debía lanzarse"))
    )
    summary = light.run()
    assert "daily_lanzado" not in summary
