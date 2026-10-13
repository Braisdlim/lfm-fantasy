"""Alineaciones probables y disponibilidad, de FútbolFantasy.

Es el factor que más pesa y que la API oficial no da: **un jugador de 6 puntos esperados que solo
sale el 60 % de las veces vale 3,6**. Sin esto, cualquier recomendación sobrevalora a los suplentes.

Verificado el 2026-09-08 en `/laliga/equipos/{slug}`: cada jugador es un `<a class="camiseta">` con
sus datos en atributos, y el nombre visible justo detrás del enlace. Lo que usamos:

    data-probabilidad          "90%"  probabilidad de ser titular
    data-lesion                "-1" sano, >= 0 lesionado
    data-sancionado            "1" cumple sanción
    data-apercibido            "1" a una amarilla de sanción
    data-nodisponible          "1" no disponible por otro motivo
    data-totalMinutosJugados   minutos de la temporada
    data-totalPartidosJugados  partidos jugados
    data-valor-laliga-fantasy  su valor en LaLiga Fantasy, que sirve para casarlo sin ambigüedad
    href                       .../jugadores/<slug>
    data-bpp data-bpc          balón parado: penaltis y córners
    data-bpfd data-bpfc        balón parado: falta directa y falta colgada al área

Y desde el 2026-09-16, los **componentes de la temporada**, que estaban en la misma página y no se
leían (`player_season_stats`):

    data-totalGoles data-totalAsistencias
    data-totalAmarillas data-totalRojas
    data-totalPartidosJugadosSuplente  partidos en los que entró desde el banquillo
    data-totalPartidosSustituido       partidos en los que salió antes del final
    data-jerarquia             0-100, el peso del jugador en su equipo según la fuente
    data-forma_value

Con `jugados − suplente` sale cuántas veces ha sido **titular**, que es el dato que la
probabilidad de titular por sí sola no da.

No se lee `data-rival_dif_index` (la dificultad del próximo rival según ellos): ya tenemos la
nuestra, medida con el modelo Poisson de `analysis/fixtures.py`, y meter un índice ajeno sin saber
cómo se calcula sería cambiar un número medido por uno opaco.

El casado con nuestro `player_id` se hace **por valor exacto** (los valores son cifras de siete
dígitos, así que la coincidencia es prácticamente única) y, si falla, por nombre normalizado.

Uso: `python -m lfm.sources.lineups` (recoge los 20 equipos y guarda en `player_availability`).
"""

from __future__ import annotations

import asyncio
import html as html_mod
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from urllib.parse import urlsplit

import httpx
from sqlalchemy import text
from sqlalchemy.engine import Connection

from lfm.db.raw_payload import store_html
from lfm.sources.futbolfantasy import HEADERS, norm

TEAM_URL = "https://www.futbolfantasy.com/laliga/equipos/{slug}"
SOURCE = "futbolfantasy_lineups"
REFRESH_HOURS = 6

# Los 20 slugs confirmados en la página de mercado el 2026-09-08
SLUGS = (
    "alaves",
    "athletic",
    "atletico",
    "barcelona",
    "betis",
    "celta",
    "deportivo",
    "elche",
    "espanyol",
    "getafe",
    "levante",
    "malaga",
    "osasuna",
    "racing",
    "rayo-vallecano",
    "real-madrid",
    "real-sociedad",
    "sevilla",
    "valencia",
    "villarreal",
)

# La página guarda a cada jugador en tres sitios y **no siempre con los mismos datos**:
#
#   div.tipo_lista   la ficha completa: probabilidad, valor, minutos, lesión, sanción. Uno por
#                    jugador de la plantilla, y comprobado el 2026-09-09 que **nunca le falta**
#                    ni la probabilidad ni el valor. Es la fuente buena.
#   a.camiseta       el once sobre el campo. A veces repite los atributos y a veces solo trae
#                    `data-lesion`: por eso leerlos solos dejaba sin probabilidad a titulares
#                    claros (Bartra, Arda Güler, Gudelj, Belocian).
#   a.juggador       la lista lateral, con el nombre visible.
#
# Se leen los tres y se fusiona por slug quedándose con la entrada más informada.
_LIST_DIV = re.compile(r'<div class="jugador_\d+ jugador tipo_lista([^>]*)>', re.S)
_NAME_SPAN = re.compile(r'<span class="nombre">([^<]{2,60})</span>')
_NAME_WINDOW = 3000  # el nombre visible aparece ~1,7 kB después de la ficha
_ANCHOR = re.compile(r'<a class="(?:camiseta|juggador)[^"]*"([^>]*)>(.*?)</a>\s*([^<]{0,40})', re.S)
_ALT = re.compile(r'alt="([^"]{2,40})"')
_ATTR = re.compile(r'([a-zA-Z0-9\-_]+)="([^"]*)"')


