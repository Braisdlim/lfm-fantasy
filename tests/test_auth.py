"""Flujo PKCE (cuenta de Google), refresh y persistencia de tokens. Sin red: respx."""

import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from lfm.api import auth

TOKEN_RESPONSE = {"id_token": "idt", "refresh_token": "rt-new", "expires_in": 3600, "token_type": "Bearer"}


def _form(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


def test_code_challenge_matches_rfc7636_vector():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert auth.code_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_pkce_pair_length_is_within_rfc_limits():
    verifier, challenge = auth.pkce_pair()
    assert 43 <= len(verifier) <= 128
    assert challenge == auth.code_challenge(verifier)


def test_authorize_url_carries_the_laligaapp_parameters():
    url = auth.build_authorize_url("chal", "st")
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == auth.AUTHORIZE_URL
    q = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert q == {
        "p": auth.SIGNIN_POLICY,
        "client_id": auth.EMAIL_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": auth.REDIRECT_URI,
        "scope": "openid offline_access",
        "code_challenge": "chal",
        "code_challenge_method": "S256",
        "state": "st",
        "nonce": "st",
    }


@pytest.mark.parametrize(
    "pasted",
    [
        "authredirect://com.lfp.laligafantasy?code=abc.def&state=st",
        "  'authredirect://com.lfp.laligafantasy/?state=st&code=abc.def'  ",
        "code=abc.def&state=st",
        "abc.def",
    ],
)
def test_parse_redirect_accepts_url_query_or_bare_code(pasted):
    assert auth.parse_redirect(pasted, "st") == "abc.def"


def test_parse_redirect_rejects_wrong_state_errors_and_garbage():
    with pytest.raises(RuntimeError, match="state"):
        auth.parse_redirect("authredirect://com.lfp.laligafantasy?code=x&state=otro", "st")
    with pytest.raises(RuntimeError, match="access_denied"):
        auth.parse_redirect("authredirect://x?error=access_denied&error_description=cancelado")
    with pytest.raises(ValueError):
        auth.parse_redirect("https://google.com/?q=hola")
    with pytest.raises(ValueError):
        auth.parse_redirect("")


@respx.mock
def test_login_google_exchanges_the_pasted_code_with_pkce(capsys):
    route = respx.post(auth.TOKEN_URL).mock(return_value=httpx.Response(200, json=TOKEN_RESPONSE))
    seen: dict = {}

    def fake_prompt(_msg: str) -> str:
        # simula al usuario: lee el state de la URL impresa y devuelve la redirección
        printed = capsys.readouterr().out
        url = next(line for line in printed.splitlines() if line.startswith("https://"))
        seen["state"] = parse_qs(urlsplit(url).query)["state"][0]
        seen["challenge"] = parse_qs(urlsplit(url).query)["code_challenge"][0]
        return f"{auth.REDIRECT_URI}?code=CODE123&state={seen['state']}"

    tokens = auth.login_google(open_browser=False, prompt=fake_prompt)

    assert tokens.refresh_token == "rt-new" and tokens.bearer == "idt"
    assert tokens.client_id == auth.EMAIL_CLIENT_ID
    req = route.calls.last.request
    assert req.url.params["p"] == auth.SIGNIN_POLICY
    form = _form(req)
    assert form["grant_type"] == "authorization_code" and form["code"] == "CODE123"
    assert form["redirect_uri"] == auth.REDIRECT_URI and form["client_id"] == auth.EMAIL_CLIENT_ID
    assert auth.code_challenge(form["code_verifier"]) == seen["challenge"]


@respx.mock
def test_refresh_tries_known_client_ids_until_one_works():
    def responder(request: httpx.Request) -> httpx.Response:
        if _form(request)["client_id"] == auth.REFRESH_CLIENT_ID:
            return httpx.Response(200, json=TOKEN_RESPONSE)
        return httpx.Response(400, json={"error": "invalid_grant"})

    route = respx.post(auth.TOKEN_URL).mock(side_effect=responder)
    tokens = auth.refresh("rt-old")
    assert tokens.client_id == auth.REFRESH_CLIENT_ID
    assert route.call_count == 2


@respx.mock
def test_refresh_with_known_client_id_keeps_old_token_if_none_rotated():
    respx.post(auth.TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"id_token": "x", "expires_in": 10})
    )
    tokens = auth.refresh("rt-old", auth.EMAIL_CLIENT_ID)
    assert tokens.refresh_token == "rt-old"


@respx.mock
def test_refresh_reports_every_failed_client_id():
    respx.post(auth.TOKEN_URL).mock(return_value=httpx.Response(400, text="invalid_grant"))
    with pytest.raises(RuntimeError, match=f"{auth.EMAIL_CLIENT_ID}.*{auth.REFRESH_CLIENT_ID}"):
        auth.refresh("rt-old")


def test_tokens_roundtrip_and_old_files_without_client_id_still_load(tmp_path):
    p = tmp_path / "t.json"
    auth.Tokens("a", "i", "r", time.time() + 10, auth.REFRESH_CLIENT_ID).save(p)
    assert auth.Tokens.load(p).client_id == auth.REFRESH_CLIENT_ID
    p.write_text(json.dumps({"access_token": "", "id_token": "i", "refresh_token": "r", "expires_at": 1}))
    old = auth.Tokens.load(p)
    assert old.client_id == auth.EMAIL_CLIENT_ID and old.is_expired()
