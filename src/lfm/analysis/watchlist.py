"""Lista de seguimiento: avisar cuando un jugador que te interesa se puede fichar a tu precio.

Revisar a mano todos los filtros del mercado y de las cláusulas cada día es justo lo que acaba por
no hacerse. Aquí guardas el jugador, lo máximo que pagarías y, si quieres, la titularidad mínima;
el job ligero comprueba cada pasada si se cumple y avisa **una sola vez por ocasión**:

- **Mercado**: está a la venta en el ciclo vigente (de la liga o de un manager) a tu precio o menos.
  El precio de un manager es orientativo: en esta liga se negocia y siempre piden más.
- **Cláusula**: tiene dueño en la liga, no eres tú, la cláusula está abierta y cabe en tu máximo.

Nada de esto predice: son hechos del mercado y de la fuente de titularidad, con su fecha. El
módulo solo lee y avisa; nunca puja ni clausula (regla 1 de CLAUDE.md).

`gather()` consulta, `evaluate()` decide con reglas puras y `compose()` redacta, separados para
probar las reglas y el texto sin base de datos.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.engine import Connection

from lfm.analysis.alerts import _falta, _fmt
from lfm.config import settings

APP_URL = settings.app_url.rstrip("/")

# Estados que no dejan fichar aunque el precio encaje.
BLOCKING_STATUS = {"injured": "lesionado", "suspended": "sancionado", "out_of_league": "fuera de LaLiga"}

SQL_GATHER = text(
    """
WITH d AS (SELECT max(day) AS day FROM player_value_daily WHERE source = 'laliga_api'),
cyc AS (SELECT max(cycle_end) AS c FROM market_offer
         WHERE league_id = :league_id AND kind = 'marketPlayerLeague'),
sq AS (
  SELECT sn.* FROM league_squad_daily sn
   WHERE sn.league_id = :league_id
     AND sn.day = (SELECT max(sm.day) FROM league_squad_daily sm
                    WHERE sm.league_id = sn.league_id AND sm.team_id = sn.team_id)
     AND NOT EXISTS (SELECT 1 FROM league_squad_daily sx
                      WHERE sx.league_id = sn.league_id AND sx.player_id = sn.player_id
                        AND sx.day > sn.day))
SELECT w.player_id, COALESCE(p.nickname, p.name) AS name,
       w.max_price::float8 AS max_price, w.min_start_prob::float8 AS min_start_prob,
       w.watch_market, w.watch_clause, w.note,
       v.market_value::float8 AS value, v.status,
       CASE WHEN a.fetched_at >= now() - interval '26 hours'
             AND a.start_prob >= 0 AND a.start_prob < 1 THEN a.start_prob::float8 END AS start_prob,
       a.injured, a.suspended,
       m.sale_price::float8 AS sale_price, m.kind AS market_kind, m.expires_at,
       ltm.manager_name AS seller, COALESCE(ltm.is_me, false) AS seller_is_me,
       cyc.c AS cycle_end,
       sq.team_id AS owner_team, lto.manager_name AS owner, COALESCE(lto.is_me, false) AS owner_is_me,
       sq.buyout_clause::float8 AS buyout_clause, sq.clause_locked_until, sq.is_shielded
  FROM watchlist w
  JOIN players p ON p.player_id = w.player_id
  CROSS JOIN d CROSS JOIN cyc
  LEFT JOIN player_value_daily v ON v.player_id = w.player_id AND v.day = d.day
  LEFT JOIN LATERAL (SELECT * FROM player_availability pa WHERE pa.player_id = w.player_id
                      ORDER BY pa.day DESC LIMIT 1) a ON true
  LEFT JOIN market_offer m ON m.league_id = :league_id AND m.cycle_end = cyc.c
        AND m.player_id = w.player_id AND (m.expires_at IS NULL OR m.expires_at > now())
  LEFT JOIN league_teams ltm ON ltm.league_id = :league_id AND ltm.team_id = m.owner_team_id
  LEFT JOIN sq ON sq.player_id = w.player_id
  LEFT JOIN league_teams lto ON lto.league_id = :league_id AND lto.team_id = sq.team_id
 ORDER BY w.created_at