@dataclass
class Availability:
    slug: str
    name: str
    start_prob: float | None  # 0..1
    injured: bool
    suspended: bool
    booking_risk: bool  # a una amarilla de sanción
    unavailable: bool
    minutes: int | None
    games: int | None
    value: int | None  # su valor en LaLiga Fantasy, para casarlo
    set_pieces: dict[str, int] = field(default_factory=dict)  # temporada; ver `_set_pieces`
    season: dict[str, int | float] = field(default_factory=dict)  # temporada; ver `_season`


def _int(v: str | None) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except ValueError:
        return None


# Los cuatro atributos de balón parado empaquetan dos cifras en un entero: el sitio los usa para
# ordenar la tabla por esa columna, y con un solo número le vale. La fórmula es
#
#     valor = (aciertos + 1) * 1000 + intentos
#
# y el `+ 1` es lo que hace que el valor por defecto sea 1000 y no 0. Comprobado el 2026-09-09
# contra `/analytics/{equipo}/balon-parado`, que publica las dos cifras en texto:
# Unai López 6/16 córners = 7016, Rubén García 6/9 = 7009, Sergio Gómez 0/13 = 1013,
# Budimir 3/3 penaltis = 4003. Los córners cuentan solo los colgados; los sacados en corto
# la web los lleva aparte y no están en estos atributos.
_SET_PIECES = {
    "data-bpp": ("pen_scored", "pen_taken"),
    "data-bpc": ("corner_accurate", "corner_taken"),
    "data-bpfd": ("fk_on_target", "fk_taken"),
    "data-bpfc": ("cross_accurate", "cross_taken"),
}


