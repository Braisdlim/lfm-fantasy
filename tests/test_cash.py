"""Saldo estimado: importes reales del feed, sin trasladar mis gastos ocultos a los rivales."""

from datetime import UTC, datetime, timedelta

from lfm.analysis.cash import INITIAL_BUDGET, estimate, manual_raise, observed_clause_spend


def flows(**kw):
    base = {"team_id": "T", "manager_name": "x", "is_me": False, "income": 0, "expense": 0, "events": 0}
    return {**base, **kw}


def test_my_row_uses_the_real_balance_and_has_no_uncertainty():
    rows = estimate([flows(team_id="A", is_me=True, income=50, expense=20)], my_money=INITIAL_BUDGET + 34)
    assert rows[0]["cash_estimate"] == INITIAL_BUDGET + 34
    assert rows[0]["uncertainty"] == 0 and rows[0]["method"] == "api"


def test_my_unexplained_difference_is_not_assigned_to_rivals():
    # Mi diferencia de 4 no demuestra que los rivales hayan ingresado también 4.
    rows = estimate(
        [
            flows(team_id="A", is_me=True, income=10, expense=20),
            flows(team_id="B", manager_name="rival", income=5, expense=1),
        ],
        my_money=INITIAL_BUDGET - 10 + 20 - 20 + 4 + 20 - 20,  # = INITIAL - 10 + 4
    )
    mine, rival = rows
    assert mine["cash_estimate"] == INITIAL_BUDGET - 6
    assert rival["cash_estimate"] == INITIAL_BUDGET + 4
    assert rival["uncertainty"] == 4 and rival["method"] == "activity;observed_clauses;own_gap:4"


def test_without_my_real_balance_there_is_no_offset():
    rows = estimate([flows(team_id="B", income=7, expense=3)], my_money=None)
    assert rows[0]["cash_estimate"] == INITIAL_BUDGET + 4
    assert rows[0]["uncertainty"] == 0


def test_sales_to_another_manager_count_as_income_for_the_seller():
    # income ya viene agregado por SQL; aquí se comprueba que la suma se respeta tal cual
    rows = estimate([flows(team_id="B", income=1_000_000, expense=0)], my_money=None)
    assert rows[0]["cash_estimate"] == INITIAL_BUDGET + 1_000_000


def test_observed_clause_spend_is_deducted_only_from_that_rival():
    rows = estimate(
        [flows(team_id="A", is_me=True), flows(team_id="B"), flows(team_id="C")],
        my_money=INITIAL_BUDGET,
        clause_spend={"B": 5_000_000},
    )
    assert [r["cash_estimate"] for r in rows] == [INITIAL_BUDGET, INITIAL_BUDGET - 5_000_000, INITIAL_BUDGET]
    assert rows[1]["clause_spend_observed"] == 5_000_000


def test_manual_raise_ignores_market_updates_and_value_glitches():
    assert manual_raise(10_000_000, 10_000_000, 11_000_000, 11_000_000) == 0
    assert manual_raise(9_854_002, 9_854_002, 10_191_421, 5_207_753) == 0
    assert manual_raise(134_911_805, 134_911_805, 145_971_067, 135_971_067) == 10_000_000
    assert manual_raise(7_443_556, 7_443_556, 9_093_521, 7_443_521) == 1_650_000


def test_observed_spend_skips_initial_squad_and_intervening_transfer():
    start = datetime(2026, 9, 8, tzinfo=UTC)

    def snapshot(clause):
        return {"players": [{"buyoutClause": clause, "playerMaster": {"id": 7, "marketValue": 5_000_000}}]}

    snaps = [
        ("/leagues/L/teams/A", start, snapshot(7_000_000)),
        ("/leagues/L/teams/A", start + timedelta(days=1), snapshot(9_000_000)),
        ("/leagues/L/teams/A", start + timedelta(days=2), snapshot(10_000_000)),
    ]
    result = observed_clause_spend(snaps, [("7", start + timedelta(days=1, hours=12))], {"A"})
    assert result == {"A": 1_000_000}
