"""Autenticación contra Azure AD B2C de LaLiga.

Flujos:
- ROPC (email + contraseña): `login()`. Solo para cuentas con contraseña de LaLiga.
- Authorization Code + PKCE (cuenta de Google u otra red social): `login_google()`. Abre el
  navegador, te logueas, y pegas la URL `authredirect://...?code=...` a la que te redirige.
  Es una sola vez: a partir de ahí vive del refresh token.
- Refresh: `refresh()`. Es el que usa el job en CI: solo necesita LALIGA_REFRESH_TOKEN.

Constantes y forma de las peticiones tomadas de Externoak/LaLigaApp (authService.js, julio 2026):
mismo client id para ROPC y PKCE, policy de signin para PKCE y refresh, y la API acepta el
id_token como Bearer (B2C solo devuelve id_token para el scope openid). VERIFY con tráfico real.

Uso local:
    python -m lfm.api.auth login            # ROPC
    python -m lfm.api.auth login-google     # PKCE (añade --no-browser para no abrir el navegador)
    python -m lfm.api.auth refresh
    python -m lfm.api.auth whoami
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sys
import time
import webbrowser
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from lfm.config import settings

TENANT = "laligadspprob2c.onmicrosoft.com"
TOKEN_URL = f"https://login.laliga.es/{TENANT}/oauth2/v2.0/token"
AUTHORIZE_URL = f"https://login.laliga.es/{TENANT}/oauth2/v2.0/authorize"

# Client id de la app móvil: LaLigaApp lo usa tanto para ROPC como para PKCE y refresh. VERIFY.
EMAIL_CLIENT_ID = "af88bcff-1157-40a0-b579-030728aacf0b"
# Segundo client id que aparece en LaLigaApp. Se prueba como alternativa si el refresh con el
# principal falla (un refresh token solo vale con el client id con el que se emitió). VERIFY.
REFRESH_CLIENT_ID = "6457fa17-1224-416a-b21a-ee6ce76e9bc0"
REFRESH_CLIENT_IDS = (EMAIL_CLIENT_ID, REFRESH_CLIENT_ID)
ROPC_POLICY = "B2C_1A_ResourceOwnerv2"
SIGNIN_POLICY = "B2C_1A_5ULAIP_PARAMETRIZED_SIGNIN"
REDIRECT_URI = "authredirect://com.lfp.laligafantasy"
PKCE_SCOPE = "openid offline_access"


@dataclass
class Tokens:
    access_token: str
    id_token: str
    refresh_token: str
    expires_at: float  # epoch seconds
    client_id: str = EMAIL_CLIENT_ID  # con el que se emitió el refresh token

    @property
    def bearer(self) -> str:
        # B2C devuelve solo id_token para el scope openid y la API lo acepta como Bearer
        # (comentario en authService.js de LaLigaApp). Si hay access_token, tiene prioridad.
        return self.access_token or self.id_token

    def is_expired(self, margin: int = 300) -> bool:
        return time.time() > self.expires_at - margin

    @classmethod
    def from_response(cls, data: dict, client_id: str = EMAIL_CLIENT_ID) -> Tokens:
        return cls(
            access_token=data.get("access_token", ""),
            id_token=data.get("id_token", ""),
            refresh_token=data.get("refresh_token", ""),
            expires_at=time.time() + int(data.get("expires_in", 3600)),
            client_id=client_id,
        )

    def save_db(self, service: str = "laliga_b2c") -> None:
        """Persiste los tokens en Neon PostgreSQL (tabla auth_tokens)."""
        try:
            from sqlalchemy import text

            from lfm.db.session import engine

            sql = text(
                "INSERT INTO auth_tokens "
                "(service, access_token, id_token, refresh_token, expires_at, client_id, updated_at) "
                "VALUES (:service, :access_token, :id_token, :refresh_token, :expires_at, :client_id, now()) "
                "ON CONFLICT (service) DO UPDATE SET "
                "  access_token = EXCLUDED.access_token, "
                "  id_token = EXCLUDED.id_token, "
                "  refresh_token = EXCLUDED.refresh_token, "
                "  expires_at = EXCLUDED.expires_at, "
                "  client_id = EXCLUDED.client_id, "
                "  updated_at = now()"
            )
            with engine().begin() as conn:
                conn.execute(
                    sql,
                    {
                        "service": service,
                        "access_token": self.access_token,
                        "id_token": self.id_token,
                        "refresh_token": self.refresh_token,
                        "expires_at": self.expires_at,
                        "client_id": self.client_id,
                    },
                )
        except Exception as e:
            # Si no hay conexión a BD o el entorno no tiene DATABASE_URL, no bloqueamos el flujo
            print(f"[auth] aviso: no se pudo persistir el token en BD: {e}", file=sys.stderr)

    @classmethod
    def load_db(cls, service: str = "laliga_b2c") -> Tokens | None:
        """Carga los tokens desde Neon PostgreSQL (tabla auth_tokens)."""
        try:
            from sqlalchemy import text

            from lfm.db.session import engine

            sql = text(
                "SELECT access_token, id_token, refresh_token, expires_at, client_id "
                "FROM auth_tokens WHERE service = :service LIMIT 1"
            )
            with engine().begin() as conn:
                row = conn.execute(sql, {"service": service}).mappings().first()
            if not row:
                return None
            return cls(
                access_token=row["access_token"] or "",
                id_token=row["id_token"] or "",
                refresh_token=row["refresh_token"],
                expires_at=float(row["expires_at"]),
                client_id=row["client_id"] or EMAIL_CLIENT_ID,
            )
        except Exception:
            return None

    def save(self, path: Path = settings.tokens_file, *, to_db: bool = True) -> None:
        try:
            path.write_text(json.dumps(asdict(self), indent=2))
        except OSError:
            pass  # en CI el sistema de archivos puede ser de solo lectura o efímero
        if to_db and path == settings.tokens_file:
            self.save_db()

    @classmethod
    def load(cls, path: Path = settings.tokens_file) -> Tokens | None:
        if not path.exists():
            return None
        return cls(**json.loads(path.read_text()))


# --- ROPC ----------------------------------------------------------------------------------


def login(email: str, password: str) -> Tokens:
    """ROPC: email + contraseña → tokens."""
    data = {
        "grant_type": "password",
        "username": email,
        "password": password,
        "client_id": EMAIL_CLIENT_ID,
        "scope": f"openid {EMAIL_CLIENT_ID} offline_access",
        "response_type": "token id_token",
        "redirect_uri": REDIRECT_URI,
    }
    r = httpx.post(TOKEN_URL, params={"p": ROPC_POLICY}, data=data, timeout=30)
    r.raise_for_status()
    return Tokens.from_response(r.json(), EMAIL_CLIENT_ID)


# --- Authorization Code + PKCE (Google) -----------------------------------------------------


def code_challenge(verifier: str) -> str:
    """S256 (RFC 7636): base64url(sha256(verifier)) sin relleno."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]  # RFC 7636: entre 43 y 128 caracteres
    return verifier, code_challenge(verifier)


