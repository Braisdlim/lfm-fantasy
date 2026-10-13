"""Dificultad de calendario (Poisson encogido) y puntos esperados (Bayes empírico)."""

from types import SimpleNamespace

import pytest

from lfm.analysis import fixtures as fx
from lfm.analysis import points as pts


def match(local, visitor, ls, vs):
    return SimpleNamespace(l=local, v=visitor, ls=ls, vs=vs)


# Liga de juguete: A arrasa, D encaja de todo, B y C están en la media
MATCHES = [
    match("A", "B", 4, 0),
    match("A", "C", 3, 0),
    match("A", "D", 5, 0),
    match("B", "C", 1, 1),
    match("B", "D", 3, 1),
    match("C", "D", 2, 1),
    match("B", "A", 0, 2),
    match("C", "A", 1, 3),
    match("D", "A", 0, 4),
    match("C", "B", 1, 1),
    match("D", "B", 1, 2),
    match("D", "C", 0, 1),
]


def test_team_strength_separates_good_from_bad():
    s, mu = fx.team_strength(MATCHES)
    assert mu == pytest.approx(sum(m.ls + m.vs for m in MATCHES) / (2 * len(MATCHES)))
    assert s["A"].attack > s["D"].attack  # A marca mucho más
    assert s["D"].defence > s["A"].defence  # D encaja mucho más
    assert all(x.played == 6 for x in s.values())


def test_shrinkage_pulls_towards_the_league_average():
    poco = fx.team_strength(MATCHES, shrink=50.0)[0]
    mucho = fx.team_strength(MATCHES, shrink=0.0)[0]
    # con mucho encogimiento todos se parecen más a 1
    assert abs(poco["A"].attack - 1) < abs(mucho["A"].attack - 1)


def test_home_advantage_helps_the_home_side():
    s, mu = fx.team_strength(MATCHES)
    en_casa = fx.expected_goals(s, mu, "B", "C", home=True)
    fuera = fx.expected_goals(s, mu, "B", "C", home=False)
    assert en_casa > fuera


def test_clean_sheet_falls_as_expected_goals_against_rise():
    assert fx.clean_sheet(0) == 1.0
    assert fx.clean_sheet(1) > fx.clean_sheet(3)
    assert 0 < fx.clean_sheet(2.5) < 0.1


def test_unknown_teams_fall_back_to_the_league_average():
    s, mu = fx.team_strength(MATCHES)
    assert fx.expected_goals(s, mu, "desconocido", "A", home=True) == mu


# --- puntos ---------------------------------------------------------------------------------------


def test_shrunk_rate_trusts_the_player_more_as_games_pile_up():
    media_posicion = 4.0
    pocos = pts.shrunk_rate([10, 10], media_posicion)
    muchos = pts.shrunk_rate([10] * 20, media_posicion)
    assert media_posicion < pocos < muchos < 10
    assert pts.shrunk_rate([], media_posicion) == media_posicion


# Rivales de juguete: FLOJO encaja mucho y marca poco; FUERTE al revés
STRENGTH = {
    "FLOJO": fx.Strength(attack=0.6, defence=1.5, played=5),
    "FUERTE": fx.Strength(attack=1.6, defence=0.6, played=5),
    "MEDIO": fx.Strength(attack=1.0, defence=1.0, played=5),
}
MU = 1.4


def fixture(opponent, home=True, week=5):
    return fx.Fixture(week, "MIO", opponent, home, 0.0, 0.0, 0.0)


def test_forwards_are_judged_by_how_leaky_the_opponent_is():
    facil = pts.fixture_factor(pts.FWD, [fixture("FLOJO")], MU, STRENGTH)[0]
    dificil = pts.fixture_factor(pts.FWD, [fixture("FUERTE")], MU, STRENGTH)[0]
    medio = pts.fixture_factor(pts.FWD, [fixture("MEDIO")], MU, STRENGTH)[0]
    assert facil > medio > dificil


def test_defenders_are_judged_by_how_dangerous_the_opponent_is():
    facil = pts.fixture_factor(pts.DEF, [fixture("FLOJO")], MU, STRENGTH)[0]
    dificil = pts.fixture_factor(pts.DEF, [fixture("FUERTE")], MU, STRENGTH)[0]
    assert facil > 1 > dificil  # contra un rival flojo se guarda la portería a cero más veces


