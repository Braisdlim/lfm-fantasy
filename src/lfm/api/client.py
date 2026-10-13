"""Cliente HTTP de la API de LaLiga Fantasy: auth, pausas, reintentos y captura del JSON crudo.

Cada respuesta pasa por `on_response(endpoint, params, payload)` si se registra un callback,
que es como los colectores guardan el raw en `raw_snapshots` sin acoplar el cliente a la BD.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from lfm.api import endpoints as ep
from lfm.api.auth import Tokens, get_tokens
from lfm.config import settings

RawCallback = Callable[[str, dict[str, Any] | None, Any], None]


# Reintentos ante un 5xx de la API. Pocos y con espera: no es un problema nuestro y tampoco hay
# que castigar su servidor. Cuentan contra el presupuesto de peticiones, así que dos bastan.
SERVER_ERROR_RETRIES = 2
SERVER_ERROR_BACKOFF = 3.0  # segundos, multiplicados por el número de intento


class RateLimited(Exception):
    pass


class LaLigaClient:
    def __init__(self, on_response: RawCallback | None = None) -> None:
        self.cmp = settings.competition_id
        self.on_response = on_response
        self._tokens: Tokens | None = None
        self._http = httpx.Client(base_url=ep.BASE_URL, headers=ep.DEFAULT_HEADERS, timeout=20)
        self._last_request = 0.0

    # --- ciclo de vida -------------------------------------------------------------------
    def __enter__(self) -> LaLigaClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self._http.close()

    def _auth_headers(self, *, force_refresh: bool = False) -> dict[str, str]:
        if force_refresh or self._tokens is None or self._tokens.is_expired():
            self._tokens = get_tokens(force_refresh=force_refresh)
        return {"Authorization": f"Bearer {self._tokens.bearer}"}

    def _pause(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < settings.request_pause_seconds:
            time.sleep(settings.request_pause_seconds - elapsed)
        self._last_request = time.monotonic()

    # --- petición base -----------------------------------------------------------------
    @retry(
        retry=retry_if_exception_type((RateLimited, httpx.TransportError)),
        wait=wait_exponential(multiplier=5, min=5, max=120),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def get(self, path: str, params: dict[str, Any] | None = None, base_url: str | None = None):
        q = {"x-lang": "es", **(params or {})}
        url = f"{base_url}{path}" if base_url else path
        r = None
        for intento in range(SERVER_ERROR_RETRIES + 1):
            self._pause()
            try:
                r = self._http.get(url, params=q, headers=self._auth_headers())
            except httpx.TransportError:
                # La red se cae a ratos. Si era el último intento, que se vea el error de verdad.
                if intento == SERVER_ERROR_RETRIES:
                    raise
                time.sleep(SERVER_ERROR_BACKOFF * (intento + 1))
                continue
            if r.status_code == 429:
                raise RateLimited(path)
            if r.status_code == 401:
                # Token rechazado antes de su caducidad: se pide uno nuevo **de verdad** (refresh),
                # no el mismo guardado en disco o en Neon, y se reintenta una vez.
                self._pause()
                r = self._http.get(url, params=q, headers=self._auth_headers(force_refresh=True))
            # Un 5xx es la API de LaLiga teniendo un mal rato, no un problema nuestro: se reintenta.
            # El 2026-09-15 un 500 suelto tumbó una pasada entera del job.
            if r.status_code < 500 or intento == SERVER_ERROR_RETRIES:
                break
            time.sleep(SERVER_ERROR_BACKOFF * (intento + 1))
        assert r is not None
        r.raise_for_status()
        payload = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
        if self.on_response:
            self.on_response(path, params, payload)
        return payload

    # --- lecturas de alto nivel --------------------------------------------------------
    def me(self):
        return self.get(ep.READ.me())

    def leagues(self):
        return self.get(ep.READ.leagues(self.cmp))

    def standing(self, league_id: str, week: int | None = None):
        return self.get(ep.READ.standing(self.cmp, league_id, week))

    def activity(self, league_id: str, index: int = 0):
        return self.get(ep.READ.activity(self.cmp, league_id, index))

    def team(self, league_id: str, team_id: str):
        return self.get(ep.READ.team(self.cmp, league_id, team_id))

    def market(self, league_id: str):
        return self.get(ep.READ.market(self.cmp, league_id))

    def players(self):
        return self.get(ep.READ.players(self.cmp))

    def player_detail(self, player_id: str, league_id: str):
        return self.get(ep.READ.player_detail(self.cmp, player_id, league_id))

    def current_week(self):
        return self.get(ep.READ.current_week(self.cmp))

    def calendar(self, week: int):
        # httpx sustituye la query de la ruta por `params`: weekNumber va como parámetro
        path, _, query = ep.READ.calendar(self.cmp, week).partition("?")
        return self.get(path, params=dict(kv.split("=", 1) for kv in query.split("&") if kv))

    def money(self, team_id: str):
        return self.get(ep.READ.money(self.cmp, team_id))

    def lineup(self, team_id: str, week: int | None = None):
        path = ep.READ.lineup_week(self.cmp, team_id, week) if week else ep.READ.lineup(self.cmp, team_id)
        return self.get(path)

    def week_stats(self, week: int):
        return self.get(ep.READ.week_stats(self.cmp, week), base_url=ep.STATS_BASE_URL)
