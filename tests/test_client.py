import pytest


def test_a_server_error_is_retried_before_giving_up():
    """El 2026-09-15 un 500 suelto de LaLiga tumbo una pasada entera del job diario."""
    import httpx

    from lfm.api import client as cl

    llamadas = []

    class FakeResponse:
        def __init__(self, code):
            self.status_code = code
            self.headers = {"content-type": "application/json"}

        def json(self):
            return {"ok": True}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("boom", request=None, response=None)

    class FakeHttp:
        def get(self, url, params=None, headers=None):
            llamadas.append(url)
            return FakeResponse(500 if len(llamadas) < 3 else 200)

    c = cl.LaLigaClient.__new__(cl.LaLigaClient)
    c._http = FakeHttp()
    c._pause = lambda: None
    c._auth_headers = lambda **kw: {}
    c.on_response = None
    c._tokens = None
    cl.SERVER_ERROR_BACKOFF = 0  # sin esperas en el test
    assert c.get("/loquesea") == {"ok": True}
    assert len(llamadas) == 3  # dos fallos y el bueno


def test_it_stops_retrying_and_raises_when_the_server_keeps_failing():
    import httpx

    from lfm.api import client as cl

    llamadas = []

    class FakeResponse:
        status_code = 500
        headers = {}

        def raise_for_status(self):
            raise httpx.HTTPStatusError("boom", request=None, response=None)

    class FakeHttp:
        def get(self, url, params=None, headers=None):
            llamadas.append(url)
            return FakeResponse()

    c = cl.LaLigaClient.__new__(cl.LaLigaClient)
    c._http = FakeHttp()
    c._pause = lambda: None
    c._auth_headers = lambda **kw: {}
    c.on_response = None
    c._tokens = None
    cl.SERVER_ERROR_BACKOFF = 0
    with pytest.raises(httpx.HTTPStatusError):
        c.get("/loquesea")
    assert len(llamadas) == cl.SERVER_ERROR_RETRIES + 1


def test_a_401_forces_a_real_refresh_instead_of_reusing_the_saved_token(monkeypatch):
    # 2026-09-20: la sesión se revocó en el servidor con el token aún vigente por reloj. Pedir
    # «un token» devolvía el mismo del disco y el 401 se repetía en cada pasada.
    import httpx

    from lfm.api import client as client_mod

    pedidos = []

    class Tok:
        def __init__(self, b):
            self.bearer = b

        def is_expired(self):
            return False

    def fake_get_tokens(*, force_refresh=False):
        pedidos.append(force_refresh)
        return Tok("nuevo" if force_refresh else "viejo")

    monkeypatch.setattr(client_mod, "get_tokens", fake_get_tokens)
    monkeypatch.setattr(client_mod.settings, "request_pause_seconds", 0)

    def handler(request):
        ok = request.headers["Authorization"] == "Bearer nuevo"
        return httpx.Response(200 if ok else 401, json={"ok": ok})

    c = client_mod.LaLigaClient()
    c._http = httpx.Client(base_url="https://x", transport=httpx.MockTransport(handler))
    assert c.get("/algo") == {"ok": True}
    assert pedidos == [False, True]
