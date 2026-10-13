"""Avisos por Telegram: lo que hay que decidir antes del próximo cierre.

Un aviso en el móvil no es un informe. El mensaje anterior abría con «2º · 178 pts · plantilla
267,0 M», que no cambia ninguna decisión, y **no decía qué comprar**, que es lo mejor que sabe la
app. También llevaba un bloque «Puedes clausular» que el 2026-09-09 decía «3,6 M, vale 3,6 M» tres
veces seguidas: la cláusula es el valor, así que clausular no daba ninguna ventaja y el aviso solo
gastaba atención.

Criterio, entonces:

1. **Solo lo que se decide hoy.** El mercado cierra cada día y el once se bloquea al empezar la
   jornada. Lo que no caduca no va en un aviso: está en la app.
2. **Primero la acción, después el porqué**, y el porqué con la cifra que lo sostiene.
3. **Lo que no se sabe se dice.** Si un fichaje se apoya en puntos sin ajustar por titularidad,
   el aviso lo advierte en vez de vender la cifra como si fuera firme.
4. **Si no hay nada que hacer, se dice en una línea** y se acabó.

Reglas (CLAUDE.md 5): cada cifra la calcula el código, nunca un texto inventado. Este módulo solo
redacta lo que ya decidieron `analysis/recommend.py`, `analysis/eleven.py` y `analysis/cash.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Connection

from lfm.analysis import eleven as eleven_mod
from lfm.analysis import fixtures as fx_mod

CLAUSE_SOON_HOURS = 72
# Cuánto antes del primer partido empieza a avisar del once. Con menos de día y medio ya no da
# tiempo a fichar un recambio, así que el aviso tiene que llegar antes de eso.
LINEUP_WARNING_HOURS = 36
MAX_BUYS = 3  # en un móvil, más de tres opciones no se leen: el resto está en la app
MAX_RISKS = 3
# Por debajo de esta diferencia, cláusula y valor son el mismo número. Sin el umbral el aviso
# decía «se lo llevaría 0,0 M por debajo de su valor» por una diferencia de unos euros.
# Es el mismo criterio que usa la web (`AT_VALUE` en web/src/lib/format.ts).
AT_VALUE = 0.005


def missing_days(conn: Connection, *, day: date, back: int = 7) -> list[date]:
    """Días sin snapshot de la API en los últimos `back`, contando solo desde el primer snapshot
    (antes de esa fecha el histórico viene del backfill de FútbolFantasy, no del colector)."""
    rows = conn.execute(
        text(
            "SELECT DISTINCT day FROM player_value_daily "
            "WHERE source = 'laliga_api' AND day > CAST(:day AS date) - :back "
            "  AND day <= CAST(:day AS date)"
        ),
        {"day": day.isoformat(), "back": back},
    ).scalars()
    have = set(rows)
    if not have:
        return []
    first = min(have)
    return [d for i in range(back) if (d := day - timedelta(days=i)) >= first and d not in have]


def _fmt(n: object) -> str:
    """Millones en formato español. Acepta int, float y Decimal (lo que devuelve psycopg)."""
    if n is None:
        return "–"
    return f"{float(n) / 1e6:,.1f} M".replace(",", "·").replace(".", ",").replace("·", ".")


def _falta(cuando: datetime | None, ahora: datetime) -> str | None:
    """«3 h 12 min», «2 d 5 h». None si ya pasó o no se sabe."""
    if cuando is None:
        return None
    seg = (cuando - ahora).total_seconds()
    if seg <= 0:
        return None
    horas = seg / 3600
    if horas < 1:
        return f"{int(seg // 60)} min"
    if horas < 48:
        minutos = int((horas % 1) * 60)
        return f"{int(horas)} h {minutos} min" if minutos else f"{int(horas)} h"
    return f"{int(horas // 24)} d {int(horas % 24)} h"


# --- Lo que se lee de la base de datos ----------------------------------------------------------


@dataclass
class Buy:
    name: str
    bid: float | None
    club: str | None
    xpts: float | None
    start_prob: float | None
    verdict: str
    player_id: str | None = None
    resale: float | None = None  # lo que se espera recuperar revendiéndolo al sistema
    fixture: str | None = None  # etiqueta de calendario, por percentil de la jornada
    # Cuántos puntos por jornada le sumaría a tu once ficharlo. `None` si no se ha podido calcular.
    # Es la única vara que no necesita un umbral inventado: o entra en el once y suma, o no entra.
    improves: float | None = None
    reasons: list[dict] = field(default_factory=list)

    def reason(self, code: str) -> str | None:
        for r in self.reasons:
            if isinstance(r, dict) and r.get("code") == code:
                return r.get("text")
        return None


@dataclass
class Snapshot:
    day: date
    now: datetime
    cash: float | None
    market_closes: datetime | None
    week_opens: datetime | None
    week: int | None
    buys: list[Buy] = field(default_factory=list)
    sells: list[Buy] = field(default_factory=list)
    risks: list[dict] = field(default_factory=list)
    lineup_problems: list[str] = field(default_factory=list)
    lineup_changes: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # lo que falta para poder alinear once


SQL_ME = text(
    "SELECT lt.team_id, COALESCE(lt.team_money, s.team_money) AS team_money FROM league_teams lt "
    "JOIN league_standing_daily s ON s.league_id = lt.league_id AND s.team_id = lt.team_id "
    "WHERE lt.league_id = :league_id AND lt.is_me AND s.day = CAST(:day AS date)"
)

SQL_RECS = text(
    "SELECT r.kind, r.subject->>'name' AS name, r.subject->>'verdict' AS verdict, "
    "       (r.subject->>'bid_to_win')::float8 AS bid, r.subject->>'club_name' AS club, "
    "       (r.subject->>'xpts')::float8 AS xpts, (r.subject->>'start_prob')::float8 AS start_prob, "
    "       r.subject->>'fixture_label' AS fixture, r.subject->>'player_id' AS player_id, "
    "       (r.subject->>'expected_resale')::float8 AS resale, r.reasons "
    "FROM recommendations r "
    "WHERE r.created_at = (SELECT max(created_at) FROM recommendations) "
    "ORDER BY r.score DESC"
)

# El bloqueo del once y la jornada a preparar salen de la misma regla que usa el resto de la app
# (`analysis/fixtures.SQL_NEXT_WEEK`): la primera jornada cuyo once **todavía no se ha bloqueado**.
# Tomar «el primer partido pendiente» se quedaba corto: un aplazado con fecha pasada no cuenta, y
# los partidos que quedan de una jornada ya arrancada tampoco, porque su alineación está cerrada.
SQL_DEADLINES = text(
    "WITH proximo AS (" + str(fx_mod.SQL_NEXT_WEEK) + ") "
    "SELECT (SELECT max(cycle_end) FROM market_offer WHERE kind = 'marketPlayerLeague') AS market_closes, "
    "       (SELECT lock_at FROM proximo) AS week_opens, "
    "       (SELECT week FROM proximo) AS week"
)

SQL_RISK = text(
    "WITH c AS (SELECT * FROM manager_cash_estimate "
    "           WHERE league_id = :league_id AND day = (SELECT max(day) FROM manager_cash_estimate)) "
    "SELECT COALESCE(p.nickname, p.name) AS name, q.buyout_clause, "
    "       COALESCE(v.market_value, q.market_value) AS market_value, "
    "       (SELECT count(*) FROM c JOIN league_teams lt "
    "               ON lt.league_id = c.league_id AND lt.team_id = c.team_id "
    "         WHERE NOT lt.is_me AND c.cash_estimate >= q.buyout_clause) AS cuantos "
    "FROM league_squad_daily q JOIN players p ON p.player_id = q.player_id "
    "LEFT JOIN player_value_daily v ON v.player_id = q.player_id AND v.day = CAST(:day AS date) "
    "WHERE q.league_id = :league_id AND q.team_id = :team_id AND q.day = CAST(:day AS date) "
    "  AND NOT COALESCE(q.is_shielded, false) "
    "  AND (q.clause_locked_until IS NULL OR q.clause_locked_until < now() + make_interval(hours => :h)) "
    "ORDER BY q.buyout_clause DESC"
)

SQL_POSITIONS = text("SELECT player_id, position_id FROM players WHERE player_id = ANY(:ids)")

SQL_LINEUP = text(
    "SELECT COALESCE(p.nickname, p.name) AS name, l.chosen, l.current, l.xpts, "
    "       a.start_prob, a.injured, a.suspended "
    "FROM lineup_daily l JOIN players p ON p.player_id = l.player_id "
    "LEFT JOIN player_availability a ON a.player_id = l.player_id "
    "     AND a.day = (SELECT max(day) FROM player_availability) "
    "WHERE l.team_id = :team_id AND l.day = (SELECT max(day) FROM lineup_daily WHERE team_id = :team_id) "
    "AND l.formation IS NOT NULL"
)


def gather(conn: Connection, *, league_id: str, day: date, now: datetime | None = None) -> Snapshot | None:
    """Todo lo que el aviso puede necesitar, en una sola pasada. Sin redactar nada."""
    ahora = now or datetime.now(UTC)
    me = conn.execute(SQL_ME, {"league_id": league_id, "day": day.isoformat()}).first()
    if me is None:
        return None
    d = conn.execute(SQL_DEADLINES).first()

    # El mercado rota cada 24 h a la hora de la liga: si el último ciclo ya cerró, el próximo es
    # un día después. Sin esto el aviso daría una cuenta atrás en negativo.
    cierre = d.market_closes if d else None
    while cierre is not None and cierre <= ahora:
        cierre = cierre + timedelta(days=1)

    recs = conn.execute(SQL_RECS).all()

    def como_buy(r) -> Buy:
        return Buy(
            name=r.name or "?",
            bid=r.bid,
            club=r.club,
            xpts=r.xpts,
            start_prob=r.start_prob,
            verdict=r.verdict or "",
            player_id=r.player_id,
            resale=r.resale,
            fixture=r.fixture,
            reasons=list(r.reasons or []),
        )

    snap = Snapshot(
        day=day,
        now=ahora,
        cash=float(me.team_money) if me.team_money is not None else None,
        market_closes=cierre,
        week_opens=d.week_opens if d else None,
        week=d.week if d else None,
        buys=[como_buy(r) for r in recs if r.kind == "buy" and r.verdict == "pujar"],
        sells=[como_buy(r) for r in recs if r.kind == "sell" and r.verdict == "vender"],
    )

    # ¿Alguna de esas compras mejoraría tu once? Es la pregunta que decide si pujar o guardar el
    # saldo, y se responde recalculando el once con cada candidato dentro. Si algo falla —una
    # plantilla que no da para ningún dibujo, un candidato sin posición— se queda en None y el
    # aviso no dice nada, en vez de afirmar que no mejora.
    if snap.buys:
        try:
            mios = eleven_mod.picks_from(conn)
            posiciones = {
                r.player_id: r.position_id
                for r in conn.execute(SQL_POSITIONS, {"ids": [b.player_id for b in snap.buys if b.player_id]})
            }
            for b in snap.buys:
                pos = posiciones.get(b.player_id or "")
                if pos is None or b.xpts is None:
                    continue
                b.improves = eleven_mod.improvement(
                    mios, eleven_mod.Pick(b.player_id or "", b.name, pos, b.xpts)
                )
        except Exception:  # noqa: BLE001
            pass

    riesgo = conn.execute(
        SQL_RISK,
        {"league_id": league_id, "day": day.isoformat(), "team_id": me.team_id, "h": CLAUSE_SOON_HOURS},
    ).all()
    # Ordenado por lo expuesto que estás, no por lo cara que es la cláusula: un jugador cuya
    # cláusula es su valor exacto se lo llevan sin penalización, y uno con 6,5 M de sobrecoste
    # está protegido aunque su cláusula sea mayor.
    snap.risks = sorted(
        (
            {
                "name": r.name,
                "clause": float(r.buyout_clause or 0),
                "value": float(r.market_value or 0),
                "cuantos": r.cuantos,
            }
            for r in riesgo
            if r.cuantos
        ),
        key=lambda r: (r["clause"] - r["value"], -r["cuantos"]),
    )

    # Si la plantilla no da para un once válido no hay nada que optimizar: hay que fichar. Es el
    # caso del 2026-09-16, sin portero, donde la app decía «todavía no hay once calculado».
    try:
        snap.missing = eleven_mod.missing_for_eleven(eleven_mod.picks_from(conn))
    except Exception:  # noqa: BLE001
        pass

    for r in conn.execute(SQL_LINEUP, {"team_id": me.team_id}):
        if r.chosen and (r.injured or r.suspended):
            snap.lineup_problems.append(f"{r.name} está {'lesionado' if r.injured else 'sancionado'}")
        elif r.chosen and r.start_prob is not None and float(r.start_prob) < 0.5:
            pct = round(float(r.start_prob) * 100)
            snap.lineup_problems.append(f"{r.name} solo sale de titular el {pct} % de las veces")
        if r.chosen and not r.current:
            snap.lineup_changes.append(f"falta {r.name}")
        if r.current and not r.chosen:
            snap.lineup_changes.append(f"sobra {r.name}")
    return snap


# --- La redacción, sin base de datos ------------------------------------------------------------


_NUMEROS = {1: "Una", 2: "Dos", 3: "Tres", 4: "Cuatro", 5: "Cinco"}


def _cuenta(n: int) -> str:
    """«Dos de las cuatro» se lee; «2 de las 4», no."""
    return _NUMEROS.get(n, str(n))


def _pareja(a: int, b: int) -> tuple[str, str]:
    """Los dos con la misma forma: «Cuatro de las 6» chirría, o palabras las dos o cifras las dos."""
    if a in _NUMEROS and b in _NUMEROS:
        return _cuenta(a), _cuenta(b).lower()
    return str(a), str(b)


def _resumen(mejoran: int, total: int) -> str:
    """«Una de las Una entrarían» no se lee; cuando son todas hay que decirlo de otra forma."""
    verbo = "entraría" if mejoran == 1 else "entrarían"
    if mejoran == total:
        if total == 1:
            return "La única opción que te cabe entraría en tu once."
        return f"Las {_cuenta(total).lower()} {verbo} en tu once."
    a, b = _pareja(mejoran, total)
    return f"{a} de las {b} {verbo} en tu once, y van primero."


def _pts(n: float) -> str:
    """Puntos con su palabra y sin decimales de más: «1,2 puntos», «1 punto»."""
    txt = f"{n:.1f}".replace(".", ",")
    return f"{txt} punto" if txt in ("1,0", "-1,0") else f"{txt} puntos"


def _calendario(label: str | None) -> str | None:
    """La etiqueta de calendario, solo cuando destaca. «Del montón» no cambia ninguna decisión."""
    if not label or "montón" in label or "comparación" in label:
        return None
    return "calendario " + ("fácil" if "fácil" in label else "difícil")


def _porque(b: Buy) -> str | None:
    """El veredicto sin repetir la puja, que ya va en la línea de arriba.

    El texto del motor empieza por «Puja hasta 14,21 M: …» y la cabecera dice «puja hasta 14,2 M»:
    la misma cifra dos veces y con dos redondeos distintos se lee como si fueran dos números."""
    t = b.reason("VEREDICTO") or b.reason("PUJA_GANAR")
    if t and t.startswith("Puja hasta") and ": " in t:
        t = t.split(": ", 1)[1]
        return t[0].upper() + t[1:]
    return t


def _linea_compra(b: Buy, sin_once: bool = False) -> list[str]:
    cabeza = f"· <b>{b.name}</b> — puja hasta {_fmt(b.bid)}"
    calendario = _calendario(b.fixture)
    if calendario:
        cabeza += f" <i>({calendario})</i>"
    fuera = [cabeza]
    # Lo primero, si te mejora el once: es lo que decide si pujar o guardar el saldo.
    if b.improves is not None and b.improves > 0 and sin_once:
        fuera.append(f"  Te dejaría alinear un once, y ese once espera {_pts(b.improves)}")
    elif b.improves is not None and b.improves > 0:
        fuera.append(f"  Entraría en tu once y le sumaría {_pts(b.improves)} por jornada")
    elif b.improves is not None:
        fuera.append("  No entraría en tu once: si pujas, es por la reventa")
    porque = _porque(b)
    if porque:
        fuera.append(f"  {porque}")
    # Lo que no se sabe se dice: sin dato de titularidad los puntos van sin ajustar y la puja
    # descansa sobre una cifra más floja de lo que parece.
    if b.start_prob is None:
        fuera.append(
            "  ⚠️ Sin dato de si es titular: se le cuenta el 43 % que juegan los que tampoco lo tienen"
        )
    elif b.start_prob < 0.6:
        fuera.append(f"  ⚠️ Solo sale de titular el {round(b.start_prob * 100)} % de las veces")
    # `club_name` solo viene cuando ya tienes gente de ese club: es el aviso de concentración, no
    # el club del jugador. Se usa para lo que es, con la cifra que trae el motor.
    if b.club and b.reason("CONCENTRACION"):
        fuera.append(f"  ⚠️ Ya tienes jugadores del {b.club}: concentras riesgo en un solo equipo")
    return fuera


def compose(s: Snapshot) -> str:
    """El mensaje. Cada bloque aparece solo si tiene algo que decidir."""
    cierre = _falta(s.market_closes, s.now)
    bloques: list[str] = []

    cabecera = f"⚽ <b>lfm · {s.day:%d/%m}</b>"
    if cierre:
        cabecera += f"\nEl mercado cierra en {cierre}"
    bloques.append(cabecera)

    # Lo primero de todo: sin once válido no puntúas, y eso no lo arregla ninguna puja fina.
    if s.missing:
        falta = " y ".join(s.missing)
        bloques.append(
            f"🚨 <b>No puedes alinear un once: te falta {falta}.</b>\n"
            f"Ese hueco son cero puntos en la jornada, y solo se arregla fichando."
        )

    if s.buys:
        saldo = f" · saldo {_fmt(s.cash)}" if s.cash is not None else ""
        cabe = [b for b in s.buys if s.cash is None or (b.bid or 0) <= s.cash]
        # Si alguna mejora el once, la lista va por eso y no por el orden del motor, que ordena
        # por rentabilidad total (puntos + reventa). Si no, la conclusión señalaría al tercero.
        if any((b.improves or 0) > 0 for b in cabe):
            cabe = sorted(cabe, key=lambda b: -(b.improves or 0))
        titulo = f"💰 <b>Compraría hoy</b>{saldo}"
        lineas = [titulo]
        for b in cabe[:MAX_BUYS]:
            lineas += _linea_compra(b, bool(s.missing))
        # La conclusión va arriba del todo, que es lo que se lee de un vistazo. No hace falta
        # ningún umbral de «buena compra»: o alguna mejora tu once o ninguna lo hace, y eso lo
        # responde el propio cálculo del once (`eleven.improvement`).
        juzgadas = [b for b in s.buys if b.improves is not None]
        mejoran = [b for b in juzgadas if (b.improves or 0) > 0]
        if mejoran:
            # La cabecera resume; el detalle de cuánto suma cada uno va en su línea. Nombrar aquí
            # al primero repetía su cifra dos renglones seguidos.
            lineas.insert(1, f"<b>{_resumen(len(mejoran), len(juzgadas))}</b>")
        elif juzgadas:
            lineas.insert(
                1,
                "<b>Ninguna te mejora el once.</b> Si no vas a por la reventa, hoy guarda el saldo.",
            )
        restantes = len(s.buys) - len(cabe[:MAX_BUYS])
        if restantes == 1:
            lineas.append("<i>Hay una opción más en la app.</i>")
        elif restantes > 1:
            lineas.append(f"<i>Hay {restantes} opciones más en la app.</i>")
        if not cabe:
            lineas = [titulo, "· Ninguna de las opciones te cabe con el saldo de hoy."]
        bloques.append("\n".join(lineas))

    if s.sells:
        lineas = ["📉 <b>Vendería</b>"]
        for b in s.sells[:MAX_BUYS]:
            porque = b.reason("VEREDICTO") or ""
            lineas.append(f"· <b>{b.name}</b>" + (f" — {porque}" if porque else ""))
        bloques.append("\n".join(lineas))

    if s.risks:
        lineas = ["🔓 <b>Posible clausulazo</b>"]
        for r in s.risks[:MAX_RISKS]:
            quien = "un rival tendría" if r["cuantos"] == 1 else f"{r['cuantos']} rivales tendrían"
            linea = f"· <b>{r['name']}</b> por {_fmt(r['clause'])}, y {quien} saldo estimado para pagarla"
            # Lo que de verdad frena a un rival es pagar por encima del valor. Sin esa frase,
            # «cláusula de 35,2 M» parecía tranquilizador por ser una cifra alta, cuando es
            # exactamente su valor y no le cuesta nada llevárselo.
            sobrecoste = r["clause"] - r["value"]
            if r["value"] and abs(sobrecoste) < r["value"] * AT_VALUE:
                sobrecoste = 0.0
            if sobrecoste > 0:
                linea += f"\n  Aunque pagaría {_fmt(sobrecoste)} más de lo que vale"
            elif sobrecoste < 0:
                linea += f"\n  Y encima se lo llevaría {_fmt(-sobrecoste)} por debajo de su valor"
            else:
                linea += "\n  Le cuesta justo lo que vale: nada le frena"
            lineas.append(linea)
        bloques.append("\n".join(lineas))

    # El once solo cuando aún da tiempo a arreglarlo comprando
    horas = (s.week_opens - s.now).total_seconds() / 3600 if s.week_opens else None
    if horas is not None and 0 < horas <= LINEUP_WARNING_HOURS and (s.lineup_changes or s.lineup_problems):
        falta = _falta(s.week_opens, s.now)
        lineas = [f"🥅 <b>La jornada {s.week or ''} empieza en {falta}</b>".replace("  ", " ")]
        if s.lineup_changes:
            lineas.append("· Tu once no es el que más puntúa: " + ", ".join(s.lineup_changes))
        for p in s.lineup_problems:
            lineas.append(f"· {p}")
        bloques.append("\n".join(lineas))

    if len(bloques) == 1:
        return bloques[0] + "\n\nNada que decidir hoy."
    return "\n\n".join(bloques)


def daily_message(conn: Connection, *, league_id: str, day: date, now: datetime | None = None) -> str:
    snap = gather(conn, league_id=league_id, day=day, now=now)
    if snap is None:
        return "⚠️ <b>lfm</b>: sin datos de tu equipo hoy."
    return compose(snap)


def gap_message(missing: list[date]) -> str:
    days = ", ".join(f"{d:%d/%m}" for d in sorted(missing))
    return f"⚠️ <b>lfm</b>: faltan snapshots de {days}. El histórico tiene huecos."
