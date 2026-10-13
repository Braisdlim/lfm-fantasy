"""FútbolFantasy: histórico diario de valor de mercado de LaLiga Fantasy (backfill).

Verificado el 2026-09-08:
- `MARKET_URL` devuelve una tabla con una fila `<tr class="elemento_jugador" data-...>` por jugador
  (674, sin los que ya no están en LaLiga): data-id (los entrenadores llevan prefijo `e`),
  data-nombre (minúsculas, con tildes), data-posicion (Portero | Defensa | Mediocampista |
  Delantero | Entrenador), data-equipo (id propio de FútbolFantasy; el `<select name="equipo">`
  da los nombres), data-valor y data-valorN / data-diferenciaN para N en 1, 2, 3, 7, 14, 30.
- `DETAIL_URL` (lo que la ficha carga por AJAX) trae la serie diaria completa desde el inicio de
  temporada como `player_chartjs.push({date: "dd/mm", value: N})`, del día más reciente al más
  antiguo (70 puntos el 8 de septiembre, sin huecos). `player_chartjs_30` es la ventana de 30 días
  y `player_chartjs_prev` la temporada anterior: se ignoran.

Uso:
    python -m lfm.sources.futbolfantasy backfill [--dry-run] [--concurrency 3]

El backfill casa cada jugador de FútbolFantasy con su `player_id` de LaLiga (club + posición +
nombre), guarda el casado en `player_aliases`, descarga las series respetando el límite del
servidor (30 peticiones por 10 s, unos 3,5 minutos en total; reanudable) y las inserta en
`player_value_daily` con
source='futbolfantasy_backfill' SIN pisar nunca una fila que venga de la API.
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.engine import Connection

MARKET_URL = "https://www.futbolfantasy.com/analytics/laliga-fantasy/mercado"
DETAIL_URL = "https://www.futbolfantasy.com/analytics/laliga-fantasy/mercado/detalle/{ff_id}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128 Safari/537.36",
    "Accept-Language": "es-ES,es;q=0.9",
}
SOURCE = "futbolfantasy"
VALUE_SOURCE = "futbolfantasy_backfill"
POSITION_IDS = {"Portero": 1, "Defensa": 2, "Mediocampista": 3, "Delantero": 4, "Entrenador": 5}
HORIZONS = (1, 2, 3, 7, 14, 30)

_ROW_RE = re.compile(r'<tr class="elemento_jugador[^"]*"([^>]*)>')
_ATTR_RE = re.compile(r'data-([a-z0-9\-]+)="([^"]*)"')
_SELECT_RE = re.compile(r'<select[^>]*name="equipo"[^>]*>(.*?)</select>', re.S)
_OPTION_RE = re.compile(r'<option value="(\d+)"[^>]*>([^<]+)</option>')
_PUSH_RE = re.compile(r'player_chartjs\.push\(\{\s*date:\s*"([^"]+)"\s*,\s*value:\s*(-?[0-9]+)')


# --- parseo puro ---------------------------------------------------------------------------------


@dataclass
class MarketRow:
    ff_id: str
    name: str
    position: str
    ff_team_id: str
    value: int
    values: dict[int, int] = field(default_factory=dict)  # horizonte en días → valor entonces

    @property
    def position_id(self) -> int | None:
        return POSITION_IDS.get(self.position)


def parse_market(html: str) -> list[MarketRow]:
    rows = []
    for attrs in _ROW_RE.findall(html):
        d = dict(_ATTR_RE.findall(attrs))
        if not d.get("id") or not d.get("valor"):
            continue
        values = {h: int(d[f"valor{h}"]) for h in HORIZONS if d.get(f"valor{h}", "").lstrip("-").isdigit()}
        rows.append(
            MarketRow(
                ff_id=d["id"],
                name=d.get("nombre", "").strip(),
                position=d.get("posicion", ""),
                ff_team_id=d.get("equipo", ""),
                value=int(d["valor"]),
                values=values,
            )
        )
    return rows


def parse_market_teams(html: str) -> dict[str, str]:
    """id de equipo de FútbolFantasy → nombre corto ('28' → 'Alavés')."""
    m = _SELECT_RE.search(html)
    if not m:
        return {}
    return {tid: name.strip() for tid, name in _OPTION_RE.findall(m.group(1)) if tid != "0"}


def assign_years(day_month: list[str], today: date) -> list[date]:
    """'dd/mm' del más reciente al más antiguo → fechas completas. Al retroceder, si una fecha
    resulta posterior a la anterior es que hemos cruzado un cambio de año."""
    out: list[date] = []
    year = today.year
    prev: date | None = None
    for dm in day_month:
        dd, mm = (int(x) for x in dm.replace("\\/", "/").split("/"))
        d = date(year, mm, dd)
        if prev is not None and d > prev:
            year -= 1
            d = date(year, mm, dd)
        if d > today:  # el primer punto no puede ser futuro
            year -= 1
            d = date(year, mm, dd)
        out.append(d)
        prev = d
    return out


def parse_detail(html: str, today: date) -> list[tuple[date, int]]:
    """Serie diaria completa (player_chartjs), ordenada de más antigua a más reciente."""
    pts = _PUSH_RE.findall(html)
    if not pts:
        return []
    days = assign_years([d for d, _ in pts], today)
    series = sorted({(d, int(v)) for d, (_, v) in zip(days, pts, strict=True)})
    return series


# --- casado con LaLiga ----------------------------------------------------------------------------


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", s.lower()).split())


def match_clubs(ff_teams: dict[str, str], clubs: dict[str, str]) -> dict[str, str]:
    """id FútbolFantasy → team_id LaLiga. Un nombre corto de FF ('Deportivo') puede estar contenido
    en varios nombres largos ('RC Deportivo', 'Deportivo Alavés'): se asignan primero los únicos y
    se itera, de modo que 'Alavés' se lleva 'Deportivo Alavés' y 'Deportivo' queda para el otro."""
    pending = {ff_id: set(norm(name).split()) for ff_id, name in ff_teams.items()}
    free = {tid: set(norm(name).split()) for tid, name in clubs.items()}
    result: dict[str, str] = {}
    progress = True
    while pending and progress:
        progress = False
        for ff_id, tokens in list(pending.items()):
            cands = [tid for tid, ctoks in free.items() if tokens <= ctoks]
            if len(cands) == 1:
                result[ff_id] = cands[0]
                free.pop(cands[0])
                pending.pop(ff_id)
                progress = True
    return result


@dataclass
class ApiPlayer:
    player_id: str
    name: str
    nickname: str
    position_id: int | None
    team_id: str | None


TOKEN_ALIASES = {"jr": "junior"}


def _tokens(s: str) -> list[str]:
    return [TOKEN_ALIASES.get(t, t) for t in norm(s).split()]


def _covers(short: list[str], long: list[str]) -> bool:
    """Cada token de `short` se corresponde con un token distinto de `long`: igual, inicial
    ('f' ↔ 'femenia') o prefijo de al menos 4 letras ('gorrotxa' ↔ 'gorrotxategi')."""
    if not short or not long:
        return False
    free = list(long)
    for t in short:
        hit = next(
            (
                x
                for x in free
                if x == t or (len(t) == 1 and x.startswith(t)) or (len(t) >= 4 and x.startswith(t))
            ),
            None,
        )
        if hit is None:
            return False
        free.remove(hit)
    return True


def _score(ff_name: str, p: ApiPlayer, *, coach: bool = False) -> float:
    ff = _tokens(ff_name)
    full, nick = _tokens(p.name), _tokens(p.nickname)
    if ff and ff in (full, nick):
        return 1.0
    if nick and set(nick) <= set(ff):
        return 0.95
    if full and set(full) <= set(ff):
        return 0.93
    if ff and set(ff) <= set(full):
        return 0.9
    if _covers(nick, ff) or _covers(full, ff):
        return 0.9  # apodos con inicial o abreviados: 'Kiko F.', 'A. Martinez', 'Vini Jr.'
    ff_s, full_s, nick_s = " ".join(ff), " ".join(full), " ".join(nick)
    ratio = max(difflib.SequenceMatcher(None, ff_s, x).ratio() for x in (full_s, nick_s) if x)
    if ff and ff[-1] in (full[-1:] + nick[-1:]):
        ratio = max(ratio, 0.85)  # mismo apellido en el mismo club
    if coach and p.position_id == 5 and set(ff) & (set(full) | set(nick)):
        ratio = max(ratio, 0.85)  # un entrenador por club: basta un token en común
    return ratio


def match_players(
    rows: list[MarketRow], api_players: list[ApiPlayer], club_map: dict[str, str], *, threshold: float = 0.8
) -> tuple[dict[str, tuple[str, float]], list[MarketRow]]:
    """ff_id → (player_id, confianza). Candidatos del mismo club; se prefiere la misma posición.
    Asignación uno a uno por confianza descendente."""
    by_club: dict[str | None, list[ApiPlayer]] = {}
    for p in api_players:
        by_club.setdefault(p.team_id, []).append(p)
    scored: list[tuple[float, str, str]] = []
    for r in rows:
        team_id = club_map.get(r.ff_team_id)
        for p in by_club.get(team_id, []):
            s = _score(r.name, p, coach=r.position_id == 5)
            if r.position_id is not None and p.position_id is not None and r.position_id != p.position_id:
                s -= 0.1
            if s >= threshold:
                scored.append((s, r.ff_id, p.player_id))
    scored.sort(reverse=True)
    result: dict[str, tuple[str, float]] = {}
    taken: set[str] = set()
    for s, ff_id, pid in scored:
        if ff_id in result or pid in taken:
            continue
        result[ff_id] = (pid, round(s, 3))
        taken.add(pid)
    unmatched = [r for r in rows if r.ff_id not in result]
    return result, unmatched


# --- descarga ----------------------------------------------------------------------------------------


RATE_LIMIT_PER_WINDOW = 30  # cabeceras x-ratelimit-limit / x-ratelimit-window del servidor (30 por 10 s)
RATE_WINDOW_SECONDS = 10.0


async def fetch_details(
    ff_ids: list[str], *, concurrency: int = 3, retries: int = 4, rate: float | None = None
) -> dict[str, str]:
    """ff_id → HTML del detalle. Respeta el límite publicado por el servidor (30 peticiones por
    10 s) espaciando los arranques; ante un 429 espera la ventana y reintenta. Los 404 y los fallos
    definitivos se devuelven como cadena vacía."""
    min_interval = rate if rate is not None else RATE_WINDOW_SECONDS / RATE_LIMIT_PER_WINDOW * 1.05
    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    last_start = [0.0]
    out: dict[str, str] = {}

    async def pace() -> None:
        async with lock:
            now = asyncio.get_running_loop().time()
            wait = last_start[0] + min_interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            last_start[0] = asyncio.get_running_loop().time()

    async def one(client: httpx.AsyncClient, ff_id: str) -> None:
        async with sem:
            for attempt in range(retries + 1):
                await pace()
                try:
                    r = await client.get(DETAIL_URL.format(ff_id=ff_id))
                except httpx.TransportError:
                    if attempt == retries:
                        out[ff_id] = ""
                        return
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                if r.status_code == 404:
                    out[ff_id] = ""
                    return
                if r.status_code == 429 or r.status_code >= 500:
                    if attempt == retries:
                        out[ff_id] = ""
                        return
                    retry_after = r.headers.get("retry-after")
                    await asyncio.sleep(float(retry_after) if retry_after else RATE_WINDOW_SECONDS)
                    continue
                out[ff_id] = r.text
                return

    async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        await asyncio.gather(*(one(client, i) for i in ff_ids))
    return out


def fetch_market_html() -> str:
    r = httpx.get(MARKET_URL, headers=HEADERS, timeout=60, follow_redirects=True)
    r.raise_for_status()
    return r.text


# --- carga ---------------------------------------------------------------------------------------------

SQL_VALUES = text(
    "INSERT INTO player_value_daily (player_id, day, market_value, source) "
    "SELECT r.player_id, r.day, r.market_value, :source "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(player_id text, day date, market_value bigint) "
    # Un cero no es un valor: es el hueco de antes de que el jugador cotizara. Guardarlo hacía que
    # la app restara contra cero y anunciara como subida de 30 días el valor entero del jugador.
    # Comprobado el 2026-09-09: los 7.453 ceros precedían todos al primer valor real de su jugador.
    "WHERE r.market_value > 0 "
    "ON CONFLICT (player_id, day) DO NOTHING"  # nunca pisa la API
)

SQL_ALIASES = text(
    "INSERT INTO player_aliases (source, external_key, player_id, confidence) "
    "SELECT :source, r.external_key, r.player_id, r.confidence "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r("
    "external_key text, player_id text, confidence numeric) "
    "ON CONFLICT (source, external_key) DO UPDATE SET player_id = EXCLUDED.player_id, "
    "confidence = EXCLUDED.confidence"
)

SQL_RAW = text(
    "INSERT INTO raw_snapshots (source, endpoint, params, payload) "
    "SELECT :source, r.endpoint, r.params, r.payload "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(endpoint text, params jsonb, payload jsonb)"
)


def load_api_players(conn: Connection) -> tuple[list[ApiPlayer], dict[str, str]]:
    players = [
        ApiPlayer(*row)
        for row in conn.execute(
            text("SELECT player_id, name, COALESCE(nickname, ''), position_id, team_id FROM players")
        ).all()
    ]
    clubs = dict(conn.execute(text("SELECT team_id, name FROM teams")).all())
    return players, clubs


def backfill(
    conn: Connection, *, concurrency: int = 4, dry_run: bool = False, today: date | None = None
) -> dict:
    today = today or datetime.now(UTC).date()
    html = fetch_market_html()
    rows = parse_market(html)
    ff_teams = parse_market_teams(html)
    api_players, clubs = load_api_players(conn)
    club_map = match_clubs(ff_teams, clubs)
    matches, unmatched = match_players(rows, api_players, club_map)
    summary: dict[str, Any] = {
        "ff_players": len(rows),
        "clubs_matched": f"{len(club_map)}/{len(ff_teams)}",
        "clubs_unmatched": [ff_teams[k] for k in ff_teams if k not in club_map],
        "players_matched": len(matches),
        "players_unmatched": [f"{r.name} ({r.position}, {ff_teams.get(r.ff_team_id)})" for r in unmatched],
        "low_confidence": sorted(
            (
                f"{r.name} -> {matches[r.ff_id][0]} ({matches[r.ff_id][1]})"
                for r in rows
                if r.ff_id in matches and matches[r.ff_id][1] < 0.9
            ),
        ),
    }
    if dry_run:
        return summary

    conn.execute(
        SQL_ALIASES,
        {
            "source": SOURCE,
            "rows": json.dumps(
                [{"external_key": k, "player_id": pid, "confidence": c} for k, (pid, c) in matches.items()]
            ),
        },
    )
    done = set(
        conn.execute(
            text(
                "SELECT params->>'ff_id' FROM raw_snapshots "
                "WHERE source = :s AND CAST(fetched_at AS date) = CURRENT_DATE"
            ),
            {"s": SOURCE},
        ).scalars()
    )
    to_fetch = [k for k in matches if k not in done]  # reanuda: no repite lo ya guardado hoy
    pages = asyncio.run(fetch_details(to_fetch, concurrency=concurrency))
    value_rows: list[dict] = []
    raw_rows: list[dict] = []
    empty: list[str] = []
    for ff_id in to_fetch:
        pid = matches[ff_id][0]
        series = parse_detail(pages.get(ff_id, ""), today)
        if not series:
            empty.append(ff_id)
            continue
        value_rows.extend({"player_id": pid, "day": d.isoformat(), "market_value": v} for d, v in series)
        raw_rows.append(
            {
                "endpoint": DETAIL_URL.format(ff_id=ff_id),
                "params": {"ff_id": ff_id, "player_id": pid},
                "payload": {"series": [[d.isoformat(), v] for d, v in series]},
            }
        )
    if raw_rows:
        conn.execute(SQL_RAW, {"source": SOURCE, "rows": json.dumps(raw_rows)})
    inserted = 0
    if value_rows:
        inserted = conn.execute(SQL_VALUES, {"source": VALUE_SOURCE, "rows": json.dumps(value_rows)}).rowcount
    summary.update(
        {
            "series_skipped_already_fetched": len(done),
            "series_fetched": len(raw_rows),
            "series_empty": empty[:10],
            "series_empty_total": len(empty),
            "value_points": len(value_rows),
            "value_rows_inserted": inserted,
            "first_day": min((r["day"] for r in value_rows), default=None),
        }
    )
    return summary


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m lfm.sources.futbolfantasy")
    ap.add_argument("cmd", choices=["backfill"])
    ap.add_argument("--dry-run", action="store_true", help="solo casar jugadores; no descarga ni escribe")
    ap.add_argument("--concurrency", type=int, default=3)
    a = ap.parse_args(argv[1:])
    from lfm.db.session import engine

    with engine().begin() as conn:
        summary = backfill(conn, concurrency=a.concurrency, dry_run=a.dry_run)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