"""
)

SQL_MY_CASH = text(
    "SELECT COALESCE(lt.team_money, (SELECT s.team_money FROM league_standing_daily s "
    "WHERE s.league_id = lt.league_id AND s.team_id = lt.team_id AND s.team_money IS NOT NULL "
    "ORDER BY s.day DESC LIMIT 1))::float8 FROM league_teams lt "
    "WHERE lt.league_id = :league_id AND lt.is_me LIMIT 1"
)

SQL_SAVE_STATE = text(
    "UPDATE watchlist SET state = :state, detail = CAST(:detail AS jsonb), checked_at = now() "
    "WHERE player_id = :player_id"
)

SQL_SENT = text("SELECT dedupe_key FROM alerts WHERE dedupe_key = ANY(:keys)")

SQL_SAVE_ALERT = text(
    "INSERT INTO alerts (kind, dedupe_key, payload, sent_at) "
    "VALUES ('watchlist', :key, CAST(:payload AS jsonb), now()) ON CONFLICT (dedupe_key) DO NOTHING"
)


@dataclass
class Watched:
    player_id: str
    name: str
    max_price: float | None = None
    min_start_prob: float | None = None
    watch_market: bool = True
    watch_clause: bool = True
    note: str | None = None
    value: float | None = None
    status: str | None = None
    start_prob: float | None = None
    injured: bool | None = None
    suspended: bool | None = None
    sale_price: float | None = None
    market_kind: str | None = None
    expires_at: datetime | None = None
    seller: str | None = None
    seller_is_me: bool = False
    cycle_end: datetime | None = None
    owner_team: str | None = None
    owner: str | None = None
    owner_is_me: bool = False
    buyout_clause: float | None = None
    clause_locked_until: datetime | None = None
    is_shielded: bool | None = None


@dataclass
class Hit:
    kind: str  # mercado | clausula
    price: float
    key: str  # clave de deduplicación: una ocasión, un aviso
    text: str
    # El plazo va aparte: la web lo pinta como cuenta atrás; guardarlo en el texto lo dejaría viejo.
    closes: datetime | None = None


@dataclass
class Verdict:
    player_id: str
    name: str
    state: str  # cumple | espera | bloqueado | tuyo
    hits: list[Hit] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)  # por qué no (o qué falta)
    start_prob: float | None = None
    value: float | None = None

    def detail(self) -> dict:
        return {
            "reasons": self.reasons,
            "hits": [
                {
                    "kind": h.kind,
                    "price": h.price,
                    "text": h.text,
                    "closes": h.closes.isoformat() if h.closes else None,
                }
                for h in self.hits
            ],
            "start_prob": self.start_prob,
            "value": self.value,
        }


def _pct(p: float) -> str:
    return f"{round(p * 100)} %"


def _iso(t: datetime | None) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M") if t else "-"


def _hora(t: datetime) -> str:
    from lfm.valueday import MADRID

    return t.astimezone(MADRID).strftime("%d/%m %H:%M")


def evaluate(w: Watched, *, now: datetime) -> Verdict:
    """Reglas puras: ¿se puede fichar hoy a tu precio y con la titularidad que pediste?"""
    v = Verdict(w.player_id, w.name, "espera", start_prob=w.start_prob, value=w.value)

    if w.owner_is_me or w.seller_is_me:
        v.state = "tuyo"
        v.reasons.append("Ya es tuyo.")
        return v

    bloqueo = None
    if w.injured:
        bloqueo = "lesionado"
    elif w.suspended:
        bloqueo = "sancionado"
    elif w.status in BLOCKING_STATUS:
        bloqueo = BLOCKING_STATUS[w.status]
    if bloqueo:
        v.state = "bloqueado"
        v.reasons.append(f"Ahora está {bloqueo}: no avisa hasta que vuelva.")
        return v

    titular_ok = True
    if w.min_start_prob is not None:
        if w.start_prob is None:
            titular_ok = False
            v.reasons.append("Sin previsión de titularidad vigente (FútbolFantasy, menos de 26 h).")
        elif w.start_prob < w.min_start_prob:
            titular_ok = False
            v.reasons.append(
                f"Titular estimado {_pct(w.start_prob)}; pediste al menos {_pct(w.min_start_prob)}."
            )

    tope = w.max_price
    tope_txt = f" · tu máximo {_fmt(tope)}" if tope is not None else ""

    candidatos: list[Hit] = []
    if w.watch_market and w.sale_price is not None:
        if tope is None or w.sale_price <= tope:
            if w.market_kind == "marketPlayerTeam" and w.seller:
                quien = f"lo vende {w.seller} por {_fmt(w.sale_price)}, precio orientativo que se negocia"
            else:
                quien = f"en el mercado de la liga desde {_fmt(w.sale_price)}"
            candidatos.append(
                Hit(
                    "mercado",
                    w.sale_price,
                    f"watch:m:{w.player_id}:{_iso(w.cycle_end)}:{int(w.sale_price)}",
                    quien + tope_txt,
                    closes=w.expires_at,
                )
            )
        else:
            v.reasons.append(f"En el mercado a {_fmt(w.sale_price)}, por encima de tu máximo {_fmt(tope)}.")

    if w.watch_clause and w.owner_team and w.buyout_clause is not None:
        bloqueada = w.clause_locked_until is not None and w.clause_locked_until > now
        if w.is_shielded:
            v.reasons.append(f"{w.owner or 'Su dueño'} tiene la cláusula blindada.")
        elif bloqueada:
            v.reasons.append(
                f"Cláusula de {_fmt(w.buyout_clause)} bloqueada hasta el {_hora(w.clause_locked_until)}."
            )
        elif tope is None or w.buyout_clause <= tope:
            candidatos.append(
                Hit(
                    "clausula",
                    w.buyout_clause,
                    f"watch:c:{w.player_id}:{w.owner_team}:{int(w.buyout_clause)}",
                    f"cláusula abierta de {_fmt(w.buyout_clause)} (de {w.owner or 'un rival'}){tope_txt}",
                )
            )
        else:
            quien = w.owner or "rival"
            v.reasons.append(
                f"Cláusula de {_fmt(w.buyout_clause)} ({quien}), por encima de tu máximo {_fmt(tope)}."
            )

    if w.sale_price is None and not w.owner_team:
        v.reasons.append("No está en el mercado ni tiene dueño en tu liga.")

    if candidatos and titular_ok:
        v.state = "cumple"
        v.hits = candidatos
    elif candidatos:
        # El precio encaja pero falta la titularidad: se dice qué hay para que la web lo enseñe.
        v.reasons.extend(f"Precio a tiro: {h.text}." for h in candidatos)
    return v


def compose(
    new_hits: list[tuple[Verdict, Hit]], *, cash: float | None, now: datetime | None = None
) -> str | None:
    """Un solo mensaje con las ocasiones nuevas. None si no hay nada que contar."""
    if not new_hits:
        return None
    lineas = ["👀 <b>Lista de seguimiento</b>"]
    for v, h in new_hits:
        extra = []
        cierra = _falta(h.closes, now or datetime.now(UTC))
        if cierra:
            extra.append(f"cierra en {cierra}")
        if v.start_prob is not None:
            extra.append(f"titular {_pct(v.start_prob)}")
        if v.value is not None:
            extra.append(f"vale {_fmt(v.value)}")
        if cash is not None and h.price > cash:
            extra.append(f"te faltan {_fmt(h.price - cash)}")
        cola = f" · {' · '.join(extra)}" if extra else ""
        name = f"<b>{v.name}</b>"
        if APP_URL:
            name = f'<a href="{APP_URL}/jugador/{v.player_id}">{name}</a>'
        lineas.append(f"• {name}: {h.text}{cola}")
    lineas.append("Solo aviso: la puja o la cláusula las haces tú.")
    return "\n".join(lineas)


def gather(conn: Connection, *, league_id: str) -> tuple[list[Watched], float | None]:
    rows = conn.execute(SQL_GATHER, {"league_id": league_id}).mappings().all()
    cash = conn.execute(SQL_MY_CASH, {"league_id": league_id}).scalar()
    return [Watched(**dict(r)) for r in rows], cash


def check(conn: Connection, *, league_id: str, send, now: datetime | None = None) -> dict:
    """Evalúa la lista, guarda el estado de cada jugador y avisa de las ocasiones nuevas.

    Solo se marca una ocasión como avisada si Telegram la aceptó: si falla el envío, la siguiente
    pasada lo vuelve a intentar en vez de perderla."""
    if conn.execute(text("SELECT to_regclass('watchlist') IS NOT NULL")).scalar() is not True:
        return {"skipped": "sin tabla watchlist (falta migrar)"}
    now = now or datetime.now(UTC)
    watched, cash = gather(conn, league_id=league_id)
    verdicts = [evaluate(w, now=now) for w in watched]
    for v in verdicts:
        conn.execute(
            SQL_SAVE_STATE,
            {
                "state": v.state,
                "detail": json.dumps(v.detail(), ensure_ascii=False),
                "player_id": v.player_id,
            },
        )
    hits = [(v, h) for v in verdicts for h in v.hits]
    if not hits:
        return {"watched": len(verdicts), "hits": 0, "sent": 0}
    ya = set(conn.execute(SQL_SENT, {"keys": [h.key for _, h in hits]}).scalars().all())
    nuevos = [(v, h) for v, h in hits if h.key not in ya]
    msg = compose(nuevos, cash=cash, now=now)
    enviado = bool(msg) and send(msg)
    if enviado:
        for v, h in nuevos:
            conn.execute(
                SQL_SAVE_ALERT,
                {
                    "key": h.key,
                    "payload": json.dumps({"player_id": v.player_id, "kind": h.kind, "price": h.price}),
                },
            )
    return {
        "watched": len(verdicts),
        "hits": len(hits),
        "new": len(nuevos),
        "sent": len(nuevos) if enviado else 0,
    }
