"""Recomendador: distribución de pujas, deriva empírica y el veredicto que sale de compararlas."""

from types import SimpleNamespace

import pytest

from lfm.analysis import bids, drift, eleven, rebound, recommend

# --- pujas ganadoras -----------------------------------------------------------------------------


def test_percentile_returns_what_would_have_been_enough_to_win():
    xs = [1.0, 1.05, 1.10, 1.20, 2.00]
    assert bids.percentile(xs, 0.2) == 1.0
    assert bids.percentile(xs, 0.6) == 1.10
    assert bids.percentile(xs, 1.0) == 2.00


def test_bid_to_win_uses_the_price_band_when_there_is_enough_sample():
    # 12 baratos que necesitaron mucha prima, 12 caros que ganaron rozando el valor
    ratios = [bids.Won(1.30, 2e6, None)] * 12 + [bids.Won(1.01, 40e6, None)] * 12
    caro = bids.bid_to_win(ratios, 40e6, 0.7)
    barato = bids.bid_to_win(ratios, 2e6, 0.7)
    assert caro.band == "más de 20 M" and caro.ratio == pytest.approx(1.01)
    assert barato.band == "menos de 5 M" and barato.ratio == pytest.approx(1.30)
    assert caro.amount == round(40e6 * 1.01) and caro.n == 12


def test_bid_to_win_falls_back_to_the_whole_league_when_the_band_is_thin():
    ratios = [bids.Won(1.10, 40e6, None)] * 3 + [bids.Won(1.05, 2e6, None)] * 20
    r = bids.bid_to_win(ratios, 40e6, 0.5)
    assert r.band == "toda la liga" and r.n == 23


def test_bid_to_win_without_history_returns_nothing():
    assert bids.bid_to_win([], 10e6) is None


def test_a_single_winning_bid_is_not_enough_to_estimate_a_market():
    assert bids.bid_to_win([bids.Won(1.4, 10e6, None)], 10e6) is None


# --- deriva --------------------------------------------------------------------------------------


def test_streak_counts_consecutive_days_in_the_same_direction():
    assert drift.streak([10, 9, 8, 7]) == -3
    assert drift.streak([7, 8, 9]) == 2
    assert drift.streak([5, 5, 5]) == 0
    assert drift.streak([10, 9, 11]) == 1  # el último cambio manda


def test_bucket_names_are_readable():
    assert drift.bucket_of(-9) == "bajando 8+ días"
    assert drift.bucket_of(-1) == "bajando 1 día"
    assert drift.bucket_of(0) == "plano"
    assert drift.bucket_of(3) == "subiendo 3 días"


def test_build_table_measures_what_happened_after_each_state():
    # una serie que baja siempre: la celda "bajando" debe salir negativa
    series = {f"p{i}": [100 - j for j in range(30)] for i in range(20)}
    table = drift.build_table(series)
    assert table["baseline"].mean < 0
    caida = table["bajando 8+ días"]
    assert caida.mean < 0 and caida.up_rate == 0 and caida.n > 100


def test_expected_falls_back_to_baseline_when_the_cell_is_small():
    table = {
        "baseline": drift.Drift(-0.01, 0.2, 5000, "baseline"),
        "bajando 2 días": drift.Drift(-0.5, 0.0, 3, "bajando 2 días"),
    }
    # la serie empieza subiendo para que la racha quede DENTRO de ella: así se prueba lo que dice el
    # nombre (celda pequeña) y no el descarte por racha censurada, que tiene sus propios tests
    d = drift.expected(table, [10, 11, 10, 9])
    assert d.bucket == "baseline"  # n=3 es demasiado poco para fiarse


# --- veredicto -----------------------------------------------------------------------------------

TABLE = {"baseline": drift.Drift(0.0, 0.5, 5000, "baseline")}
# Con deriva positiva la operación puede compensar; con deriva cero, comprar al valor y revender
# al sistema no deja ventaja suficiente, y ese "no" es el comportamiento correcto.
SUBE = {"baseline": drift.Drift(0.08, 0.8, 5000, "baseline")}
CAE = {"baseline": drift.Drift(-0.10, 0.07, 5000, "baseline")}