def build_authorize_url(challenge: str, state: str, client_id: str = EMAIL_CLIENT_ID) -> str:
    # Sin prompt=login a propósito (como LaLigaApp): así reutiliza una sesión de Google abierta.
    q = {
        "p": SIGNIN_POLICY,
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": PKCE_SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "nonce": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(q)}"


def parse_redirect(pasted: str, state: str | None = None) -> str:
    """Saca el `code` de lo que pegue el usuario: la URL `authredirect://...?code=...&state=...`
    completa, solo su query, o directamente el código."""
    text = pasted.strip().strip("'\"")
    if not text:
        raise ValueError("No has pegado nada")
    if "://" not in text and "=" not in text:
        if any(c in text for c in " ?&/"):
            raise ValueError("Eso no parece ni una URL de redirección ni un código")
        return text
    query = urlsplit(text).query if "://" in text else text.split("?", 1)[-1]
    params = parse_qs(query)
    if "error" in params:
        desc = params.get("error_description", [""])[0]
        raise RuntimeError(f"B2C devolvió error: {params['error'][0]} {desc}".strip())
    code = params.get("code", [""])[0]
    if not code:
        raise ValueError("La URL pegada no lleva 'code'")
    if state and params.get("state", [None])[0] != state:
        raise RuntimeError("El 'state' no coincide: pega la URL de ESTE intento, no de uno anterior")
    return code


def exchange_code(code: str, verifier: str, client_id: str = EMAIL_CLIENT_ID) -> Tokens:
    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
        "scope": PKCE_SCOPE,
    }
    r = httpx.post(TOKEN_URL, params={"p": SIGNIN_POLICY}, data=data, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"Canje del código falló: {r.status_code} {r.text[:300]}")
    return Tokens.from_response(r.json(), client_id)


