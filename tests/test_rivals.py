"""Radar de rivales: huecos, estilo de fichaje y quién podría pujar."""

from lfm.analysis import rivals
from lfm.analysis.rivals import build, needs, needs_text, style


def test_full_squad_can_field():
    n = needs({1: 1, 2: 4, 3: 4, 4: 2})
    assert n.can_field and not n.missing


def test_missing_goalkeeper_is_the_only_need():
    n = needs({1: 0, 2: 4, 3: 4, 4: 2})
    assert not n.can_field and n.missing == {1: 1}
    assert needs_text(n) == "Le falta 1 portero para alinear."


def test_several_needs_read_naturally():
    assert needs_text(needs({1: 0, 2: 1, 3: 4, 4: 2})) == "Le falta 1 portero y 3 defensas para alinear."
    assert (
        needs_text(needs({2: 1, 3: 1, 4: 2}))
        == "Le falta 1 portero, 4 defensas y 2 centrocampistas para alinear."
    )


def test_picks_the_cheapest_formation_to_complete():
    # 2 defensas, 5 medios, 3 delanteros: el 3-4-3 o el 3-5-2 solo piden un defensa más
    n = needs({1: 1, 2: 2, 3: 5, 4: 3})
    assert n.missing == {2: 1}


def test_style_needs_three_cases_for_the_overpay():
    rows = [
        {"activity_type": 31, "amount": 1.1e6, "value": 1e6},
        {"activity_type": 31, "amount": 1.3e6, "value": 1e6},
        {"activity_type": 32, "amount": 5e6, "value": 4e6},
    ]
    s = style(rows)
    assert s.signings == 2 and s.clauses == 1 and s.overpay_median is None
    s = style(rows + [{"activity_type": 31, "amount": 1.2e6, "value": 1e6}])
    assert abs(s.overpay_median - 0.2) < 1e-9 and s.overpay_cases == 3


TEAMS = [
    {
        "team_id": "me",
        "manager_id": "m0",
        "manager_name": "Demo Manager",
        "is_me": True,
        "cash": 9e6,
        "uncertainty": 0,
    },
    {
        "team_id": "t1",
        "manager_id": "m1",
        "manager_name": "Iago",
        "is_me": False,
        "cash": 3e6,
        "uncertainty": 1e6,
    },
]


def squad(team, pos_counts, injured_pos=None):
    out = []
    for pos, k in pos_counts.items():
        for i in range(k):
            out.append(
                {
                    "team_id": team,
                    "player_id": f"{team}{pos}{i}",
                    "position_id": pos,
                    "status": "ok",
                    "injured": pos == injured_pos and i == 0,
                    "suspended": False,
                }
            )
    return out


def test_injured_players_do_not_count_and_market_fits_the_need():
    sq = squad("t1", {1: 1, 2: 4, 3: 4, 4: 2}, injured_pos=1)
    market = [
        {"player_id": "gk1", "name": "Portero barato", "position_id": 1, "sale_price": 2.5e6},
        {"player_id": "gk1b", "name": "Portero intermedio", "position_id": 1, "sale_price": 3.5e6},
        {"player_id": "gk2", "name": "Portero caro", "position_id": 1, "sale_price": 9e6},
        {"player_id": "st1", "name": "Delantero", "position_id": 4, "sale_price": 1e6},
    ]
    [f] = build(TEAMS, sq, [], market)
    assert f["manager_name"] == "Iago" and not f["can_field"]
    assert f["missing"] == {"portero": 1}
    # El desfase de mi saldo no amplía el presupuesto conocido de este rival.
    assert [x["player_id"] for x in f["could_bid"]] == ["gk1"]


def test_me_is_not_in_the_radar():
    assert all(f["team_id"] != "me" for f in build(TEAMS, squad("t1", {1: 1}), [], []))


def test_recompute_skips_without_table():
    class C:
        def execute(self, *a, **k):
            class R:
                def scalar(self_inner):
                    return None

            return R()

    assert "skipped" in rivals.recompute(C(), league_id="L", day=None)
