"""Comprobar después si la recomendación acertó, con hechos y no con supuestos."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

from lfm.analysis import calibration as cal

CICLO = datetime(2026, 9, 1, 17, 21, tzinfo=UTC)


class FakeConn:
    """Devuelve valores por consulta según el SQL que se le pide."""

    def __init__(self, valores=None, pagado=None):
        self.valores = valores or {}  # 'YYYY-MM-DD' -> valor
        self.pagado = pagado
        self.guardado = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        if "player_value_daily" in sql:
            return SimpleNamespace(scalar=lambda: self.valores.get(params["day"]))
        if "league_activity" in sql:
            return SimpleNamespace(scalar=lambda: self.pagado)
        self.guardado.append(params)
        return SimpleNamespace(scalar=lambda: None)


def fila(kind="buy", verdict="pujar", subject=None):
    return SimpleNamespace(
        cycle_end=CICLO,
        kind=kind,
        player_id="p1",
        verdict=verdict,
        score=1.0,
        subject=subject or {"value": 10e6, "bid_to_win": 10.3e6, "drift": 0.08},
    )


def test_a_buy_that_rose_is_scored_as_profit():
    conn = FakeConn(valores={"2026-09-01": 10e6, "2026-09-08": 12e6}, pagado=10.1e6)
    o = cal.evaluate(conn, fila())
    assert o.sold is True and o.paid == 10.1e6
    assert o.would_have_won is True  # pujábamos 10,3 y se fue por 10,1
    assert o.real_return == 0.2
    assert o.profit_if_taken == 12e6 * 1.03 - 10.3e6  # se revende al sistema


def test_a_buy_that_fell_is_scored_as_a_loss():
    conn = FakeConn(valores={"2026-09-01": 10e6, "2026-09-08": 8e6}, pagado=10.1e6)
    o = cal.evaluate(conn, fila())
    assert o.real_return < 0 and o.profit_if_taken < 0


def test_a_bid_that_would_not_have_won_is_recorded_as_such():
    conn = FakeConn(valores={"2026-09-01": 10e6, "2026-09-08": 11e6}, pagado=15e6)
    o = cal.evaluate(conn, fila())
    assert o.would_have_won is False  # se fue por 15 y nosotros pujábamos 10,3


def test_a_player_nobody_bought_leaves_the_bid_unjudged():
    """Sin fichaje no se sabe cuánto hacía falta: inventarlo sería peor que no decir nada."""
    conn = FakeConn(valores={"2026-09-01": 10e6, "2026-09-08": 11e6}, pagado=None)
    o = cal.evaluate(conn, fila())
    assert o.sold is False and o.would_have_won is None


def test_selling_is_judged_by_the_fall_it_avoided():
    conn = FakeConn(valores={"2026-09-01": 10e6, "2026-09-08": 9e6})
    o = cal.evaluate(conn, fila(kind="sell", verdict="vender", subject={"value": 10e6}))
    assert o.profit_if_taken == (10e6 - 9e6) * 1.03  # vender evitó perder un millón


def test_a_sale_that_would_have_recovered_is_scored_against_us():
    conn = FakeConn(valores={"2026-09-01": 10e6, "2026-09-08": 11e6})
    o = cal.evaluate(conn, fila(kind="sell", verdict="vender", subject={"value": 10e6}))
    assert o.profit_if_taken < 0  # haber aguantado era mejor


def test_without_a_later_value_nothing_is_invented():
    conn = FakeConn(valores={"2026-09-01": 10e6})
    o = cal.evaluate(conn, fila())
    assert o.value_after is None and o.real_return is None and o.profit_if_taken is None


# --- el cuadro de mando ---------------------------------------------------------------------------


class ReportConn:
    def __init__(self, filas):
        self.filas = filas

    def execute(self, stmt, params=None):
        return SimpleNamespace(all=lambda: self.filas)


def scored(verdict, profit, won=None):
    return SimpleNamespace(
        kind="buy",
        verdict=verdict,
        subject={},
        outcome=json.dumps({"profit_if_taken": profit, "would_have_won": won}),
    )


def test_the_report_separates_verdicts_and_always_carries_the_sample_size():
    filas = [
        scored("pujar", 1e6, True),
        scored("pujar", 2e6, True),
        scored("pujar", -1e6, False),
        scored("no_pujar", -5e5),
    ]
    r = cal.report(ReportConn(filas))
    assert r["total"] == 4
    p = r["por_veredicto"]["pujar"]
    assert p["n"] == 3 and p["tasa_acierto"] == 2 / 3
    assert p["beneficio"] == 2e6 and p["puja_bastaba"] == 2 / 3
    assert r["por_veredicto"]["no_pujar"]["n"] == 1


def test_with_nothing_measurable_the_rates_are_none_not_zero():
    """Un cero se lee como 'falla siempre'; lo cierto es que aún no se sabe."""
    r = cal.report(ReportConn([scored("pujar", None)]))
    p = r["por_veredicto"]["pujar"]
    assert p["n"] == 1 and p["tasa_acierto"] is None and p["beneficio_medio"] is None