GOOGLE_INSTRUCTIONS = """\
1. Se abre el navegador con el login de LaLiga. Entra con tu cuenta de Google.
2. Al terminar, el navegador intenta ir a una dirección que empieza por
   authredirect://com.lfp.laligafantasy?code=...  y no sabe abrirla. Es normal.
   - Chrome/Edge: abre DevTools (F12) > Consola. Verás en rojo "Failed to launch
     'authredirect://...' because the scheme does not have a registered handler".
     Clic derecho en ese enlace > Copiar dirección de enlace.
   - Firefox: la URL completa queda en la barra de direcciones. Cópiala.
3. Pégalo aquí abajo (vale la URL entera o solo el valor de code).
"""


def login_google(*, open_browser: bool = True, prompt: Callable[[str], str] = input) -> Tokens:
    """PKCE con pegado manual de la redirección. Una sola vez: luego vive del refresh token."""
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    url = build_authorize_url(challenge, state)
    print(GOOGLE_INSTRUCTIONS)
    print(f"URL de login:\n{url}\n")
    if open_browser:
        webbrowser.open(url)
    code = parse_redirect(prompt("Pega la URL authredirect://... (o el code): "), state)
    return exchange_code(code, verifier)


# --- Refresh ---------------------------------------------------------------------------------


def refresh(refresh_token: str, client_id: str | None = None) -> Tokens:
    """Refresh token → tokens nuevos (el refresh token puede rotar: guarda el nuevo).

    Si no se sabe con qué client id se emitió (p. ej. viene de LALIGA_REFRESH_TOKEN), se prueban
    los conocidos en orden."""
    candidates = (client_id,) if client_id else REFRESH_CLIENT_IDS
    errors: list[str] = []
    for cid in candidates:
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": cid,
            "scope": PKCE_SCOPE,
        }
        r = httpx.post(TOKEN_URL, params={"p": SIGNIN_POLICY}, data=data, timeout=30)
        if r.status_code < 400:
            tokens = Tokens.from_response(r.json(), cid)
            if not tokens.refresh_token:
                tokens.refresh_token = refresh_token
            return tokens
        errors.append(f"[{cid}] {r.status_code} {r.text[:200]}")
    raise RuntimeError("Refresh falló: " + " | ".join(errors))


