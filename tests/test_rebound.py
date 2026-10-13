"""Señales de rebote: solo pasan si el efecto aguanta en las dos mitades de la historia."""

import random
from datetime import date, timedelta
from types import SimpleNamespace

from lfm.analysis import bids, drift, rebound, recommend

START = date(2026, 7, 1)


def test_active_signals_match_full_history_including_yesterdays_role_median():
    values, avail = _history(effect=0.10)
    day = START + timedelta(days=79)
    # Una señal que solo apareció ayer necesita los precios del resto del
    # universo ayer: reducir la consulta a los candidatos perdería la mediana.
    for pid in values:
        values[pid][day - timedelta(days=1)] = 1_000_000
        values[pid][day] = 1_000_000
    values["0"][day - timedelta(days=1)] = 100_000
    for row in avail:
        if row.day >= day - timedelta(days=1):
            row.p = 0.8
            row.injured = False
    full = rebound.events(values, avail, [])
    assert rebound._known(full["barato_para_su_rol"], "0", day)
    ids = {"0", "1"}
    reduced = {
        pid: {d: v for d, v in series.items() if pid in ids or d >= day - timedelta(days=1)}
        for pid, series in values.items()
    }
    narrowed = rebound.events(reduced, [r for r in avail if r.day >= day - timedelta(days=8)], [])
    for name in set(full) | set(narrowed):
        for pid in ids:
            assert rebound._known(full.get(name, set()), pid, day) == rebound._known(
                narrowed.get(name, set()), pid, day
            )
    assert sum(map(len, reduced.values())) < sum(map(len, values.values())) * 0.04


def _history(effect: float, seed: int = 3):
    """80 días, 200 jugadores. Cada jugador cae unos días y, si `effect`, a algunos les llega el
    alta médica y rebotan; al resto no. Devuelve (valores, disponibilidad)."""
    rnd = random.Random(seed)
    values, avail = {}, []
    for pid in map(str, range(200)):
        serie, v = {}, 10e6
        vuelve = rnd.randrange(10, 70) if rnd.random() < 0.3 else None
        for i in range(80):
            d = START + timedelta(days=i)
            if vuelve is not None and vuelve < i <= vuelve + 7:  # el valor reacciona al día siguiente
                v *= 1 + effect / 7
            else:
                v *= 1 - 0.004 + rnd.gauss(0, 0.002)  # la mayoría baja despacio
            serie[d] = v
            lesionado = vuelve is not None and vuelve - 5 <= i < vuelve
            avail.append(SimpleNamespace(player_id=pid, day=d, p=0.5, injured=lesionado, position_id=3))
        values[pid] = serie
    return values, avail


def test_a_real_rebound_after_injury_passes_the_forward_check():
    values, avail = _history(effect=0.10)
    res = rebound.measure(values, rebound.events(values, avail, []))
    assert res["vuelve_lesion"]["passes"]
    assert res["vuelve_lesion"]["mean_7d"] > res["vuelve_lesion"]["control_mean"] + rebound.MIN_LIFT


def test_no_effect_no_signal():
    values, avail = _history(effect=-0.03)
    res = rebound.measure(values, rebound.events(values, avail, []))
    assert not res["vuelve_lesion"]["passes"]
    assert not res["gana_titularidad"]["passes"]  # nadie gana titularidad en esta historia


def test_a_passing_rebound_can_turn_a_falling_player_into_a_bid():
    row = SimpleNamespace(
        player_id="1", name="N", nickname="N", position_id=3, price=10e6, num_bids=0, value=10e6, status="ok"
    )
    cae = [10e6 * (1 - 0.01 * i) for i in range(12)]  # doce días bajando
    tabla = {
        "baseline": drift.Drift(-0.01, 0.2, 5000, "baseline"),
        "bajando 8+ días": drift.Drift(-0.10, 0.07, 800, "bajando 8+ días"),
    }
    ratios = [bids.Won(1.03, 10e6, None)] * 20
    sin = recommend.buy_recommendation(row, cae, tabla, ratios, cash=50e6)
    assert sin.verdict == "no_pujar"
    sig = rebound.Signal("vuelve_lesion", 60, 0.12, 0.8, -0.05)
    con = recommend.buy_recommendation(row, cae, tabla, ratios, cash=50e6, rebound=sig)
    assert con.verdict == "pujar" and con.detail["rebound"] == "vuelve de lesión"
    assert any(x.code == "REBOTE" and "60" in x.text for x in con.reasons)