def test_the_factor_ignores_how_good_my_own_team_is():
    """La tasa del jugador ya recoge lo bueno que es su equipo: contarlo otra vez sería doble."""
    a = pts.fixture_factor(pts.FWD, [fx.Fixture(5, "BARCELONA", "MEDIO", True, 0, 0, 0)], MU, STRENGTH)[0]
    b = pts.fixture_factor(pts.FWD, [fx.Fixture(5, "GETAFE", "MEDIO", True, 0, 0, 0)], MU, STRENGTH)[0]
    assert a == b


def test_playing_at_home_helps_in_both_directions():
    casa = pts.fixture_factor(pts.FWD, [fixture("MEDIO", home=True)], MU, STRENGTH)[0]
    fuera = pts.fixture_factor(pts.FWD, [fixture("MEDIO", home=False)], MU, STRENGTH)[0]
    assert casa > fuera
    casa_def = pts.fixture_factor(pts.DEF, [fixture("MEDIO", home=True)], MU, STRENGTH)[0]
    fuera_def = pts.fixture_factor(pts.DEF, [fixture("MEDIO", home=False)], MU, STRENGTH)[0]
    assert casa_def > fuera_def


def test_fixture_factor_is_capped_so_the_calendar_never_decides_alone():
    brutal = {"X": fx.Strength(attack=0.01, defence=50.0, played=5)}
    assert pts.fixture_factor(pts.FWD, [fixture("X")], MU, brutal)[0] == 1.6
    imposible = {"X": fx.Strength(attack=50.0, defence=0.01, played=5)}
    assert pts.fixture_factor(pts.FWD, [fixture("X")], MU, imposible)[0] == 0.6


def test_unknown_opponents_leave_the_factor_neutral():
    assert pts.fixture_factor(pts.FWD, [fixture("nadie")], MU, STRENGTH)[0] == 1.0


def test_expected_combines_rate_and_calendar():
    means = {pts.FWD: 4.0}
    e = pts.expected([8, 8, 8, 8], pts.FWD, [fixture("FLOJO")], means, MU, STRENGTH, 1.0)
    assert e.played == 4 and e.rate > 4.0
    assert e.xpts > e.rate  # calendario favorable
    assert "J5" in e.detail


def test_a_player_who_never_scored_gets_no_sporting_value():
    """Sin jornadas puntuadas no hay evidencia de que juegue: atribuirle la media de su posición
    premiaría a los suplentes que nunca salen."""
    means = {pts.FWD: 4.0}
    e = pts.expected([], pts.FWD, [fixture("FLOJO")], means, MU, STRENGTH)
    assert e.played == 0 and e.xpts == 0.0
    assert e.rate == 4.0  # la tasa sigue siendo informativa, pero no se convierte en puntos


def test_expected_looks_at_one_gameweek_even_with_two_fixtures_ahead():
    """El horizonte debe coincidir con el de la reventa (7 días)."""
    means = {pts.MID: 4.0}
    dos = [fixture("MEDIO", week=5), fixture("MEDIO", home=False, week=6)]
    e = pts.expected([6, 6, 6, 6], pts.MID, dos, means, MU, STRENGTH, 1.0)
    assert e.xpts == pytest.approx(e.rate * e.fixture_factor)


def test_outcome_always_adds_up_to_one():
    for xgf, xga in ((1.4, 1.1), (0.2, 3.5), (4.0, 4.0), (0.0, 0.0)):
        g, e, p = fx.outcome(xgf, xga)
        assert abs(g + e + p - 1) < 1e-9, (xgf, xga)
        assert all(0 <= x <= 1 for x in (g, e, p))


def test_the_favourite_is_the_one_who_is_expected_to_score_more():
    g, _e, p = fx.outcome(2.1, 0.9)
    assert g > p
    assert g > 0.5
    g2, _e2, p2 = fx.outcome(0.9, 2.1)
    assert p2 > g2
    assert abs(g - p2) < 1e-9  # dar la vuelta al partido da la vuelta al resultado


def test_two_equal_teams_are_a_coin_toss_with_draws():
    g, e, p = fx.outcome(1.4, 1.4)
    assert abs(g - p) < 1e-9
    assert 0.2 < e < 0.32  # el empate ronda la cuarta parte, como en el futbol real


def test_a_goalless_pair_of_teams_can_only_draw():
    assert fx.outcome(0.0, 0.0) == (0.0, 1.0, 0.0)


def test_scores_is_the_complement_of_the_clean_sheet_of_the_rival():
    assert abs(fx.scores(1.6) - (1 - fx.clean_sheet(1.6))) < 1e-12
    assert fx.scores(0.0) == 0.0