def get_tokens(*, force_refresh: bool = False) -> Tokens:
    """Estrategia de tokens con auto-rotación y persistencia en BD:
    1. Archivo local válido sin expirar
    2. Base de datos Neon válida sin expirar
    3. Refresh usando el refresh_token guardado en Neon DB (rotación continua)
    4. Refresh usando el refresh_token de archivo local
    5. Refresh usando variable de entorno LALIGA_REFRESH_TOKEN (seed de GitHub Secrets)
    6. Login ROPC con LALIGA_EMAIL + LALIGA_PASSWORD
    """
    # `force_refresh`: la API acaba de responder 401 con un token que por reloj seguía vigente
    # (sesión revocada en el servidor). Devolver el mismo token guardado repetía el 401 sin fin:
    # pasó el 2026-09-20, con el mercado y las plantillas fallando y /players, que no pide sesión,
    # funcionando. Se salta directamente al refresh.
    # 1. Archivo local válido
    local = Tokens.load()
    if local and not local.is_expired() and not force_refresh:
        return local

    # 2. Base de datos válida en Neon
    db_tokens = Tokens.load_db()
    if db_tokens and not db_tokens.is_expired() and not force_refresh:
        # Sincronizamos con el archivo local si estamos en un entorno con disco persistente
        try:
            settings.tokens_file.write_text(json.dumps(asdict(db_tokens), indent=2))
        except OSError:
            pass
        return db_tokens

    # 3. Refresh desde Neon DB (es la credencial más fresca en CI)
    if db_tokens and db_tokens.refresh_token:
        try:
            tokens = refresh(db_tokens.refresh_token, db_tokens.client_id)
            tokens.save()
            return tokens
        except Exception as e:
            print(
                f"[auth] refresh desde Neon DB falló ({e}); probando fuentes secundarias...",
                file=sys.stderr,
            )

    # 4. Refresh desde archivo local
    if local and local.refresh_token:
        try:
            tokens = refresh(local.refresh_token, local.client_id)
            tokens.save()
            return tokens
        except Exception as e:
            print(
                f"[auth] refresh desde archivo local falló ({e}); probando variables de entorno...",
                file=sys.stderr,
            )

    # 5. Refresh desde variable de entorno (seed inicial)
    if settings.laliga_refresh_token:
        try:
            tokens = refresh(settings.laliga_refresh_token)
            tokens.save()
            return tokens
        except Exception as e:
            print(f"[auth] refresh desde env falló ({e})", file=sys.stderr)

    # 6. ROPC email + password
    if settings.laliga_email and settings.laliga_password:
        tokens = login(settings.laliga_email, settings.laliga_password)
        tokens.save()
        return tokens

    raise RuntimeError(
        "Sin credenciales válidas: ejecuta `python -m lfm.api.auth login-google` (cuenta de Google) "
        "o rellena LALIGA_EMAIL/LALIGA_PASSWORD (cuenta con contraseña) o LALIGA_REFRESH_TOKEN"
    )


def _main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "help"
    if cmd == "login":
        tokens = login(settings.laliga_email, settings.laliga_password)
        tokens.save()
        print(f"OK. Tokens guardados en {settings.tokens_file} y en Neon DB.")
    elif cmd == "login-google":
        try:
            tokens = login_google(open_browser="--no-browser" not in argv)
        except (ValueError, RuntimeError) as e:
            print(f"\nNo se pudo completar el login: {e}")
            return 1
        tokens.save()
        print(f"OK. Tokens guardados en {settings.tokens_file} y en Neon DB.")
    elif cmd == "refresh":
        tokens = get_tokens()
        print(f"OK. Token listo y persistido. Caduca en {int(tokens.expires_at - time.time())} s")
    elif cmd == "seed-db":
        local = Tokens.load()
        if not local:
            print(f"Error: no existe {settings.tokens_file}. Ejecuta primero login-google.")
            return 1
        local.save_db()
        print("OK. Tokens locales sincronizados con la tabla auth_tokens en Neon.")
    elif cmd == "status":
        local = Tokens.load()
        db_tokens = Tokens.load_db()
        now = time.time()
        print("=== Estado de Tokens ===")
        if local:
            exp = int(local.expires_at - now)
            st = "Válido" if exp > 0 else "Expirado"
            print(f"Local (.tokens.json): Presente ({st}, expira en {exp} s)")
        else:
            print("Local (.tokens.json): No encontrado")
        if db_tokens:
            exp = int(db_tokens.expires_at - now)
            st = "Válido" if exp > 0 else "Expirado"
            print(f"Neon DB (auth_tokens): Presente ({st}, expira en {exp} s)")
        else:
            print("Neon DB (auth_tokens): No encontrado")
    elif cmd == "whoami":
        from lfm.api.client import LaLigaClient

        with LaLigaClient() as c:
            print(json.dumps(c.me(), indent=2, ensure_ascii=False))
            print(json.dumps(c.leagues(), indent=2, ensure_ascii=False))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