def _set_pieces(attrs: dict[str, str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for attr, (aciertos, intentos) in _SET_PIECES.items():
        bruto = _int(attrs.get(attr))
        if bruto is None or bruto < 1000:
            continue
        out[aciertos], out[intentos] = divmod(bruto, 1000)
        out[aciertos] -= 1
    return out


# Los componentes de la temporada. Enteros salvo la forma, que viene con un decimal.
_SEASON = {
    "goals": "data-totalgoles",
    "assists": "data-totalasistencias",
    "yellows": "data-totalamarillas",
    "reds": "data-totalrojas",
    "games": "data-totalpartidosjugados",
    "games_as_sub": "data-totalpartidosjugadossuplente",
    "games_subbed_off": "data-totalpartidossustituido",
    "minutes": "data-totalminutosjugados",
    "hierarchy": "data-jerarquia",
}


def _float(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def _season(attrs: dict[str, str]) -> dict[str, int | float]:
    """Solo lo que la página trae de verdad: un campo ausente se omite, no se cuenta como cero.

    La distinción importa porque estas cifras se fusionan entre las tres apariciones del jugador en
    la página (ver `parse_team`), y un cero inventado ganaría a un dato bueno."""
    out: dict[str, int | float] = {}
    for col, attr in _SEASON.items():
        v = _int(attrs.get(attr))
        if v is not None:
            out[col] = v
    forma = _float(attrs.get("data-forma_value"))
    if forma is not None:
        out["form"] = forma
    return out


def _row(attrs: dict[str, str], slug: str, name: str) -> Availability:
    prob = attrs.get("data-probabilidad")
    pct = _int(prob.rstrip("%")) if prob else None
    lesion = _int(attrs.get("data-lesion"))
    return Availability(
        slug=slug,
        name=name or slug.replace("-", " "),
        # La fuente limita las previsiones al 99 %. Un 100 puede representar
        # un once confirmado; sin partido asociado no es previsión de la próxima jornada.
        start_prob=pct / 100 if pct is not None and 0 <= pct < 100 else None,
        injured=lesion is not None and lesion >= 0,
        # `data-sancionado` es el número de partidos de sanción, no un sí/no: el 2026-09-09 había
        # trece jugadores con "1" y dos con "3", y compararlo con "1" dejaba fuera a esos dos.
        suspended=(_int(attrs.get("data-sancionado")) or 0) > 0,
        # `data-apercibido` viene siempre a cero en las 20 páginas: el sitio no lo rellena, así que
        # no se puede avisar de quién está a una amarilla de sanción con esta fuente.
        booking_risk=(_int(attrs.get("data-apercibido")) or 0) > 0,
        unavailable=(_int(attrs.get("data-nodisponible")) or 0) > 0,
        minutes=_int(attrs.get("data-totalminutosjugados")),
        games=_int(attrs.get("data-totalpartidosjugados")),
        value=_int(attrs.get("data-valor-laliga-fantasy")),
        set_pieces=_set_pieces(attrs),
        season=_season(attrs),
    )


def _score(r: Availability) -> tuple[int, int, int, int]:
    """Cuánto sabemos de una entrada, para quedarnos con la mejor de las repetidas."""
    return (r.start_prob is not None, r.value is not None, len(r.set_pieces), len(r.season))


def parse_team(html: str) -> list[Availability]:
    """Un jugador por slug, fusionando las tres formas en que la página lo repite.

    Se recorre primero la ficha completa (`div.tipo_lista`) y después los enlaces, y de cada slug
    se guarda la entrada que trae más datos. Así un titular cuya camiseta solo lleva la lesión
    conserva la probabilidad y el valor que sí están en su ficha."""
    best: dict[str, Availability] = {}

    def offer(row: Availability) -> None:
        prev = best.get(row.slug)
        if prev is None or _score(row) > _score(prev):
            best[row.slug] = row

    for m in _LIST_DIV.finditer(html):
        a = {k.lower(): v for k, v in _ATTR.findall(m.group(1))}
        slug = a.get("data-nombre", "")
        if not slug:
            continue
        nom = _NAME_SPAN.search(html, m.end(), m.end() + _NAME_WINDOW)
        offer(_row(a, slug, html_mod.unescape(nom.group(1)).strip() if nom else ""))

    for attrs_raw, inner, after in _ANCHOR.findall(html):
        a = {k.lower(): v for k, v in _ATTR.findall(attrs_raw)}
        href = a.get("href", "")
        path = urlsplit(html_mod.unescape(href)).path
        match_slug = re.fullmatch(r"/jugadores/([^/]+)(?:/[^/]+)?/?", path)
        slug = match_slug.group(1) if match_slug else ""
        if not slug:
            continue
        alt = _ALT.search(inner)
        name = html_mod.unescape(after).strip() or (html_mod.unescape(alt.group(1)) if alt else "")
        offer(_row(a, slug, name))
    return list(best.values())


async def fetch_all(slugs=SLUGS, *, concurrency: int = 3) -> dict[str, str]:
    """HTML de cada equipo, al mismo ritmo que respeta el resto del scraper."""
    urls = {s: TEAM_URL.format(slug=s) for s in slugs}
    sem = asyncio.Semaphore(concurrency)
    out: dict[str, str] = {}

    async def one(client: httpx.AsyncClient, slug: str) -> None:
        async with sem:
            try:
                r = await client.get(urls[slug])
                out[slug] = r.text if r.status_code == 200 else ""
            except httpx.TransportError:
                out[slug] = ""

    async with httpx.AsyncClient(headers=HEADERS, timeout=45, follow_redirects=True) as client:
        await asyncio.gather(*(one(client, s) for s in slugs))
    return out


SQL_VALUES_TODAY = text(
    "SELECT v.player_id, v.market_value::bigint AS value, p.name, p.nickname, p.team_id "
    "FROM player_value_daily v JOIN players p USING (player_id) "
    "WHERE v.day = (SELECT max(day) FROM player_value_daily WHERE source = 'laliga_api')"
)

SQL_SAVE = text(
    "INSERT INTO player_availability (player_id, day, start_prob, injured, suspended, booking_risk, "
    "minutes, games, source, fetched_at) "
    "SELECT r.player_id, CAST(:day AS date), r.start_prob, r.injured, r.suspended, r.booking_risk, "
    "r.minutes, r.games, :source, now() "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(player_id text, start_prob numeric, "
    "injured boolean, suspended boolean, booking_risk boolean, minutes int, games int) "
    "ON CONFLICT (player_id, day) DO UPDATE SET start_prob = EXCLUDED.start_prob, "
    "injured = EXCLUDED.injured, suspended = EXCLUDED.suspended, booking_risk = EXCLUDED.booking_risk, "
    "minutes = EXCLUDED.minutes, games = EXCLUDED.games, fetched_at = now()"
)


_SP_COLS = (
    "pen_scored",
    "pen_taken",
    "corner_accurate",
    "corner_taken",
    "fk_on_target",
    "fk_taken",
    "cross_accurate",
    "cross_taken",
)

SQL_SAVE_SET_PIECES = text(
    "INSERT INTO player_set_pieces (player_id, day, "
    + ", ".join(_SP_COLS)
    + ", source, fetched_at) SELECT r.player_id, CAST(:day AS date), "
    + ", ".join("r." + c for c in _SP_COLS)
    + ", :source, now() FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(player_id text, "
    + ", ".join(c + " int" for c in _SP_COLS)
    + ") ON CONFLICT (player_id, day) DO UPDATE SET "
    + ", ".join(f"{c} = EXCLUDED.{c}" for c in _SP_COLS)
    + ", fetched_at = now()"
)


_SEASON_COLS = tuple(_SEASON) + ("form",)

SQL_SAVE_SEASON = text(
    "INSERT INTO player_season_stats (player_id, day, "
    + ", ".join(_SEASON_COLS)
    + ", source, fetched_at) SELECT r.player_id, CAST(:day AS date), "
    + ", ".join("r." + c for c in _SEASON_COLS)
    + ", :source, now() FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(player_id text, "
    + ", ".join(c + (" numeric" if c == "form" else " int") for c in _SEASON_COLS)
    + ") ON CONFLICT (player_id, day) DO UPDATE SET "
    + ", ".join(f"{c} = EXCLUDED.{c}" for c in _SEASON_COLS)
    + ", fetched_at = now()"
)


_SP_TEAM_COLS = ("pen_taken", "corner_taken", "fk_taken", "cross_taken")

SQL_SAVE_TEAM_SET_PIECES = text(
    "INSERT INTO team_set_pieces (team_id, day, "
    + ", ".join(_SP_TEAM_COLS)
    + ", source, fetched_at) SELECT r.team_id, CAST(:day AS date), "
    + ", ".join("r." + c for c in _SP_TEAM_COLS)
    + ", :source, now() FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(team_id text, "
    + ", ".join(c + " int" for c in _SP_TEAM_COLS)
    + ") ON CONFLICT (team_id, day) DO UPDATE SET "
    + ", ".join(f"{c} = EXCLUDED.{c}" for c in _SP_TEAM_COLS)
    + ", fetched_at = now()"
)


VALUE_TOLERANCE = 0.02  # el valor de FútbolFantasy puede ir un día por detrás del nuestro
# Un casado por nombre no puede contradecir al valor. Los apellidos se repiten en la liga y casar
# por el apellido del slug atravesaba los veinte equipos: el 2026-09-09, 10 de los 487 alias
# apuntaban a otro jugador, y `vinicius-junior` (106 M) le estaba dando su probabilidad de titular
# a un "Junior" del Betis de 1,9 M. Con este margen los diez quedan descartados y ninguno de los
# 474 buenos se pierde: la desincronización real entre las dos fuentes es de cientos de euros.
NAME_VALUE_TOLERANCE = 0.25
VALUE_TOLERANCE_TIGHT = 0.001  # ...y, aun siendo del mismo día, difiere en unos cientos de euros


def plausible(value: int | None, player, tol: float = NAME_VALUE_TOLERANCE) -> bool:
    """Si las dos fuentes dan valores parecidos, el nombre puede decidir; si no, no."""
    if not value or not getattr(player, "value", None):
        return True  # sin valor con el que comparar no se puede desmentir a nadie
    return abs(player.value - value) <= player.value * tol


def _near(value: int | None, players: list, used: set[str], tol: float) -> list:
    """Los nuestros cuyo valor cae dentro de la tolerancia, sin los ya asignados."""
    if not value:
        return []
    return [p for p in players if p.player_id not in used and abs(p.value - value) <= value * tol]


def match(
    rows: list[Availability], players: list, known: dict[str, str] | None = None
) -> tuple[dict[str, str], list[Availability]]:
    """Availability → player_id, en tres pasadas de más fiable a menos:

    1. **Valor exacto**: son cifras de siete dígitos, la coincidencia es prácticamente única.
    2. **Nombre normalizado** (sin tildes ni mayúsculas), contra nombre completo y apodo.
    3. **Apellido del slug**, que viene sin tildes y rescata los que fallan por acentos
       (`alex-grimaldo` contra nuestro apodo `Grimaldo`). Las pasadas por nombre solo aceptan a
       quien además tenga un valor parecido: el apellido solo no distingue en una liga con veinte
       equipos, y sin esa condición `vinicius-junior` casaba con un "Junior" del Betis.
    4. **Valor aproximado** (±2 %), porque la página de equipos puede llevar el valor de ayer.

    Cada jugador nuestro se asigna una sola vez.

    **Antes que nada se aplican los casados ya conocidos** (`known`, de `player_aliases`). Sin eso
    el casado dependía de que las dos fuentes compartieran la foto de valores del día, y en cuanto
    se desincronizan se cae en picado: el 2026-09-09 pasó de 506 jugadores a 397 de un día para
    otro, y un quinto de la liga se quedó sin probabilidad de titular sin que nada fallara. Un slug
    de FútbolFantasy apunta siempre al mismo jugador, así que casarlo es trabajo de una sola vez."""
    out: dict[str, str] = {}
    used: set[str] = set()
    ids_validos = {p.player_id for p in players}
    for r in rows:
        pid = (known or {}).get(r.slug)
        if pid and pid in ids_validos and pid not in used:
            out[r.slug] = pid
            used.add(pid)
    rows = [r for r in rows if r.slug not in out]

    by_value: dict[int, list] = {}
    by_name: dict[str, list] = {}
    for p in players:
        by_value.setdefault(p.value, []).append(p)
        # un jugador puede tener el mismo nombre y apodo: sin el set se indexaría dos veces bajo
        # la misma clave y el candidato dejaría de ser único
        for key in {norm(p.nickname or p.name), norm(p.name)}:
            by_name.setdefault(key, []).append(p)
    pending = list(rows)

    def take(r: Availability, cand: list) -> bool:
        free = [p for p in cand if p.player_id not in used]
        if len(free) != 1:
            return False
        out[r.slug] = free[0].player_id
        used.add(free[0].player_id)
        return True

    pending = [r for r in pending if not take(r, by_value.get(r.value or -1, []))]
    # Casi exacto. FútbolFantasy publica el valor con unos cientos de euros de diferencia sobre el
    # nuestro (Bartra 412 €, Mikautadze 261 €, Nico Williams 760 € el 2026-09-09) porque lo capturan
    # en otro instante. El 8 coincidían al euro y el 9 ya no, y eso solo se llevó por delante 109
    # jugadores en un día. Una milésima es suficiente para que siga siendo único.
    pending = [r for r in pending if not take(r, _near(r.value, players, used, VALUE_TOLERANCE_TIGHT))]

    def por_nombre(clave: str):
        """Candidatos con ese nombre a los que el valor no desmienta."""
        return lambda r: [p for p in by_name.get(clave(r), []) if plausible(r.value, p)]

    pending = [r for r in pending if not take(r, por_nombre(lambda r: norm(r.name))(r))]
    # el slug viene sin tildes, así que rescata los que fallan por acentos: alex-grimaldo -> grimaldo
    pending = [r for r in pending if not take(r, por_nombre(lambda r: r.slug.rsplit("-", 1)[-1])(r))]
    pending = [r for r in pending if not take(r, por_nombre(lambda r: r.slug.replace("-", " "))(r))]
    resto = [p for p in players if p.player_id not in used]
    remaining = []
    for r in pending:
        if r.value:
            cerca = [p for p in resto if abs(p.value - r.value) <= r.value * VALUE_TOLERANCE]
            if take(r, cerca):
                continue
        remaining.append(r)
    return out, remaining


SQL_ALIASES = text("SELECT external_key, player_id FROM player_aliases WHERE source = :source")

SQL_SAVE_ALIASES = text(
    "INSERT INTO player_aliases (source, external_key, player_id, confidence) "
    "SELECT :source, r.external_key, r.player_id, 1 "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(external_key text, player_id text) "
    "ON CONFLICT (source, external_key) DO NOTHING"
)


def team_totals(por_pagina: dict[str, list[Availability]], ids: dict[str, str], players: list) -> list[dict]:
    """Balón parado sumado por equipo, con el equipo deducido por mayoría de sus jugadores.

    El slug de FútbolFantasy no es el nuestro (`athletic` frente a `athletic-club`), así que en vez
    de mantener un mapa a mano se mira a qué equipo pertenecen los jugadores ya casados de esa
    página: veintitantos jugadores del mismo club no dejan lugar a duda. Se suma **la página
    entera**, casada o no, porque es el denominador de "lanza el 80 % de los córners" y con solo
    los casados sale inflado."""
    equipo_de = {p.player_id: p.team_id for p in players}
    out = []
    for filas in por_pagina.values():
        votos: dict[str, int] = {}
        for r in filas:
            tid = equipo_de.get(ids.get(r.slug, ""))
            if tid:
                votos[tid] = votos.get(tid, 0) + 1
        if not votos:
            continue
        team_id = max(votos, key=votos.get)  # type: ignore[arg-type]
        total = {c: sum(r.set_pieces.get(c, 0) for r in filas) for c in _SP_TEAM_COLS}
        if any(total.values()):
            out.append({"team_id": team_id} | total)
    return out


def refresh_due(conn: Connection) -> bool:
    """Una lectura reciente del mercado no dice nada sobre la edad de las alineaciones."""
    return not bool(
        conn.execute(
            text(
                "SELECT count(*) >= 400 AND min(fetched_at) > now() - make_interval(hours => :hours) "
                "FROM player_availability WHERE day = (SELECT max(day) FROM player_availability)"
            ),
            {"hours": REFRESH_HOURS},
        ).scalar()
    )


def refresh(conn: Connection, *, day: date) -> dict:
    return collect(conn, day=day) if refresh_due(conn) else {"cached": True}


def collect(conn: Connection, *, day: date, pages: dict[str, str] | None = None) -> dict:
    pages = pages if pages is not None else asyncio.run(fetch_all())
    if not pages or any(not h for h in pages.values()):
        raise ValueError("Recogida de titularidades incompleta: se conserva la foto anterior")
    # Guardar las respuestas permite revisar errores de extracción sin repetir la descarga.
    for slug, html in pages.items():
        conn.execute(
            text(
                "INSERT INTO raw_snapshots (source, endpoint, payload) "
                "VALUES (:source, :endpoint, CAST(:payload AS jsonb))"
            ),
            {
                "source": SOURCE,
                "endpoint": TEAM_URL.format(slug=slug),
                "payload": json.dumps(store_html(conn, html)),
            },
        )
    por_pagina = {slug: parse_team(html) for slug, html in pages.items() if html}
    if any(len(rows) < 11 for rows in por_pagina.values()):
        raise ValueError("HTML de titularidades incompleto o desconocido: se conserva la foto anterior")
    rows: list[Availability] = [r for filas in por_pagina.values() for r in filas]
    # Un jugador puede aparecer en dos páginas durante un traspaso. No adivinar
    # cuál está actualizada ni mandar dos escrituras para la misma clave.
    if len({r.slug for r in rows}) != len(rows):
        raise ValueError("Jugadores duplicados entre equipos: revisar la fuente antes de guardar")
    players = conn.execute(SQL_VALUES_TODAY).all()
    known = {k: v for k, v in conn.execute(SQL_ALIASES, {"source": SOURCE})}
    ids, missed = match(rows, players, known=known)
    if len(ids) < len(rows) * 0.8:
        raise ValueError("Menos del 80 % de jugadores identificados: se conserva la foto anterior")
    nuevos = [{"external_key": s, "player_id": p} for s, p in ids.items() if s not in known]
    if nuevos:
        conn.execute(SQL_SAVE_ALIASES, {"source": SOURCE, "rows": json.dumps(nuevos)})
    fuera = ("slug", "name", "value", "set_pieces", "season")
    payload = [
        {k: v for k, v in asdict(r).items() if k not in fuera} | {"player_id": ids[r.slug]}
        for r in rows
        if r.slug in ids
    ]
    if payload:
        conn.execute(SQL_SAVE, {"day": day.isoformat(), "source": SOURCE, "rows": json.dumps(payload)})
    # El balón parado es acumulado de temporada y llega a cero para casi todos: solo se guarda a
    # quien ha lanzado algo, que son ~100 de 500 y son los únicos de los que hay algo que decir.
    balon = [
        {"player_id": ids[r.slug]} | {c: r.set_pieces.get(c, 0) for c in _SP_COLS}
        for r in rows
        if r.slug in ids and any(r.set_pieces.get(c) for c in _SP_COLS)
    ]
    if balon:
        conn.execute(
            SQL_SAVE_SET_PIECES,
            {"day": day.isoformat(), "source": SOURCE, "rows": json.dumps(balon)},
        )
    # Los componentes de la temporada sí se guardan de todos, incluso a cero: un delantero con cero
    # goles en seis jornadas es información, no un hueco. Solo se exige que la página traiga algún
    # campo, para no escribir una fila entera de NULL de quien no aparece con datos.
    temporada = [
        {"player_id": ids[r.slug]} | {c: r.season.get(c) for c in _SEASON_COLS}
        for r in rows
        if r.slug in ids and r.season
    ]
    if temporada:
        conn.execute(
            SQL_SAVE_SEASON,
            {"day": day.isoformat(), "source": SOURCE, "rows": json.dumps(temporada)},
        )
    equipos = team_totals(por_pagina, ids, players)
    if equipos:
        conn.execute(
            SQL_SAVE_TEAM_SET_PIECES,
            {"day": day.isoformat(), "source": SOURCE, "rows": json.dumps(equipos)},
        )
    with_prob = sum(1 for r in rows if r.start_prob is not None)
    return {
        "teams": sum(1 for h in pages.values() if h),
        "players": len(rows),
        "with_start_prob": with_prob,
        "matched": len(ids),
        "reused_aliases": len(ids) - len(nuevos),
        "new_aliases": len(nuevos),
        "unmatched": [r.name for r in missed][:10],
        "injured": sum(1 for r in rows if r.injured),
        "booking_risk": sum(1 for r in rows if r.booking_risk),
        "set_pieces": len(balon),
        "set_pieces_teams": len(equipos),
        "season_stats": len(temporada),
    }


AUDIT_TOLERANCE = 0.05  # dos capturas del mismo día difieren en céntimos, no en millones


def audit(conn: Connection, pages: dict[str, str] | None = None) -> dict:
    """Comprueba que cada alias apunta de verdad a ese jugador, contrastando el valor de mercado.

    Es el contraste objetivo que existe: los dos sitios publican el valor del mismo jugador en
    LaLiga Fantasy, y si el alias es bueno coinciden salvo unos cientos de euros. Merece la pena
    poder repetirlo porque un alias malo **se queda grabado**: el 2026-09-09 había diez, todos de
    casar por el apellido del slug, y `vinicius-junior` le daba su probabilidad de titular a un
    "Junior" del Betis. Devuelve los sospechosos para poder borrarlos y dejar que se rehagan.
    """
    pages = pages if pages is not None else asyncio.run(fetch_all())
    fuente = {r.slug: r for html in pages.values() if html for r in parse_team(html)}
    alias = list(conn.execute(SQL_ALIASES, {"source": SOURCE}))
    nuestros = {p.player_id: p for p in conn.execute(SQL_VALUES_TODAY)}
    malos, sin_comprobar = [], 0
    for slug, pid in alias:
        f, n = fuente.get(slug), nuestros.get(pid)
        if not f or not n or not f.value or not n.value:
            sin_comprobar += 1
            continue
        dif = abs(f.value - n.value) / n.value
        if dif > AUDIT_TOLERANCE:
            malos.append(
                {
                    "slug": slug,
                    "player_id": pid,
                    "nickname": n.nickname,
                    "suyo": f.value,
                    "nuestro": n.value,
                    "veces": round(dif, 2),
                }
            )
    return {
        "total": len(alias),
        "sin_comprobar": sin_comprobar,
        "sospechosos": sorted(malos, key=lambda m: -m["veces"]),
    }


if __name__ == "__main__":  # pragma: no cover
    import sys
    from datetime import UTC, datetime

    from lfm.db.session import engine

    with engine().begin() as conn:
        if len(sys.argv) > 1 and sys.argv[1] == "audit":
            salida = audit(conn)
        else:
            salida = collect(conn, day=datetime.now(UTC).date())
        print(json.dumps(salida, indent=2, ensure_ascii=False))
