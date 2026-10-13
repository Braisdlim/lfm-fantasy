"""Diario de decisiones: emparejar entradas y salidas de mi plantilla."""

from datetime import UTC, datetime

from lfm.analysis.journal import build_holdings

ME = "m0"


def ev(t, pid, day, amount=None, manager="m0", manager2=None, was_mine=False):
    return {
        "activity_type": t,
        "player_id": pid,
        "happened_at": datetime(2026, 9, day, 19, 21, tzinfo=UTC),
        "amount": amount,
        "manager_id": manager,
        "manager2_id": manager2,
        "was_mine": was_mine,
    }


def test_buy_then_sell_is_one_closed_holding():
    [h] = build_holdings([ev(31, "p1", 1, 4e6), ev(33, "p1", 8, 5e6)], ME)
    assert h.entry_kind == "mercado" and h.paid == 4e6
    assert h.exit_kind == "venta_sistema" and h.received == 5e6


def test_open_holding_has_no_exit():
    [h] = build_holdings([ev(1, "p2", 3, 10e6, manager2="m9")], ME)
    assert h.entry_kind == "manager" and h.exit_at is None


def test_selling_an_initial_player_has_no_entry():
    [h] = build_holdings([ev(33, "p3", 5, 2e6)], ME)
    assert h.entry_kind == "inicial" and h.paid is None and h.received == 2e6


def test_sale_to_another_manager_and_clause_against_me():
    hs = build_holdings(
        [
            ev(31, "a", 1, 1e6),
            ev(1, "a", 4, 2e6, manager="m7", manager2=ME),  # se lo vendí a m7
            ev(31, "b", 1, 3e6),
            ev(32, "b", 6, 6e6, manager="m8", was_mine=True),  # me lo clausularon
            ev(32, "c", 6, 6e6, manager="m8"),  # clausulazo entre rivales: no me afecta
        ],
        ME,
    )
    kinds = {h.player_id: h.exit_kind for h in hs}
    assert kinds == {"a": "venta_manager", "b": "me_clausularon"}


def test_clause_i_paid_is_an_entry():
    [h] = build_holdings([ev(32, "d", 2, 7e6)], ME)
    assert h.entry_kind == "clausula" and h.paid == 7e6


def test_rebuy_after_selling_makes_two_holdings():
    hs = build_holdings([ev(31, "p", 1, 1e6), ev(33, "p", 2, 1.1e6), ev(31, "p", 5, 1.2e6)], ME)
    assert len(hs) == 2 and hs[0].exit_kind == "venta_sistema" and hs[1].exit_at is None