def row(**kw):
    base = dict(
        player_id="1",
        name="Nombre",
        nickname="Apodo",
        position_id=3,
        price=10e6,
        num_bids=0,
        value=10e6,
        status="ok",
    )
    return SimpleNamespace(**{**base, **kw})


def test_buy_says_bid_when_winning_costs_less_than_what_you_recover():
    # hace falta 1,02 × valor para ganar y con deriva +8 % la reventa deja margen de sobra
    ratios = [bids.Won(1.02, 10e6, None)] * 20
    r = recommend.buy_recommendation(row(), [10e6] * 10, SUBE, ratios, cash=50e6)
    assert r.verdict == "pujar" and r.score > 0
    assert r.detail["bid_to_win"] == round(10e6 * 1.02)
    assert any(x.code == "PUJA_GANAR" for x in r.reasons)
    assert any("Puja orientativa" in x.text for x in r.reasons)


def test_buy_says_do_not_bid_when_winning_costs_more_than_you_recover():
    ratios = [bids.Won(1.40, 10e6, None)] * 20  # en esta liga se sobrepuja mucho
    r = recommend.buy_recommendation(row(), [10e6] * 10, TABLE, ratios, cash=50e6)
    assert r.verdict == "no_pujar" and r.score < 0
    assert any("perderías" in x.text for x in r.reasons)


def test_buy_flags_lack_of_cash_separately_from_a_bad_deal():
    ratios = [bids.Won(1.02, 10e6, None)] * 20
    r = recommend.buy_recommendation(row(), [10e6] * 10, SUBE, ratios, cash=1e6)
    assert r.verdict == "sin_saldo" and any(x.code == "SALDO" for x in r.reasons)


def test_buy_never_recommends_an_injured_player():
    ratios = [bids.Won(1.0, 10e6, None)] * 20
    r = recommend.buy_recommendation(row(status="injured"), [10e6] * 10, TABLE, ratios, cash=50e6)
    assert r.verdict == "no_pujar" and any(x.code == "VETO" for x in r.reasons)


def test_every_reason_carries_a_figure_or_an_explicit_none():
    ratios = [bids.Won(1.02, 10e6, None)] * 20
    r = recommend.buy_recommendation(row(), [10e6] * 10, TABLE, ratios, cash=50e6)
    assert r.reasons and all(x.code and x.text for x in r.reasons)


def test_sell_only_fires_after_a_long_fall():
    subiendo = [100 + i for i in range(10)]
    assert recommend.sell_recommendation(row(), subiendo, TABLE) is None
    bajando = [100 - i for i in range(10)]
    r = recommend.sell_recommendation(row(), bajando, TABLE)
    assert r is not None and r.kind == "sell" and r.detail["streak"] <= -recommend.SELL_STREAK
    assert any(x.code == "RACHA" for x in r.reasons)


def test_without_drift_the_break_even_bid_is_exactly_the_value():
    """Comprar al valor y revender al sistema deja un 3 % bruto, que es justo la ventaja exigida.
    Así que sin deriva el techo es el valor: un euro por encima ya no compensa."""
    plano = recommend.buy_recommendation(
        row(), [10e6] * 10, TABLE, [bids.Won(1.00, 10e6, None)] * 20, cash=50e6
    )
    assert plano.detail["max_bid"] == 10_000_000
    caro = recommend.buy_recommendation(
        row(), [10e6] * 10, TABLE, [bids.Won(1.05, 10e6, None)] * 20, cash=50e6
    )
    assert caro.verdict == "no_pujar"


def test_numbers_are_written_in_spanish():
    assert recommend._es(2401, 0) == "2.401"
    assert recommend._es(1.0333, 3) == "1,033"
    assert recommend._money(35_940_000) == "35,94 M"
    assert recommend._pct(0.119) == "+11,9 %"
    assert recommend._pct(-0.105) == "−10,5 %"


def test_an_injury_the_official_app_has_not_published_yet_is_said_but_does_not_veto():
    """La probabilidad de titular ya recorta los puntos: vetar además contaría dos veces lo mismo."""
    ratios = [bids.Won(1.02, 10e6, None)] * 20
    r = recommend.buy_recommendation(row(), [10e6] * 10, SUBE, ratios, cash=50e6, flags={"injured": True})
    assert any(x.code == "LESION" for x in r.reasons)
    assert r.verdict == "pujar"


