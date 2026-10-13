"""El canal de avisos: nunca puede tumbar el job que lo usa."""

import httpx
import pytest

from lfm.jobs import daily, light
from lfm.notify import telegram


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("sin json")
        return self._payload


@pytest.fixture
def con_credenciales(monkeypatch):
    monkeypatch.setattr(telegram.settings, "telegram_bot_token", "T", raising=False)
    monkeypatch.setattr(telegram.settings, "telegram_chat_id", "42", raising=False)


def test_without_credentials_it_prints_and_reports_not_sent(monkeypatch, capsys):
    monkeypatch.setattr(telegram.settings, "telegram_bot_token", None, raising=False)
    monkeypatch.setattr(telegram.settings, "telegram_chat_id", None, raising=False)
    assert telegram.send("hola") is False
    assert "telegram desactivado" in capsys.readouterr().out


def test_a_network_error_is_swallowed_not_raised(monkeypatch, capsys, con_credenciales):
    def boom(*a, **k):
        raise httpx.ConnectError("sin red")

    monkeypatch.setattr(telegram.httpx, "post", boom)
    assert telegram.send("hola") is False  # no lanza
    assert "no se pudo enviar" in capsys.readouterr().out


def test_an_api_rejection_explains_why(monkeypatch, capsys, con_credenciales):
    monkeypatch.setattr(
        telegram.httpx,
        "post",
        lambda *a, **k: FakeResponse(400, {"description": "chat not found"}),
    )
    assert telegram.send("hola") is False
    assert "chat not found" in capsys.readouterr().out


def test_a_successful_send_reports_true(monkeypatch, con_credenciales):
    monkeypatch.setattr(telegram.httpx, "post", lambda *a, **k: FakeResponse(200, {"ok": True}))
    assert telegram.send("hola") is True


def test_chat_id_lists_the_chats_that_wrote_to_the_bot(monkeypatch):
    payload = {
        "result": [
            {"message": {"chat": {"id": 42, "first_name": "Demo Manager", "type": "private"}}},
            {"message": {"chat": {"id": 42, "first_name": "Demo Manager", "type": "private"}}},  # repetido
            {"channel_post": {"chat": {"id": -100, "title": "Avisos lfm", "type": "channel"}}},
        ]
    }

    class R(FakeResponse):
        def raise_for_status(self):
            return None

    monkeypatch.setattr(telegram.httpx, "get", lambda *a, **k: R(200, payload))
    assert telegram.chat_id_from_updates("T") == [("-100", "Avisos lfm"), ("42", "Demo Manager")]


# --- aislamiento respecto al job -------------------------------------------------------------------


def test_a_broken_notification_never_fails_a_good_collection(monkeypatch, capsys):
    """El 2026-09-08 dos ejecuciones se dieron por fallidas con todos los datos ya guardados."""

    def boom(*a, **k):
        raise TypeError("unsupported operand type(s) for /: 'decimal.Decimal' and 'float'")

    monkeypatch.setattr(daily.alerts, "daily_message", boom)
    monkeypatch.setattr(daily.settings, "league_id", "L", raising=False)
    daily._notify("ok", None, {"missing_days": []}, day=daily.date(2026, 9, 9), quiet=False)
    assert "no se pudo componer el aviso" in capsys.readouterr().err


def test_a_failed_run_is_reported_and_the_summary_is_not_built(monkeypatch):
    enviados = []
    monkeypatch.setattr(daily.telegram, "send", lambda t, **k: enviados.append(t) or True)
    monkeypatch.setattr(daily.alerts, "daily_message", lambda *a, **k: pytest.fail("no debe llamarse"))
    daily._notify("error", "Traceback: boom", {}, day=daily.date(2026, 9, 9), quiet=False)
    assert len(enviados) == 1 and "falló" in enviados[0] and "boom" in enviados[0]


def test_quiet_suppresses_the_summary_but_not_a_failure(monkeypatch):
    enviados = []
    monkeypatch.setattr(daily.telegram, "send", lambda t, **k: enviados.append(t) or True)
    monkeypatch.setattr(daily.settings, "league_id", "L", raising=False)
    daily._notify("ok", None, {"missing_days": []}, day=daily.date(2026, 9, 9), quiet=True)
    assert enviados == []
    daily._notify("error", "boom", {}, day=daily.date(2026, 9, 9), quiet=True)
    assert len(enviados) == 1


# --- el job ligero solo avisa cuando encadena fallos -----------------------------------------------


def stub_runs(monkeypatch, estados):
    """Sustituye la consulta a job_runs por la lista de estados dada, la más reciente primero."""

    class Conn:
        def execute(self, *a, **k):
            return self

        def scalars(self):
            return self

        def all(self):
            return estados

    class Engine:
        def begin(self):
            from contextlib import nullcontext

            return nullcontext(Conn())

    monkeypatch.setattr(light, "engine", lambda: Engine())


def test_one_failure_alone_says_nothing(monkeypatch):
    enviados = []
    monkeypatch.setattr(light.telegram, "send", lambda t, **k: enviados.append(t) or True)
    stub_runs(monkeypatch, ["error", "ok", "ok"])
    light._notify_if_stuck("boom")
    assert enviados == []


def test_three_failures_in_a_row_do_raise_the_alarm(monkeypatch):
    enviados = []
    monkeypatch.setattr(light.telegram, "send", lambda t, **k: enviados.append(t) or True)
    stub_runs(monkeypatch, ["error", "error", "error"])
    light._notify_if_stuck("boom")
    assert len(enviados) == 1 and "no se está actualizando" in enviados[0]


def test_with_too_little_history_it_stays_quiet(monkeypatch):
    """Al estrenar la tabla no hay tres pasadas todavía: callarse es lo correcto."""
    enviados = []
    monkeypatch.setattr(light.telegram, "send", lambda t, **k: enviados.append(t) or True)
    stub_runs(monkeypatch, ["error"])
    light._notify_if_stuck("boom")
    assert enviados == []
