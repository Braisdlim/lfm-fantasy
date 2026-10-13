"""Recomendación diaria: qué pujar en el mercado de la liga y qué vender de mi plantilla.

Combina los dos números que hacen falta para decidir una puja (docs/criterio.md §7):

1. **Cuánto hay que pujar para ganar** (`lfm.analysis.bids`), de las subastas reales de la liga.
2. **Cuánto compensa pagar**: el valor esperado de reventa menos un margen.

       venta_esperada = valor × (1 + deriva) × 1,03
       puja_maxima    = venta_esperada − ventaja_minima × valor

   El 1,03 es lo que paga el sistema al recomprar (medido en 75 ventas de la liga, banda 90-111 %).

El veredicto es la comparación: si para ganarlo hay que pagar más de lo que se recupera, la
recomendación es **no pujar**, que suele ser la que más dinero ahorra.

Cada recomendación se guarda en `recommendations` con sus `reasons[]` (código, texto, cifra y
fuente), de modo que después se pueda comprobar si acertó. Ninguna frase existe sin su número.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Connection

from lfm.analysis import bids as bids_mod
from lfm.analysis import drift as drift_mod
from lfm.analysis import eleven as eleven_mod
from lfm.analysis import fixtures as fx_mod
from lfm.analysis import points as pts_mod
from lfm.analysis import rebound as rebound_mod
from lfm.analysis import trend as trend_mod

SYSTEM_RESALE = 1.03  # lo que paga el sistema al recomprar, medido en la liga
# Ventaja mínima exigida, en tanto por uno del valor. Con deriva cero, comprar al valor y revender
# al sistema deja un 3 % bruto; exigir un 3 % de ventaja significa que solo se recomienda pujar
# cuando el jugador tiene deriva esperada positiva. Es estricto a propósito.
MIN_EDGE = 0.03
WIN_CONFIDENCE = 0.7  # percentil de pujas ganadoras observadas; NO probabilidad de ganar
SELL_STREAK = 5  # días seguidos de caída a partir de los cuales avisamos de venta
MIN_SELL_LOSS = 0.02  # pérdida esperada a 7 días por debajo de la cual no se recomienda vender
# Cuánto vale un punto en euros. La guía cita 100.000 € y en nuestra liga los ingresos por jornada
# son siempre múltiplos de 100.000, lo que encaja, pero NO está verificado hacia atrás porque no
# guardábamos los onces (docs/criterio.md §3). Se marca como supuesto en las razones.
EUROS_PER_POINT = 100_000
POINTS_ASSUMPTION = "supuesto: 100.000 € por punto"


@dataclass
class Reason:
    code: str
    text: str
    value: float | None = None
    source: str = "laliga_api"


@dataclass
class Recommendation:
    kind: str  # buy | sell
    player_id: str
    name: str
    score: float  # beneficio esperado en euros (compra) o pérdida evitada (venta)
    verdict: str
    reasons: list[Reason] = field(default_factory=list)
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Fit:
    """Cómo encaja un jugador en **tu** once. Es lo que convierte puntos esperados en puntos tuyos.

    En el fantasy gratuito no hay banquillo que puntúe: un suplente suma cero. Contar los puntos
    esperados de un jugador que no entraría en tu once (o no restar los de uno que sí juega al
    venderlo) recomendaba fichar activos, no futbolistas, y contradecía al aviso de Telegram, que
    ya preguntaba si el fichaje mejoraba el once."""

    gain: float  # puntos por jornada que gana (compra) o pierde (venta) tu mejor once
    completes: bool = False  # compra: sin él no puedes alinear ningún once válido
    breaks: bool = False  # venta: sin él te quedas sin once válido
    replaces: str | None = None  # compra: a quién sacaría de tu once
    missing: tuple[str, ...] = ()  # venta: qué te faltaría para alinear
    incomplete: bool = False  # no existe un once actual con el que comparar


SQL_MARKET = text(
    "SELECT m.player_id, p.name, p.nickname, p.position_id, p.team_id AS club_id, "
    "       m.sale_price::float8 AS price, "
    "       m.num_bids, v.market_value::float8 AS value, v.status "
    "FROM market_offer m "
    "JOIN players p ON p.player_id = m.player_id "
    "JOIN player_value_daily v ON v.player_id = m.player_id AND v.day = CAST(:day AS date) "
    "WHERE m.league_id = :league_id AND m.kind = 'marketPlayerLeague' "
    # Sin entrenadores: en el juego gratuito no se alinean (`coach: 0`), así que no puntúan nunca.
    "  AND p.position_id BETWEEN 1 AND 4 "
    "  AND m.cycle_end = (SELECT max(cycle_end) FROM market_offer WHERE league_id = :league_id "
    "                     AND kind = 'marketPlayerLeague') "
    "  AND (m.expires_at IS NULL OR m.expires_at > now())"
)

SQL_MY_SQUAD = text(
    "SELECT q.player_id, p.name, p.nickname, p.position_id, p.team_id AS club_id, "
    "       v.market_value::float8 AS value, v.status "
    "FROM league_squad_daily q "
    "JOIN players p ON p.player_id = q.player_id "
    "JOIN player_value_daily v ON v.player_id = q.player_id AND v.day = CAST(:day AS date) "
    "WHERE q.league_id = :league_id AND q.team_id = :team_id "
    "  AND q.day = (SELECT max(day) FROM league_squad_daily WHERE team_id = :team_id)"
)

SQL_SERIES_FOR = text(
    "SELECT market_value::float8 AS v FROM player_value_daily "
    "WHERE player_id = :player_id AND day <= CAST(:day AS date) AND market_value > 0 "
    "ORDER BY day DESC LIMIT 40"
)

# Si la migración aún no ha corrido (el job ligero no migra), la tabla no existe: se comprueba
# antes para no abortar la transacción entera por una consulta opcional.
SQL_THESIS = text(
    "SELECT t.player_id, t.created_at, t.entry_value::float8 AS entry_value, t.note "
    "FROM player_thesis t WHERE to_regclass('player_thesis') IS NOT NULL"
)
SQL_HAS_THESIS = text("SELECT to_regclass('player_thesis') IS NOT NULL")

SQL_CASH = text(
    "SELECT COALESCE(lt.team_money, (SELECT s.team_money FROM league_standing_daily s "
    "WHERE s.league_id = lt.league_id AND s.team_id = lt.team_id AND s.team_money IS NOT NULL "
    "ORDER BY s.day DESC LIMIT 1))::float8 FROM league_teams lt "
    "WHERE lt.league_id = :league_id AND lt.team_id = :team_id"
)

SQL_SAVE = text(
    "INSERT INTO recommendations (kind, subject, score, reasons) "
    "SELECT r.kind, r.subject, r.score, r.reasons "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r("
    "kind text, subject jsonb, score numeric, reasons jsonb)"
)

# `recommendations` es **la foto vigente y nada más**: el histórico vive en `recommendation_log`.
# Antes solo se borraban las del día, y como la web lee las últimas 36 horas, las de ayer seguían
# ahí: el 2026-09-09 salían 28 filas para 14 jugadores, cada uno dos veces y con cifras distintas
# (Bartra a 35,9 M y a 36,3 M a la vez). Con una sola foto viva eso no puede volver a pasar.
SQL_CLEAR = text("DELETE FROM recommendations WHERE acted_at IS NULL")


def _es(x: float, decimals: int = 2) -> str:
    """Número en formato español: miles con punto y decimales con coma."""
    return f"{x:,.{decimals}f}".replace(",", "·").replace(".", ",").replace("·", ".")


def _money(x: float) -> str:
    return f"{_es(x / 1e6)} M"


def _deriva_reason(d: drift_mod.Drift, *, solo: str = "") -> Reason:
    """La deriva, y por qué la creemos.

    Cuando la racha está censurada no se puede decir «jugadores subiendo 1 día», porque ese 1 es
    lo que alcanzamos a ver y no lo que pasó. En ese caso se usa la media general y se dice."""
    if d.bucket == drift_mod.UNKNOWN_STREAK:
        return Reason(
            "DERIVA",
            f"Lleva muy poco en el juego, así que no se puede saber su racha: se usa la media "
            f"general, {_pct(d.mean)} a 7 días (n={_es(d.n, 0)})",
            d.mean,
            source="histórico propio",
        )
    return Reason(
        "DERIVA",
        f"Jugadores {d.bucket} cambiaron {_pct(d.mean)} a 7 días y {solo}subieron el "
        f"{d.up_rate * 100:.0f} % de las veces (n={_es(d.n, 0)})",
        d.mean,
        source="histórico propio",
    )


def _calendario_reason(sport: pts_mod.Expectation) -> Reason:
    return Reason(
        "CALENDARIO",
        f"Calendario {sport.label or _calendario(sport.fixture_factor)} ({sport.detail})",
        sport.fixture_factor,
        "resultados oficiales",
    )


def _titular_reason(sport: pts_mod.Expectation) -> Reason:
    if sport.start_prob is None:
        return Reason(
            "TITULAR",
            f"Sin dato de alineación probable. Se le aplica el "
            f"{_es(pts_mod.UNKNOWN_START_PROB * 100, 0)} %, que es lo que jugaron los que tampoco "
            f"lo tenían (24 de 56 veces, frente a 733 de 967 de los que sí)",
            pts_mod.UNKNOWN_START_PROB,
            "medido sobre nuestro histórico",
        )
    return Reason(
        "TITULAR",
        f"Probabilidad de ser titular: {_es(sport.start_prob * 100, 0)} %",
        sport.start_prob,
        "FútbolFantasy",
    )


def _puntos_reason(sport: pts_mod.Expectation, sport_value: float) -> Reason:
    if sport.played == 0:
        return Reason(
            "PUNTOS",
            "Sin ninguna jornada puntuada: no hay evidencia de que juegue, así que no se le "
            "cuenta valor deportivo",
            0.0,
            "puntos por jornada de la API",
        )
    return Reason(
        "PUNTOS",
        f"Espera {_es(sport.xpts, 1)} puntos en la próxima jornada "
        f"(media propia {_es(sport.rate, 1)} en {sport.played} jornadas), que valen {_money(sport_value)}",
        sport.xpts,
        POINTS_ASSUMPTION,
    )


def _calendario(factor: float) -> str:
    if factor >= 1.2:
        return "muy favorable"
    if factor >= 1.05:
        return "favorable"
    if factor <= 0.8:
        return "muy difícil"
    if factor <= 0.95:
        return "difícil"
    return "neutro"


def _pct(x: float) -> str:
    return f"{'+' if x >= 0 else '−'}{_es(abs(x) * 100, 1)} %"


def buy_recommendation(
    row,
    series: list[float],
    table: dict[str, drift_mod.Drift],
    ratios,
    cash: float,
    sport: pts_mod.Expectation | None = None,
    club_share: dict | None = None,
    flags: dict | None = None,
    fit: Fit | None = None,
    rebound: rebound_mod.Signal | None = None,
    tables: tuple | None = None,
) -> Recommendation:
    value = row.value
    d = drift_mod.expected(table, series)
    if tables is not None:
        d = drift_mod.expected_magnitude(tables[1], tables[0], series)
    if rebound is not None and drift_mod.streak(series) <= rebound_mod.FALLING:
        # Viene bajando, pero con un hecho que en nuestra historia cambió lo que pasó después: se usa
        # lo que pasó de verdad con los que estaban igual, no la media de su racha.
        d = drift_mod.Drift(rebound.mean_7d, rebound.up_rate, rebound.n, f"señal: {rebound.label}")
    resale = value * (1 + d.mean) * SYSTEM_RESALE
    # El valor deportivo se suma al techo: puntuar también es dinero, porque cada punto paga. Pero
    # solo puntúa quien juega: con la plantilla a la vista se cuenta lo que mejora **tu** once.
    if fit is not None:
        sport_value = max(fit.gain, 0.0) * EUROS_PER_POINT
    else:
        sport_value = (sport.xpts * EUROS_PER_POINT) if sport else 0.0
    max_bid = max(0.0, resale + sport_value - MIN_EDGE * value)
    # La racha del jugador entra en la puja: lo que decide cuanto hay que pagar no es solo lo
    # que vale, es si toda la liga lo esta viendo subir.
    win = bids_mod.bid_to_win(ratios, value, WIN_CONFIDENCE, player_momentum=bids_mod.momentum(series))
    # El mínimo del anuncio manda aunque el histórico sugiera una cifra menor.
    asking = max(0.0, float(getattr(row, "price", None) or value))
    if win is not None and win.amount < asking:
        win = replace(win, amount=int(asking), ratio=asking / value)
    reasons = [
        Reason("VALOR", f"Vale {_money(value)}; precio mínimo del anuncio: {_money(asking)}", value),
        _deriva_reason(d) if not d.bucket.startswith("señal") else _rebote_reason(rebound),
        Reason("REVENTA", f"Reventa esperada al sistema: {_money(resale)}", resale, "75 ventas de la liga"),
    ]
    if sport:
        reasons.append(_calendario_reason(sport))
        reasons.append(_titular_reason(sport))
        reasons.append(_puntos_reason(sport, sport.xpts * EUROS_PER_POINT))
    if fit is not None:
        reasons.append(_encaje_compra_reason(fit, sport_value))
    if flags:
        # La API de LaLiga tarda en marcar las bajas; FútbolFantasy las publica antes. Cuando no
        # coinciden se dice, pero no se veta: la probabilidad de titular ya recorta los puntos, y
        # vetar además sería contar dos veces la misma lesión.
        if flags.get("injured") and row.status == "ok":
            reasons.append(
                Reason(
                    "LESION",
                    "FútbolFantasy lo da lesionado o en duda, aunque la app oficial lo da disponible",
                    None,
                    "FútbolFantasy",
                )
            )
        if flags.get("suspended"):
            reasons.append(
                Reason("SANCION", "Está sancionado: no juega la próxima jornada", None, "FútbolFantasy")
            )
        elif flags.get("booking_risk"):
            reasons.append(
                Reason(
                    "APERCIBIDO",
                    "Apercibido: a una amarilla de perderse la siguiente jornada",
                    None,
                    "FútbolFantasy",
                )
            )
    if club_share and club_share["share"] >= pts_mod.CONCENTRATION_ALERT:
        reasons.append(
            Reason(
                "CONCENTRACION",
                f"Ya tienes {club_share['n']} jugador(es) del {club_share['club']}, el "
                f"{_es(club_share['share'] * 100, 0)} % del valor de tu plantilla. El "
                f"{_es(pts_mod.TEAM_SHARE_OF_VARIANCE * 100, 0)} % de los puntos de una jornada lo "
                f"explica qué hizo su equipo ese día, así que sumar otro concentra riesgo sin subir "
                f"lo que esperas ganar",
                club_share["share"],
                "puntos por jornada de la liga",
            )
        )
    reasons.append(
        Reason("TECHO", f"Por encima de {_money(max_bid)} la operación deja de compensar", max_bid)
    )
    if d.low is not None and d.high is not None:
        reasons.append(
            Reason(
                "INCERTIDUMBRE",
                f"El 60 % central de los cambios históricos a 7 días estuvo entre {_pct(d.low)} y "
                f"{_pct(d.high)}. Es dispersión de resultados, no una garantía para este jugador",
                d.low,
                "histórico propio · percentiles 20–80",
            )
        )
    if win:
        reasons.append(
            Reason(
                "PUJA_GANAR",
                (
                    f"Referencia de puja: {_money(win.amount)}, a partir del percentil 70 de "
                    f"precios ganadores ({win.band}, n={win.n}) y el mínimo del anuncio"
                )
                + (
                    ""
                    if win.momentum_band is None
                    else (
                        f", contando que viene {win.momentum_band}: eso subió la puja un "
                        f"{_es((win.momentum_factor - 1) * 100, 0)} % (n={win.momentum_n})"
                        if win.momentum_factor >= 1
                        else (
                            f", contando que viene {win.momentum_band}: eso bajó la puja un "
                            f"{_es((1 - win.momentum_factor) * 100, 0)} % (n={win.momentum_n})"
                        )
                    )
                )
                + ". Solo vemos las pujas ganadoras; no equivale a un 70 % de probabilidad de ganar",
                win.amount,
                "fichajes de la liga",
            )
        )
    if row.num_bids:
        reasons.append(Reason("PUJAS", f"Ya tiene {row.num_bids} puja(s)", row.num_bids))
    if row.status != "ok":
        reasons.append(Reason("ESTADO", f"Estado: {row.status}", None))

    affordable = win is not None and win.amount <= cash
    if win is None or (d.n < drift_mod.MIN_SAMPLE and not d.bucket.startswith("señal")) or len(series) < 2:
        verdict, score = "sin_datos", 0.0
        reasons.append(Reason("DATOS", "Falta histórico suficiente de precios o subastas para decidir"))
    elif row.status in ("injured", "suspended", "out_of_league"):
        verdict, score = "no_pujar", 0.0
        reasons.append(Reason("VETO", f"No se recomienda pujar por un jugador {row.status}", None))
    elif win.amount > max_bid:
        verdict = "no_pujar"
        score = resale + sport_value - win.amount
        reasons.append(
            Reason(
                "VEREDICTO",
                f"Para llevártelo harían falta {_money(win.amount)} y entre reventa y puntos recuperas "
                f"{_money(resale + sport_value)}: "
                + (
                    f"perderías {_money(win.amount - resale - sport_value)}"
                    if win.amount - resale - sport_value > 1000
                    else "te quedarías en tablas, sin margen que justifique el riesgo"
                ),
                score,
            )
        )
    elif not affordable:
        verdict = "sin_saldo"
        score = resale + sport_value - win.amount
        reasons.append(
            Reason("SALDO", f"Te faltan {_money(win.amount - cash)} para poder pujar eso", cash - win.amount)
        )
    else:
        verdict = "pujar"
        score = resale + sport_value - win.amount
        reasons.append(
            Reason(
                "VEREDICTO",
                f"Puja orientativa: {_money(win.amount)}. No superes {_money(min(max_bid, cash))}; "
                f"entre reventa y puntos se estiman {_money(resale + sport_value)}, sin garantía de ganarla",
                score,
            )
        )
    return Recommendation(
        kind="buy",
        player_id=row.player_id,
        name=row.nickname or row.name,
        score=round(score, 2),
        verdict=verdict,
        reasons=reasons,
        detail={
            "value": value,
            "max_bid": round(max_bid),
            "affordable_max": int(max(0, min(max_bid, cash))),
            "min_price": round(asking),
            "margin_required": round(MIN_EDGE * value),
            "bid_sample": win.n if win else 0,
            "bid_percentile": WIN_CONFIDENCE,
            "bid_to_win": win.amount if win else None,
            "win_ratio": win.ratio if win else None,
            "expected_resale": round(resale),
            "sport_value": round(sport_value),
            "xpts": round(sport.xpts, 2) if sport else None,
            "fixture_factor": round(sport.fixture_factor, 3) if sport else None,
            "fixture_label": sport.label if sport else None,
            "start_prob": sport.start_prob if sport else None,
            "club_share": round(club_share["share"], 3) if club_share else None,
            "club_name": club_share["club"] if club_share else None,
            "drift": d.mean,
            "drift_n": d.n,
            "drift_low": d.low,
            "drift_high": d.high,
            "up_rate": d.up_rate,
            "bucket": d.bucket,
            "num_bids": row.num_bids,
            "eleven_gain": round(fit.gain, 2) if fit else None,
            "incomplete_eleven": fit.incomplete if fit else False,
            "rebound": (
                rebound.label
                if rebound is not None and rebound.rebound and d.bucket.startswith("señal")
                else None
            ),
            "completes_eleven": fit.completes if fit else False,
            "replaces": fit.replaces if fit else None,
        },
    )


def _rebote_reason(sig: rebound_mod.Signal) -> Reason:
    return Reason(
        "REBOTE" if sig.rebound else "FRENA",
        f"Viene bajando, pero {sig.label}: de {_es(sig.n, 0)} jugadores que bajaban así, a 7 días "
        f"cambiaron {_pct(sig.mean_7d)} y subió el {sig.up_rate * 100:.0f} % (los que bajaban sin "
        f"eso: {_pct(sig.control_mean)}). Comprobado por separado en la mitad antigua y la reciente",
        sig.mean_7d,
        "histórico propio",
    )


def _encaje_compra_reason(fit: Fit, sport_value: float) -> Reason:
    if fit.incomplete:
        return Reason(
            "ENCAJE",
            "Aún no tienes un once válido y esta compra no lo completa. "
            "No se añade valor deportivo a la puja hasta poder comparar onces",
            None,
            "tu plantilla",
        )
    if fit.completes:
        return Reason(
            "ENCAJE",
            "Sin él no puedes alinear ningún once válido, y una jornada sin once son cero puntos: "
            "es la compra que más urge",
            fit.gain,
            "tu plantilla",
        )
    if fit.gain > 0.05:
        return Reason(
            "ENCAJE",
            "Entra en tu once"
            + (f" por {fit.replaces}" if fit.replaces else "")
            + f": suma {_es(fit.gain, 1)} puntos por jornada a tu mejor once, "
            f"que valen {_money(sport_value)}",
            fit.gain,
            "tu plantilla",
        )
    return Reason(
        "ENCAJE",
        "No entraría en tu once: sería suplente y sus puntos no te cuentan. Solo lo justifica la reventa",
        0.0,
        "tu plantilla",
    )


def sell_recommendation(
    row,
    series: list[float],
    table: dict[str, drift_mod.Drift],
    sport: pts_mod.Expectation | None = None,
    fit: Fit | None = None,
    thesis: dict | None = None,
    signal: rebound_mod.Signal | None = None,
    tables: tuple | None = None,
    *,
    include_holds: bool = False,
) -> Recommendation | None:
    k = drift_mod.streak(series)
    if k > -SELL_STREAK and not include_holds:
        return None
    d = drift_mod.expected(table, series)
    if tables is not None:
        d = drift_mod.expected_magnitude(tables[1], tables[0], series)
    if signal is not None:
        d = drift_mod.Drift(signal.mean_7d, signal.up_rate, signal.n, f"señal: {signal.label}")
    value = row.value
    loss = value * d.mean
    # Lo que pierdes al venderlo son los puntos que tu once deja de sumar, no los suyos: si es
    # suplente, venderlo no te cuesta ninguno.
    if fit is not None:
        sport_value = max(fit.gain, 0.0) * EUROS_PER_POINT
    else:
        sport_value = (sport.xpts * EUROS_PER_POINT) if sport else 0.0
    reasons = [
        Reason(
            "RACHA",
            (
                f"Lleva {abs(k)} días seguidos {'bajando' if k < 0 else 'subiendo'}"
                if k
                else "Sin racha de precio activa"
            ),
            k,
        ),
        _rebote_reason(signal) if signal is not None else _deriva_reason(d, solo="solo "),
        Reason(
            "COSTE",
            f"Esperar una semana cuesta unos {_money(-loss)} de media"
            if loss < 0
            else f"Lo esperable a una semana es que no pierda valor ({_pct(d.mean)})",
            loss,
        ),
        Reason(
            "OFERTA",
            f"El sistema paga en torno a {_money(value * SYSTEM_RESALE)}, y esa oferta baja con el valor",
            value * SYSTEM_RESALE,
            "75 ventas de la liga",
        ),
    ]
    verdict = "vender" if k <= -SELL_STREAK and (d.n >= drift_mod.MIN_SAMPLE or signal) else "aguantar"
    if verdict == "aguantar":
        reasons.append(
            Reason(
                "VENTA",
                "No hay una señal de venta contrastada por la racha actual; revisa el saldo y las ofertas",
                None,
                "regla de venta validada",
            )
        )
    # Por debajo de un 2 % de pérdida esperada, vender no compensa: el sistema paga entre el 90 y el
    # 111 % del valor, así que la diferencia se come en la propia venta. Caso Tchouaméni: 39 días
    # bajando, pero ya casi plano; los que estaban así perdieron de mediana un 1 %, no un 10 %.
    material = d.mean <= -MIN_SELL_LOSS
    if not material and not thesis:
        verdict = "aguantar"
        reasons.append(
            Reason(
                "VEREDICTO",
                (
                    f"Esperar apenas cuesta ({_pct(d.mean)} a 7 días): "
                    "menos de lo que se juega en la propia venta"
                    if d.mean < 0
                    else f"La referencia histórica no anticipa pérdida a 7 días ({_pct(d.mean)})"
                ),
                d.mean,
            )
        )
    if thesis:
        # Tu apuesta manda sobre una racha de mercado: el modelo solo ve precios y no puede saber
        # que esperas que gane la titularidad. Se sigue diciendo lo que cuesta esperar, con cifra.
        verdict = "aguantar"
        entrada = thesis.get("entry_value")
        desde = thesis.get("created_at")
        va = f", y desde entonces va {_pct(value / entrada - 1)}" if entrada else ""
        reasons.append(
            Reason(
                "APUESTA",
                "Es tu apuesta"
                + (f" desde el {desde:%d/%m}" if desde else "")
                + (f" a {_money(entrada)}" if entrada else "")
                + va
                + (f" («{thesis['note']}»)" if thesis.get("note") else "")
                + ". El mercado no la ve; la decisión es tuya",
                (value / entrada - 1) if entrada else None,
                "tú",
            )
        )
    elif fit is not None and fit.incomplete:
        verdict = "aguantar"
        reasons.append(
            Reason(
                "ENCAJE",
                "Tu plantilla aún no permite un once válido: no se puede medir el coste de venderlo. "
                "Revisa los puestos que faltan antes de desprenderte de él",
                None,
                "tu plantilla",
            )
        )
    elif verdict == "aguantar":
        pass
    elif fit is not None and fit.breaks:
        # Restricción dura, no una cuenta: sin once válido la jornada vale cero para todo el equipo.
        verdict = "aguantar"
        reasons.append(
            Reason(
                "ENCAJE",
                f"Sin él te quedas sin once válido (te faltaría {', '.join(fit.missing) or 'un titular'}): "
                "véndelo solo cuando tengas el sustituto",
                None,
                "tu plantilla",
            )
        )
    elif fit is not None:
        reasons.append(
            Reason(
                "ENCAJE",
                (
                    f"Es titular en tu once: sin él pierdes {_es(fit.gain, 1)} puntos por jornada"
                    if fit.gain > 0.05
                    else "No juega en tu once: venderlo no te cuesta puntos"
                ),
                fit.gain,
                "tu plantilla",
            )
        )
    if sport:
        reasons.append(_calendario_reason(sport))
        reasons.append(_titular_reason(sport))
        reasons.append(_puntos_reason(sport, sport.xpts * EUROS_PER_POINT))
        # lo que rinde en el campo puede compensar lo que pierde en el mercado
        if verdict == "vender" and sport_value >= abs(loss):
            verdict = "aguantar"
            reasons.append(
                Reason(
                    "VEREDICTO",
                    f"Pierde {_money(abs(loss))} de valor a la semana, pero sus puntos valen "
                    f"{_money(sport_value)}: compensa aguantarlo",
                    sport_value - abs(loss),
                )
            )
    if verdict == "vender":
        reasons.append(
            Reason(
                "VEREDICTO",
                f"Pierde {_money(abs(loss))} de valor a la semana y sus puntos solo valen "
                f"{_money(sport_value)}",
                abs(loss) - sport_value,
            )
        )
    return Recommendation(
        kind="sell",
        player_id=row.player_id,
        name=row.nickname or row.name,
        score=round(max(-loss, 0.0) - sport_value, 2),
        verdict=verdict,
        reasons=reasons,
        detail={
            "value": value,
            "streak": k,
            "drift": d.mean,
            "drift_n": d.n,
            "drift_low": d.low,
            "drift_high": d.high,
            "sport_value": round(sport_value),
            "xpts": round(sport.xpts, 2) if sport else None,
            "fixture_factor": round(sport.fixture_factor, 3) if sport else None,
            "fixture_label": sport.label if sport else None,
            "start_prob": sport.start_prob if sport else None,
            "eleven_gain": round(fit.gain, 2) if fit else None,
            "incomplete_eleven": fit.incomplete if fit else False,
            "breaks_eleven": fit.breaks if fit else False,
            "thesis": bool(thesis),
        },
    )


SQL_LATEST_VALUE_DAY = text("SELECT max(day) FROM player_value_daily WHERE source = 'laliga_api'")


def build(conn: Connection, *, league_id: str, day: date, team_id: str | None) -> list[Recommendation]:
    # El valor de mercado lo escribe el job diario, así que **hoy puede no existir todavía**: el
    # ligero corre desde las 06:19 UTC y el diario no llega hasta las 17:38. Pedir el valor "de hoy"
    # devolvía cero filas durante once horas al día y con ellas cero recomendaciones. Se usa el
    # último día con valores, que es lo que hace la web desde siempre.
    value_day = conn.execute(SQL_LATEST_VALUE_DAY).scalar() or day
    return _build(conn, league_id=league_id, day=value_day, team_id=team_id)


def _build(conn: Connection, *, league_id: str, day: date, team_id: str | None) -> list[Recommendation]:
    # Precios y modelo verificados por datos, fecha y código. Mercado, saldo,
    # disponibilidad y demás entradas actuales se siguen leyendo debajo.
    from lfm.analysis import price_models

    models = price_models.load(conn, day)
    recent = models["recent"]
    trend_table, trend_check = models["trend_table"], models["trend_check"]
    table = {k: drift_mod.Drift(**v) for k, v in models["table"].items()}
    # Racha partida por su tamaño y resumida con la mediana: el modelo que ganó la prueba hacia
    # delante del 2026-09-20 (error medio 0,076 frente a 0,097 del de solo racha y 0,111 del baseline,
    # 4.176 predicciones en 7 cortes). `python -m lfm.analysis.drift comparar`.
    tables = (table, {k: drift_mod.Drift(**v) for k, v in models["magnitude"].items()})
    ratios = bids_mod.load_ratios(conn, league_id=league_id, before=day)
    strength, mu, next_fixtures = fx_mod.load(conn, limit_weeks=1)
    history, pos_means = pts_mod.load(conn)
    clubs = pts_mod.concentration(conn, league_id=league_id, team_id=team_id) if team_id else {}
    avail = pts_mod.availability(conn)
    # universo de factores de calendario de la jornada, para etiquetar por percentil y no por umbral
    universe: dict[str, list[float]] = {"atras": [], "arriba": []}
    for fixs in next_fixtures.values():
        universe["atras"].append(pts_mod.fixture_factor(pts_mod.DEF, fixs, mu, strength)[0])
        universe["arriba"].append(pts_mod.fixture_factor(pts_mod.FWD, fixs, mu, strength)[0])

    def sport_of(row) -> pts_mod.Expectation | None:
        if not next_fixtures or not row.club_id:
            return None
        a = avail.get(row.player_id) or {}
        e = pts_mod.expected(
            history.get(row.player_id, []),
            row.position_id,
            next_fixtures.get(row.club_id, []),
            pos_means,
            mu,
            strength,
            a.get("start_prob"),
        )
        grupo = "atras" if row.position_id in (pts_mod.GK, pts_mod.DEF) else "arriba"
        return replace(e, label=pts_mod.percentile_label(e.fixture_factor, universe[grupo]))

    def flags_of(row) -> dict:
        return avail.get(row.player_id) or {}

    cash = 0.0
    if team_id:
        cash = float(conn.execute(SQL_CASH, {"league_id": league_id, "team_id": team_id}).scalar() or 0)

    def series_of(player_id: str) -> list[float]:
        return recent.get(player_id, [])

    squad_rows = (
        list(conn.execute(SQL_MY_SQUAD, {"league_id": league_id, "team_id": team_id, "day": day.isoformat()}))
        if team_id
        else []
    )
    sports = {r.player_id: sport_of(r) for r in squad_rows}
    squad = [_pick(r, sports[r.player_id], flags_of(r)) for r in squad_rows]
    # Sin puntos esperados de algún titular el once no es comparable: mejor no afirmar nada.
    know_squad = bool(squad) and all(sports[r.player_id] is not None for r in squad_rows)

    market_rows = list(conn.execute(SQL_MARKET, {"league_id": league_id, "day": day.isoformat()}))
    series = {r.player_id: series_of(r.player_id) for r in market_rows}
    # Rebote: solo señales que pasaron su prueba, y solo para los que vienen bajando.
    senales = rebound_mod.passing(conn)
    squad_series = {r.player_id: series_of(r.player_id) for r in squad_rows}
    cayendo = [
        pid for pid, s in {**series, **squad_series}.items() if drift_mod.streak(s) <= rebound_mod.FALLING
    ]
    activas = rebound_mod.active_now(conn, cayendo, day) if senales and cayendo else {}

    def rebound_of(pid: str) -> rebound_mod.Signal | None:
        validas = [senales[n] for n in activas.get(pid, []) if n in senales]
        return max(validas, key=lambda x: x.mean_7d) if validas else None

    out: list[Recommendation] = []
    for row in market_rows:
        sport = sport_of(row)
        fit = buy_fit(squad, _pick(row, sport, flags_of(row))) if know_squad and sport else None
        out.append(
            buy_recommendation(
                row,
                series[row.player_id],
                table,
                ratios,
                cash,
                sport,
                clubs.get(row.club_id),
                flags_of(row),
                fit,
                rebound_of(row.player_id),
                tables,
            )
        )
    theses = {}
    if conn.execute(SQL_HAS_THESIS).scalar():
        theses = {r.player_id: r._asdict() for r in conn.execute(SQL_THESIS)}
    for row in squad_rows:
        fit = sell_fit(squad, row.player_id) if know_squad else None
        rec = sell_recommendation(
            row,
            squad_series[row.player_id],
            table,
            sports[row.player_id],
            fit,
            theses.get(row.player_id),
            rebound_of(row.player_id),
            tables,
            include_holds=True,
        )
        if rec:
            out.append(rec)
    apply_budget(out, cash)
    for rec in out:
        values = recent.get(rec.player_id, [])
        rec.detail["trend"] = trend_mod.outlook(values, trend_table, trend_check)
        rec.detail["value_day"] = day.isoformat()
        rec.detail["history_days"] = len(values)
        rec.detail["missing_eleven"] = eleven_mod.missing_for_eleven(squad) if know_squad else []
        info = avail.get(rec.player_id) or {}
        fetched = info.get("fetched_at")
        if fetched:
            rec.detail["availability_at"] = fetched.isoformat()
            rec.reasons.append(
                Reason(
                    "ACTUALIDAD",
                    f"Titularidad y disponibilidad consultadas el {fetched:%d/%m a las %H:%M} UTC. "
                    "Una noticia posterior puede cambiar el escenario",
                    None,
                    "FútbolFantasy",
                )
            )
    # Primero lo que te deja sin once si no lo compras; después, por beneficio esperado.
    out.sort(key=lambda r: (r.kind != "buy", not r.detail.get("completes_eleven"), -r.score))
    return out


def current_series(rows, day: date) -> dict[str, list[float]]:
    """Último tramo diario por jugador, hasta 40 días y terminado en la fecha de valor."""
    result: dict[str, list[float]] = {}
    previous = None
    last_days = {}
    for row in rows:
        if row.day > day:
            continue
        if (
            previous is None
            or row.player_id != previous.player_id
            or row.day != previous.day + timedelta(days=1)
            or row.source != previous.source
        ):
            result[row.player_id] = []
        result[row.player_id].append(row.v)
        last_days[row.player_id] = row.day
        previous = row
    return {pid: values[-40:] for pid, values in result.items() if last_days[pid] == day}


def _pick(row, sport: pts_mod.Expectation | None, flags: dict) -> eleven_mod.Pick:
    return eleven_mod.Pick(
        player_id=row.player_id,
        name=row.nickname or row.name,
        position_id=row.position_id,
        xpts=sport.xpts if sport else 0.0,
        start_prob=sport.start_prob if sport else None,
        injured=bool(flags.get("injured")) or row.status in ("injured", "out_of_league"),
        suspended=bool(flags.get("suspended")) or row.status == "suspended",
    )


def buy_fit(squad: list[eleven_mod.Pick], candidate: eleven_mod.Pick) -> Fit:
    """Cuánto mejora tu mejor once si lo fichas, y a quién sacaría.

    Si hoy no puedes alinear y con él sí, lo que aporta no es su media: es pasar de cero a tener
    equipo. No se traduce a euros (inflaría la puja con los puntos de los otros diez); se marca como
    `completes` y se ordena primero."""
    ahora = eleven_mod.best(squad)
    con_el = eleven_mod.best([*squad, candidate])
    if con_el is None:
        return Fit(gain=0.0, incomplete=ahora is None)
    if candidate not in con_el.starters:
        return Fit(gain=0.0)
    if ahora is None:
        return Fit(gain=candidate.xpts, completes=True)
    fuera = [p for p in ahora.starters if p not in con_el.starters]
    return Fit(gain=con_el.xpts - ahora.xpts, replaces=fuera[0].name if len(fuera) == 1 else None)


def sell_fit(squad: list[eleven_mod.Pick], player_id: str) -> Fit:
    """Cuántos puntos pierde tu once sin él, y si te quedarías sin poder alinear."""
    ahora = eleven_mod.best(squad)
    resto = [p for p in squad if p.player_id != player_id]
    sin_el = eleven_mod.best(resto)
    if ahora is None:
        return Fit(gain=0.0, incomplete=True)
    if sin_el is None:
        return Fit(gain=ahora.xpts, breaks=True, missing=tuple(eleven_mod.missing_for_eleven(resto)))
    return Fit(gain=ahora.xpts - sin_el.xpts)


def apply_budget(recs: list[Recommendation], cash: float) -> None:
    """Las pujas se recomiendan **juntas**, no cada una como si fuera la única.

    Cada «pujar» se comprobaba contra todo tu saldo, así que la app podía proponer cuatro pujas que
    sumaban el doble de lo que tienes. Se reparten por orden de prioridad (primero la que completa
    tu once, luego la de más beneficio) y la que ya no cabe pasa a `sin_saldo`, diciendo por qué."""
    if cash <= 0:
        return
    pujas = [r for r in recs if r.kind == "buy" and r.verdict == "pujar" and r.detail.get("bid_to_win")]
    pujas.sort(key=lambda r: (not r.detail.get("completes_eleven"), -r.score))
    comprometido = 0.0
    delante: list[str] = []
    for r in pujas:
        importe = float(r.detail["bid_to_win"])
        if comprometido + importe > cash:
            r.verdict = "sin_saldo"
            r.reasons = [x for x in r.reasons if x.code != "VEREDICTO"]
            r.reasons.append(
                Reason(
                    "SALDO",
                    f"Compensa, pero junto a {_lista(delante)} ya comprometes {_money(comprometido)} de "
                    f"{_money(cash)}: si las ganas todas te quedas en negativo. Va detrás de esas",
                    cash - comprometido - importe,
                )
            )
            continue
        comprometido += importe
        delante.append(r.name)
        r.detail["committed_after"] = round(comprometido)

    # Los límites máximos también deben caber JUNTOS, no solo las pujas de referencia.
    remaining = max(0, cash - comprometido)
    for rec in pujas:
        if rec.verdict != "pujar":
            rec.detail["affordable_max"] = 0
            continue
        bid = float(rec.detail["bid_to_win"])
        extra = min(remaining, max(0, float(rec.detail["max_bid"]) - bid))
        rec.detail["affordable_max"] = int(bid + extra)
        rec.reasons = [reason for reason in rec.reasons if reason.code != "VEREDICTO"]
        rec.reasons.append(
            Reason(
                "VEREDICTO",
                f"Puja orientativa: {_money(bid)}. Límite con las otras compras propuestas: "
                f"{_money(rec.detail['affordable_max'])}. No garantiza ganar la subasta",
                rec.detail["affordable_max"],
                "saldo repartido entre las compras propuestas",
            )
        )
        remaining -= extra


def _lista(nombres: list[str]) -> str:
    if len(nombres) <= 1:
        return "".join(nombres) or "las anteriores"
    return ", ".join(nombres[:-1]) + " y " + nombres[-1]


def save(conn: Connection, recs: list[Recommendation]) -> int:
    """Reemplaza la foto vigente. **Una tanda vacía no borra la anterior.**

    Quedarse sin mercado es transitorio y normal: pasa mientras el mercado rota y pasaba cada
    mañana antes de que existieran los valores del día. Borrar primero y comprobar después dejaba
    la app sin ninguna recomendación hasta el siguiente recálculo; es mejor enseñar la última
    buena, con su antigüedad a la vista, que no enseñar nada."""
    if not recs:
        return 0
    conn.execute(SQL_CLEAR)
    rows = [
        {
            "kind": r.kind,
            "subject": {"player_id": r.player_id, "name": r.name, "verdict": r.verdict, **r.detail},
            "score": r.score,
            "reasons": [asdict(x) for x in r.reasons],
        }
        for r in recs
    ]
    conn.execute(SQL_SAVE, {"rows": json.dumps(rows, ensure_ascii=False)})
    return len(rows)


# El ciclo vigente es el último **con jugadores de la liga**. Las capturas a medio rotar de antes
# del 2026-09-20 dejaron en la tabla ciclos falsos con solo ventas de managers; este filtro los
# vuelve invisibles sin tener que borrarlos.
SQL_CURRENT_CYCLE = text(
    "SELECT max(cycle_end) FROM market_offer WHERE league_id = :league_id AND kind = 'marketPlayerLeague'"
)

SQL_LOG = text(
    "INSERT INTO recommendation_log (cycle_end, kind, player_id, verdict, score, subject) "
    "SELECT CAST(:cycle_end AS timestamptz), r.kind, r.player_id, r.verdict, r.score, r.subject "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) "
    "AS r(kind text, player_id text, verdict text, score numeric, subject jsonb) "
    "ON CONFLICT (cycle_end, kind, player_id) DO UPDATE SET "
    "verdict = EXCLUDED.verdict, score = EXCLUDED.score, subject = EXCLUDED.subject, "
    "last_seen_at = now()"
)


def save_log(conn: Connection, recs: list[Recommendation], *, league_id: str) -> int:
    """Congela una fila por ciclo de mercado y jugador, para poder juzgarnos después.

    `save` solo deja la foto vigente porque es lo que pinta la web, así que sin esto es imposible
    comprobar si una recomendación acertó (docs/criterio.md §7.11). La clave es el **ciclo**, no la
    hora: las pasadas horarias van actualizando la misma fila y la última antes del cierre —la que
    de verdad pudiste usar para decidir— queda congelada cuando el mercado rota."""
    if not recs:
        return 0
    cycle_end = conn.execute(SQL_CURRENT_CYCLE, {"league_id": league_id}).scalar()
    if cycle_end is None:
        return 0  # sin mercado capturado todavía no hay ciclo al que atribuirlo
    rows = [
        {
            "kind": r.kind,
            "player_id": r.player_id,
            "verdict": r.verdict,
            "score": r.score,
            "subject": {"name": r.name, **r.detail},
        }
        for r in recs
    ]
    conn.execute(SQL_LOG, {"cycle_end": cycle_end.isoformat(), "rows": json.dumps(rows, ensure_ascii=False)})
    return len(rows)


def recompute(conn: Connection, *, league_id: str, day: date, team_id: str | None) -> dict:
    # Con el ciclo ya cerrado y el nuevo sin publicar, el mercado vivo tiene cero jugadores: recalcular
    # borraría todas las pujas y dejaría solo las ventas. Se conserva la última foto buena, que la
    # web enseña con su hora, hasta que llegue el mercado nuevo.
    cycle_end = conn.execute(SQL_CURRENT_CYCLE, {"league_id": league_id}).scalar()
    if cycle_end is not None and hasattr(cycle_end, "tzinfo") and cycle_end <= datetime.now(UTC):
        return {"skipped": "el mercado está rotando: se conservan las recomendaciones del ciclo anterior"}
    recs = build(conn, league_id=league_id, day=day, team_id=team_id)
    saved = save(conn, recs)
    logged = save_log(conn, recs, league_id=league_id)
    return {
        "saved": saved,
        "logged": logged,
        "pujar": [r.name for r in recs if r.verdict == "pujar"],
        "no_pujar": sum(1 for r in recs if r.verdict == "no_pujar"),
        "vender": [r.name for r in recs if r.verdict == "vender"],
        "aguantar": [r.name for r in recs if r.verdict == "aguantar"],
    }


if __name__ == "__main__":  # pragma: no cover
    # python -m lfm.analysis.recommend recalcular: la misma cuenta que hace el job, sin pedir nada a LaLiga
    import sys
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    from lfm.config import settings
    from lfm.db.session import engine
    from lfm.jobs.light import my_team_id

    if len(sys.argv) > 1 and sys.argv[1] == "recalcular":
        with engine().begin() as c:
            print(recompute(c, league_id=settings.league_id, day=_dt.now(_UTC).date(), team_id=my_team_id(c)))
    else:
        print("uso: python -m lfm.analysis.recommend recalcular")