def test_no_injury_reason_when_the_official_app_already_says_it():
    ratios = [bids.Won(1.0, 10e6, None)] * 20
    r = recommend.buy_recommendation(
        row(status="injured"), [10e6] * 10, TABLE, ratios, cash=50e6, flags={"injured": True}
    )
    assert not any(x.code == "LESION" for x in r.reasons)
    assert any(x.code == "VETO" for x in r.reasons)


def test_reason_codes_are_unique_so_the_list_can_be_keyed_by_them():
    ratios = [bids.Won(1.02, 10e6, None)] * 20
    r = recommend.buy_recommendation(
        row(), [10e6] * 10, SUBE, ratios, cash=50e6, flags={"injured": True, "suspended": True}
    )
    codes = [x.code for x in r.reasons]
    assert len(codes) == len(set(codes))


# --- robustez: qué pasa cuando falta el dato ------------------------------------------------------


class SaveConn:
    """Registra el SQL que se ejecuta, para comprobar si llega a borrar."""

    def __init__(self):
        self.sql: list[str] = []

    def execute(self, stmt, params=None):
        self.sql.append(str(stmt))
        return None


def test_an_empty_batch_never_wipes_the_previous_one():
    """Quedarse sin mercado es transitorio (rota el mercado, o aún no hay valores del día).
    Borrar primero y comprobar después dejaba la app sin ninguna recomendación."""
    conn = SaveConn()
    assert recommend.save(conn, []) == 0
    assert not any("DELETE" in s for s in conn.sql)


def test_a_real_batch_does_replace_the_previous_one():
    conn = SaveConn()
    r = recommend.Recommendation(kind="buy", player_id="1", name="X", score=1.0, verdict="pujar")
    assert recommend.save(conn, [r]) == 1
    assert any("DELETE" in s for s in conn.sql)
    assert any("INSERT" in s for s in conn.sql)


def test_momentum_raises_the_bid_for_a_player_everyone_can_see_rising():
    """El caso real: Xavi Espart subio de 12,3 a 23,8 M en seis dias y la app recomendo pujar
    24,57 M, un 3 % sobre su valor. Medido en 83 fichajes, la prima que hizo falta pasa de
    1,026 x en los que suben poco a 1,221 x en los que suben mas del 15 %."""
    tranquilos = [bids.Won(1.00, 10e6, 0.01) for _ in range(20)]
    disparados = [bids.Won(1.30, 10e6, 0.30) for _ in range(10)]
    ratios = tranquilos + disparados

    sin_racha = bids.bid_to_win(ratios, 10e6, 0.7, player_momentum=0.01)
    con_racha = bids.bid_to_win(ratios, 10e6, 0.7, player_momentum=0.37)
    assert con_racha.amount > sin_racha.amount
    assert con_racha.momentum_band == "subiendo mucho"
    assert con_racha.momentum_n == 10


def test_without_enough_sample_the_momentum_does_not_move_the_bid():
    """Con cuatro observaciones no se corrige nada: seria creerse una casualidad."""
    ratios = [bids.Won(1.00, 10e6, 0.01) for _ in range(20)] + [bids.Won(1.90, 10e6, 0.30) for _ in range(4)]
    r = bids.bid_to_win(ratios, 10e6, 0.7, player_momentum=0.37)
    assert r.momentum_factor == 1.0
    assert r.momentum_band is None


def test_the_momentum_correction_is_capped():
    """Con muestras pequeñas, una correccion suelta seria creerse una extrapolacion."""
    ratios = [bids.Won(1.00, 10e6, 0.01) for _ in range(30)] + [bids.Won(9.00, 10e6, 0.30) for _ in range(9)]
    r = bids.bid_to_win(ratios, 10e6, 0.7, player_momentum=0.37)
    assert r.momentum_factor == bids.MOMENTUM_FACTOR_RANGE[1]


def test_a_dominant_group_leaves_the_correction_at_one_instead_of_exaggerating_it():
    """Si un tramo es un tercio de la muestra, la referencia se contamina con el y el factor tiende
    a 1. Es un fallo conservador —corrige de menos, nunca de mas— y conviene tenerlo escrito: con
    la muestra real (11 de 83) no ocurre."""
    ratios = [bids.Won(1.00, 10e6, 0.01) for _ in range(20)] + [bids.Won(9.00, 10e6, 0.30) for _ in range(10)]
    r = bids.bid_to_win(ratios, 10e6, 0.7, player_momentum=0.37)
    assert r.momentum_factor == 1.0


def test_momentum_reads_the_last_three_days_of_the_series():
    assert bids.momentum([10.0, 10.0, 10.0, 11.0]) == pytest.approx(0.1)
    assert bids.momentum([10.0, 20.0]) is None  # serie corta: no se inventa
    assert bids.momentum(None) is None
    assert bids.momentum([0.0, 1.0, 2.0, 3.0]) is None  # sin valor de partida no hay ratio


# --- encaje en tu once y saldo conjunto (2026-09-20) ---------------------------------------------


GK, DF, MD, FW = eleven.GOALKEEPER, eleven.DEFENDER, eleven.MIDFIELD, eleven.STRIKER


def _squad(gk=1, df=4, md=4, fw=3, xpts=4.0):
    out, n = [], 0
    for pos, k in ((GK, gk), (DF, df), (MD, md), (FW, fw)):
        for _ in range(k):
            n += 1
            out.append(eleven.Pick(f"s{n}", f"J{n}", pos, xpts))
    return out


def test_a_player_who_would_sit_on_the_bench_adds_no_sporting_value():
    # En el fantasy gratuito el suplente no puntúa: sus puntos no pueden subir la puja máxima
    fit = recommend.buy_fit(_squad(xpts=6.0), eleven.Pick("c", "C", MD, 2.0))
    assert fit.gain == 0 and not fit.completes
    ratios = [bids.Won(1.02, 10e6, None)] * 20
    r = recommend.buy_recommendation(row(), [10e6] * 10, SUBE, ratios, cash=50e6, fit=fit)
    assert r.detail["sport_value"] == 0
    assert any(x.code == "ENCAJE" and "suplente" in x.text for x in r.reasons)


def test_a_player_who_enters_the_eleven_counts_only_what_he_improves():
    fit = recommend.buy_fit(_squad(xpts=4.0), eleven.Pick("c", "C", MD, 7.0))
    assert fit.gain == pytest.approx(3.0) and fit.replaces  # sustituye a un medio de 4


def test_a_goalkeeper_is_the_most_urgent_buy_when_you_have_none():
    fit = recommend.buy_fit(_squad(gk=0), eleven.Pick("c", "C", GK, 3.0))
    assert fit.completes and fit.gain == 3.0


def test_selling_your_only_goalkeeper_is_never_advised():
    fit = recommend.sell_fit(_squad(), "s1")
    assert fit.breaks and "1 portero" in fit.missing
    cae = [10e6 * (1 - 0.02 * i) for i in range(12)]
    r = recommend.sell_recommendation(row(position_id=GK), cae, CAE, fit=fit)
    assert r.verdict == "aguantar" and any(x.code == "ENCAJE" for x in r.reasons)


def test_selling_a_bench_player_costs_no_points():
    squad = _squad(df=5)  # 1-5-4-3: sobra uno
    squad[5] = eleven.Pick("s6", "J6", DF, 0.5)  # el peor defensa, que se queda fuera del once
    assert recommend.sell_fit(squad, "s6").gain == pytest.approx(0.0)


def test_bids_are_recommended_together_within_your_cash():
    ratios = [bids.Won(1.02, 10e6, None)] * 20
    a = recommend.buy_recommendation(row(player_id="a", nickname="A"), [10e6] * 10, SUBE, ratios, cash=15e6)
    b = recommend.buy_recommendation(row(player_id="b", nickname="B"), [10e6] * 10, SUBE, ratios, cash=15e6)
    assert a.verdict == b.verdict == "pujar"  # cada una, sola, cabe
    recommend.apply_budget([a, b], 15e6)
    assert [a.verdict, b.verdict] == ["pujar", "sin_saldo"]  # juntas, no
    assert any(x.code == "SALDO" and "A" in x.text for x in b.reasons)
    assert not any(x.code == "VEREDICTO" for x in b.reasons)


def test_your_own_bet_is_never_sold_on_a_market_streak():
    # Caso Tchouaméni: cinco días bajando unas décimas y la apuesta es que gane la titularidad
    from datetime import datetime

    cae = [20e6 * (1 - 0.003 * i) for i in range(12)]
    tesis = {"created_at": datetime(2026, 9, 10), "entry_value": 20e6, "note": "titular del Madrid"}
    r = recommend.sell_recommendation(row(value=cae[-1]), cae, TABLE, thesis=tesis)
    assert r.verdict == "aguantar" and r.detail["thesis"]
    apuesta = next(x for x in r.reasons if x.code == "APUESTA")
    assert "10/09" in apuesta.text and "titular del Madrid" in apuesta.text and apuesta.value < 0


def test_a_fall_that_has_nearly_stopped_is_not_worth_selling():
    # Caso Tchouaméni: 39 días bajando pero ya casi plano. «Frena la caída» separa (n=145): a 7
    # días cambiaron +0,5 % frente al −9,9 % de los que seguían cayendo.
    cae = [34e6 * (1 - 0.02 * i) for i in range(10)] + [22.2e6, 22.15e6, 22.06e6]
    frena = rebound.Signal("frena_la_caida", 145, 0.005, 0.33, -0.099, rebound=False)
    r = recommend.sell_recommendation(row(value=22.06e6), cae, CAE, signal=frena)
    assert r.verdict == "aguantar" and r.score == 0
    assert any(x.code == "FRENA" for x in r.reasons)
    sin = recommend.sell_recommendation(row(value=22.06e6), cae, CAE)
    assert sin.verdict == "vender"


def test_a_signal_that_only_stops_the_fall_is_not_labelled_as_a_rebound():
    ratios = [bids.Won(1.03, 10e6, None)] * 20
    frena = rebound.Signal("frena_la_caida", 145, 0.005, 0.33, -0.099, rebound=False)
    cae = [10e6 * (1 - 0.01 * i) for i in range(12)]
    r = recommend.buy_recommendation(row(), cae, CAE, ratios, cash=50e6, rebound=frena)
    assert r.detail["rebound"] is None and any(x.code == "FRENA" for x in r.reasons)


def test_bid_reference_respects_the_actual_minimum_price():
    r = recommend.buy_recommendation(
        row(price=11e6), [10e6] * 10, SUBE, [bids.Won(0.95, 10e6, None)] * 20, cash=50e6
    )
    assert r.detail["bid_to_win"] == 11e6
    assert r.verdict == "no_pujar"


def test_maximums_fit_together_and_never_exceed_the_economic_ceiling():
    ratios = [bids.Won(1.02, 10e6, None)] * 20
    recs = [
        recommend.buy_recommendation(row(player_id=str(i)), [10e6] * 10, SUBE, ratios, cash=21e6)
        for i in range(2)
    ]
    recommend.apply_budget(recs, 21e6)
    assert sum(r.detail["affordable_max"] for r in recs) <= 21e6
    assert all(r.detail["bid_to_win"] <= r.detail["affordable_max"] <= r.detail["max_bid"] for r in recs)


def test_empty_value_history_cannot_recommend_a_profitable_bid():
    r = recommend.buy_recommendation(row(), [], SUBE, [bids.Won(1, 10e6, None)] * 20, cash=50e6)
    assert r.verdict == "sin_datos"


def test_holds_can_be_included_without_turning_a_short_fall_into_a_sell_signal():
    r = recommend.sell_recommendation(row(), [100, 110, 100], CAE, include_holds=True)
    assert r.verdict == "aguantar"


def test_an_incomplete_squad_does_not_make_everyone_a_bench_player():
    fit = recommend.sell_fit(_squad(gk=0), "s2")
    assert fit.incomplete
    r = recommend.sell_recommendation(row(), [100 - i for i in range(12)], CAE, fit=fit)
    assert r.verdict == "aguantar" and r.detail["incomplete_eleven"]
    assert not any("No juega en tu once" in x.text for x in r.reasons)
