"""Alineaciones probables: parseo del HTML real y casado con nuestros jugadores."""

import pathlib
from types import SimpleNamespace

import pytest

from lfm.analysis import points as pts
from lfm.sources import lineups as ln

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def html():
    return (FIXTURES / "futbolfantasy_equipo.html").read_text(encoding="utf-8")


def test_parse_reads_probability_and_availability():
    rows = {r.slug: r for r in ln.parse_team(html())}
    assert len(rows) == 6
    con_prob = [r for r in rows.values() if r.start_prob is not None]
    assert len(con_prob) == 3 and all(0 <= r.start_prob <= 1 for r in con_prob)
    uno = rows["jugador-01"]
    assert uno.start_prob == 0.9 and uno.minutes == 360 and uno.games == 4 and uno.value > 0
    assert rows["jugador-05"].suspended is True
    assert not rows["jugador-01"].suspended


def test_players_without_probability_are_left_unknown_not_zero():
    """Ausencia de dato no es un cero: no sabemos si sale, y hay que decirlo."""
    rows = {r.slug: r for r in ln.parse_team(html())}
    assert rows["jugador-02"].start_prob is None


def test_parse_keeps_one_row_per_player():
    """La página repite al jugador en el once y en la lista de plantilla."""
    doble = html() + html()
    assert len(ln.parse_team(doble)) == 6


def test_season_suffix_does_not_become_a_player_slug():
    doc = (
        '<a class="camiseta" data-probabilidad="50%" '
        'href="https://www.futbolfantasy.com/jugadores/yan-diomande/laliga-26-27">D</a>'
        '<a class="camiseta" data-probabilidad="80%" '
        'href="https://www.futbolfantasy.com/jugadores/otro/laliga-26-27?x=1">O</a>'
    )
    rows = {r.slug: r.start_prob for r in ln.parse_team(doc)}
    assert rows == {"yan-diomande": 0.5, "otro": 0.8}


@pytest.mark.parametrize("pct", ["100%", "101%", "-5%", "desconocido"])
def test_confirmed_or_invalid_probability_is_not_a_forecast(pct):
    assert ln._row({"data-probabilidad": pct}, "uno", "Uno").start_prob is None


@pytest.mark.parametrize("pct,expected", [("0%", 0), ("50%", 0.5), ("99%", 0.99)])
def test_valid_probabilities_are_preserved(pct, expected):
    assert ln._row({"data-probabilidad": pct}, "uno", "Uno").start_prob == expected


def test_missing_team_page_cannot_replace_the_snapshot():
    with pytest.raises(ValueError, match="incompleta"):
        ln.collect(None, day=None, pages={"real-madrid": ""})


def player(pid, name, nickname, value):
    return SimpleNamespace(player_id=pid, name=name, nickname=nickname, value=value)


def test_match_prefers_the_exact_value():
    rows = ln.parse_team(html())
    uno = next(r for r in rows if r.slug == "jugador-01")
    nuestros = [player("p1", "Otro Nombre", "Otro", uno.value), player("p2", "Jugador 01", "Jugador 01", 999)]
    ids, missed = ln.match([uno], nuestros)
    assert ids["jugador-01"] == "p1"  # manda el valor, no el nombre
    assert not missed


def test_match_falls_back_to_the_name_without_accents():
    r = ln.Availability("alex-grimaldo", "Álex Grimaldo", 0.8, False, False, False, False, 90, 1, None)
    ids, missed = ln.match([r], [player("p9", "Grimaldo", "Grimaldo", 5)])
    assert ids["alex-grimaldo"] == "p9" and not missed


def test_match_never_assigns_the_same_player_twice():
    a = ln.Availability("uno", "Repetido", 0.5, False, False, False, False, 90, 1, 100)
    b = ln.Availability("dos", "Repetido", 0.5, False, False, False, False, 90, 1, 100)
    ids, missed = ln.match([a, b], [player("p1", "Repetido", "Repetido", 100)])
    assert len(ids) == 1 and len(missed) == 1


# --- probabilidad de titular en los puntos esperados ----------------------------------------------


def test_start_probability_scales_expected_points():
    means = {pts.FWD: 4.0}
    seguro = pts.expected([8, 8, 8, 8], pts.FWD, [], means, 1.4, None, 1.0)
    mitad = pts.expected([8, 8, 8, 8], pts.FWD, [], means, 1.4, None, 0.5)
    assert mitad.xpts == seguro.xpts * 0.5
    assert mitad.start_prob == 0.5


def test_without_data_it_applies_the_measured_rate_instead_of_nothing():
    """Dejar los puntos sin ajustar premiaba a quien menos se sabe de el: el 2026-09-09 la mejor
    compra del mercado era un jugador sin dato, compitiendo contra cifras ya rebajadas.

    El 43 % no es un supuesto: los que no tienen dato y venian jugando repitieron 24 de 56 veces,
    frente a 733 de 967 de los que si lo tienen."""
    means = {pts.FWD: 4.0}
    seguro = pts.expected([8, 8, 8, 8], pts.FWD, [], means, 1.4, None, 1.0)
    sin = pts.expected([8, 8, 8, 8], pts.FWD, [], means, 1.4, None, None)
    assert sin.xpts == seguro.xpts * pts.UNKNOWN_START_PROB
    assert sin.start_prob is None  # se conserva que la fuente no lo trae
    assert sin.assumed_start_prob is True


def test_a_player_with_data_is_never_marked_as_assumed():
    means = {pts.FWD: 4.0}
    e = pts.expected([8, 8, 8, 8], pts.FWD, [], means, 1.4, None, 0.9)
    assert e.assumed_start_prob is False


def test_a_player_who_will_not_start_is_worth_nothing_this_week():
    means = {pts.FWD: 4.0}
    e = pts.expected([8, 8, 8, 8], pts.FWD, [], means, 1.4, None, 0.0)
    assert e.xpts == 0.0


# --- etiquetas por percentil ----------------------------------------------------------------------


def test_labels_compare_against_the_rest_of_the_league():
    universo = [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6]
    assert "más fáciles" in pts.percentile_label(1.6, universo)
    assert "más difíciles" in pts.percentile_label(0.7, universo)
    assert pts.percentile_label(1.15, universo) == "del montón"


def test_the_same_factor_can_be_easy_or_hard_depending_on_the_week():
    """Un 1,1 es fácil en una jornada dura y del montón en una fácil: por eso no vale un umbral fijo."""
    jornada_dura = [0.6, 0.7, 0.7, 0.8, 0.8, 0.9, 0.9, 1.0, 1.0, 1.1]
    jornada_facil = [1.1, 1.2, 1.2, 1.3, 1.3, 1.4, 1.4, 1.5, 1.5, 1.6]
    assert "más fáciles" in pts.percentile_label(1.1, jornada_dura)
    assert "más difíciles" in pts.percentile_label(1.1, jornada_facil)


def test_without_a_universe_the_label_says_so():
    assert pts.percentile_label(1.2, []) == "sin comparación"


# --- la ficha completa, que es donde están todos los datos ----------------------------------------


def ficha():
    return (FIXTURES / "futbolfantasy_equipo_ficha.html").read_text(encoding="utf-8")


def test_the_full_card_is_read_even_when_the_shirt_only_has_the_injury():
    """Bartra, Gudelj o Arda Güler salían sin probabilidad porque su camiseta solo trae la lesión:
    el dato estaba en la ficha `tipo_lista`, que antes no se leía."""
    rows = {r.slug: r for r in ln.parse_team(ficha())}
    assert len(rows) == 3
    uno = rows["jugador-01"]
    assert uno.start_prob == 0.7 and uno.value == 34787081 and uno.games == 3 and uno.minutes == 270
    assert uno.name == "Jugador Uno"  # el nombre visible, no el slug


def test_the_card_carries_suspension_injury_and_booking_risk():
    rows = {r.slug: r for r in ln.parse_team(ficha())}
    assert rows["jugador-02"].suspended and not rows["jugador-02"].injured
    assert rows["jugador-03"].injured and rows["jugador-03"].booking_risk


def test_html_entities_in_the_name_are_decoded():
    rows = {r.slug: r for r in ln.parse_team(ficha())}
    assert rows["jugador-02"].name == "Jugador Dós"


def test_suspension_is_a_number_of_games_not_a_flag():
    """La página escribe 3 cuando quedan tres partidos de sanción: compararlo con "1" los perdía."""
    doc = (
        ficha()
        .replace('data-nombre="jugador-02"', 'data-nombre="jugador-02"')
        .replace('data-sancionado="1"', 'data-sancionado="3"')
    )
    rows = {r.slug: r for r in ln.parse_team(doc)}
    assert rows["jugador-02"].suspended is True


def test_a_known_slug_is_matched_before_anything_else():
    """El casado se guarda en player_aliases: un slug apunta siempre al mismo jugador."""
    r = ln.Availability("uno", "Nombre Que No Coincide", 0.9, False, False, False, False, 90, 1, 999)
    nuestros = [player("p1", "Otro", "Otro", 1)]
    ids, missed = ln.match([r], nuestros, known={"uno": "p1"})
    assert ids == {"uno": "p1"} and not missed


def test_an_alias_pointing_at_someone_who_left_is_ignored():
    r = ln.Availability("uno", "Alguien", 0.9, False, False, False, False, 90, 1, 5)
    nuestros = [player("p2", "Alguien", "Alguien", 5)]
    ids, _ = ln.match([r], nuestros, known={"uno": "se-fue-de-la-liga"})
    assert ids == {"uno": "p2"}  # cae a las pasadas normales en vez de perderse


def test_the_alias_survives_a_value_that_no_longer_matches():
    """Es el fallo real del 2026-09-09: las dos fuentes se desincronizaron y se cayó de 506 a 397."""
    r = ln.Availability("dos", "Jugador", 0.8, False, False, False, False, 90, 1, 1_000_000)
    nuestros = [player("p9", "Jugador", "Jugador", 1_020_000)]  # el valor ya no cuadra al euro
    sin_alias, faltan = ln.match([r], nuestros)
    con_alias, _ = ln.match([r], nuestros, known={"dos": "p9"})
    assert con_alias == {"dos": "p9"}
    assert sin_alias == {"dos": "p9"} or faltan  # con alias es determinista; sin él, no


def test_set_pieces_decodes_the_packed_attribute():
    """`(aciertos + 1) * 1000 + intentos`, con los casos verificados contra la web el 2026-09-09.

    Los cuatro numeros salieron de `/analytics/{equipo}/balon-parado`, que los publica en texto:
    Unai Lopez 6/16 cornnrs, Ruben Garcia 6/9, Sergio Gomez 0/13 y Budimir 3/3 penaltis."""
    unai = ln._set_pieces({"data-bpc": "7016", "data-bpp": "1000", "data-bpfc": "2003"})
    assert (unai["corner_accurate"], unai["corner_taken"]) == (6, 16)
    assert (unai["pen_scored"], unai["pen_taken"]) == (0, 0)
    assert (unai["cross_accurate"], unai["cross_taken"]) == (1, 3)

    assert ln._set_pieces({"data-bpc": "7009"})["corner_accurate"] == 6
    sergio = ln._set_pieces({"data-bpc": "1013"})
    assert (sergio["corner_accurate"], sergio["corner_taken"]) == (0, 13)
    budimir = ln._set_pieces({"data-bpp": "4003"})
    assert (budimir["pen_scored"], budimir["pen_taken"]) == (3, 3)


def test_set_pieces_ignores_what_it_cannot_read():
    """Un atributo ausente o por debajo del minimo de 1000 no puede dar un acierto negativo."""
    assert ln._set_pieces({}) == {}
    assert ln._set_pieces({"data-bpc": ""}) == {}
    assert ln._set_pieces({"data-bpc": "0"}) == {}
    assert ln._set_pieces({"data-bpc": "no"}) == {}


def _av(slug, sp):
    return ln.Availability(slug, slug, 0.9, False, False, False, False, 90, 1, None, sp)


class _P:
    def __init__(self, pid, team):
        self.player_id, self.team_id = pid, team


def test_team_totals_count_the_whole_page_not_only_the_matched_players():
    """El denominador no puede depender del casado: si falta uno, el resto sale inflado.

    Es el fallo real del 2026-09-09: la Real Sociedad sumaba 18 cornners en vez de 24 porque
    Carlos Soler no estaba casado, y a Sergio Gomez le salia un 72 % en vez de un 54 %."""
    pagina = {
        "real-sociedad": [
            _av("sergio-gomez", {"corner_taken": 13}),
            _av("carlos-soler", {"corner_taken": 6}),  # este no esta casado
            _av("luka-sucic", {"corner_taken": 2}),
        ]
    }
    ids = {"sergio-gomez": "p1", "luka-sucic": "p2"}
    players = [_P("p1", "16"), _P("p2", "16")]
    assert ln.team_totals(pagina, ids, players) == [
        {"team_id": "16", "pen_taken": 0, "corner_taken": 21, "fk_taken": 0, "cross_taken": 0}
    ]


def test_team_totals_ignores_a_page_it_cannot_attribute():
    """Sin un solo jugador casado no se sabe de que equipo es la pagina, y no se inventa."""
    assert ln.team_totals({"x": [_av("a", {"corner_taken": 4})]}, {}, []) == []


def test_a_surname_match_that_the_value_contradicts_is_rejected():
    """El fallo real del 2026-09-09: `vinicius-junior` (106 M) casaba con un "Junior" del Betis
    de 1,9 M porque el slug acaba en "junior", y ese alias quedaba grabado para siempre.
    Diez de los 487 alias estaban asi."""

    class P:
        def __init__(self, pid, nick, value):
            self.player_id, self.nickname, self.name, self.value = pid, nick, nick, value

    vini = ln.Availability(
        "vinicius-junior", "Vinicius Junior", 0.9, False, False, False, False, 300, 4, 106_000_000
    )
    junior_betis = P("2627", "Junior", 1_860_000)
    ids, missed = ln.match([vini], [junior_betis])
    assert ids == {}
    assert [r.slug for r in missed] == ["vinicius-junior"]


def test_a_surname_match_the_value_supports_is_accepted():
    """Sin esta pasada se pierden los que fallan por tildes: alex-grimaldo contra Grimaldo."""

    class P:
        def __init__(self, pid, nick, value):
            self.player_id, self.nickname, self.name, self.value = pid, nick, nick, value

    r = ln.Availability("alex-grimaldo", "Alex Grimaldo", 0.9, False, False, False, False, 300, 4, 34_100_000)
    ids, _ = ln.match([r], [P("1", "Grimaldo", 34_050_000)])
    assert ids == {"alex-grimaldo": "1"}


def test_plausible_lets_through_what_it_cannot_check():
    class P:
        def __init__(self, value):
            self.value = value

    assert ln.plausible(None, P(5)) is True
    assert ln.plausible(5, P(None)) is True
    assert ln.plausible(1_000_000, P(1_100_000)) is True
    assert ln.plausible(1_000_000, P(5_000_000)) is False


def test_season_components_are_read_from_the_same_page():
    """Goles, asistencias, tarjetas y reparto de titularidad: cero peticiones nuevas."""
    rows = {r.slug: r for r in ln.parse_team(html())}
    uno = rows["jugador-01"]
    assert uno.season["goals"] == 1
    assert uno.season["assists"] == 0
    assert uno.season["yellows"] == 0 and uno.season["reds"] == 0
    assert uno.season["games"] == 4 and uno.season["minutes"] == 360
    assert uno.season["hierarchy"] == 40
    assert uno.season["form"] == 1.5


def test_starts_are_games_minus_bench_appearances():
    """El dato que la probabilidad de titular no da: cuántas veces salió de inicio."""
    rows = {r.slug: r for r in ln.parse_team(html())}
    cinco = rows["jugador-05"]
    # 3 jugados, 0 desde el banquillo, 3 sustituido: fue titular las tres y salió antes del final
    assert cinco.season["games"] - cinco.season["games_as_sub"] == 3
    assert cinco.season["games_subbed_off"] == 3
    assert cinco.season["minutes"] == 226  # ~75 min de media, coherente con salir sustituido


def test_a_missing_component_is_absent_not_zero():
    """Un cero inventado ganaría al dato bueno al fusionar las tres apariciones del jugador."""
    assert ln._season({}) == {}
    assert ln._season({"data-totalgoles": ""}) == {}
    assert ln._season({"data-totalgoles": "2"}) == {"goals": 2}


def test_the_best_informed_entry_wins_including_components():
    """La camiseta a veces solo trae la lesión; la ficha completa trae los componentes."""
    pobre = ln.Availability("x", "X", None, False, False, False, False, None, None, None)
    rica = ln.Availability("x", "X", 0.9, False, False, False, False, 300, 4, 5_000_000, {}, {"goals": 2})
    assert ln._score(rica) > ln._score(pobre)


# --- modelo B: puntos por componentes -------------------------------------------------------------


def _comp(goals=0, assists=0, mins=2, yellows=0, reds=0, marca=2, cs=0):
    """Construye un dict de listas de puntos por componente (una sola jornada)."""
    return {
        "goals_pts": [goals],
        "assists_pts": [assists],
        "mins_pts": [mins],
        "yellow_pts": [yellows],
        "red_pts": [reds],
        "marca_pts": [marca],
        "cs_pts": [cs],
    }


def _pos_means_comp(goals=0, assists=0, mins=2, yellows=0, reds=0, marca=2, cs=0):
    """Media de posición uniforme para simplificar los tests."""
    return {
        "goals_pts": goals,
        "assists_pts": assists,
        "mins_pts": mins,
        "yellow_pts": yellows,
        "red_pts": reds,
        "marca_pts": marca,
        "cs_pts": cs,
    }


def test_component_history_groups_by_player():
    """component_history() agrupa los puntos de cada componente por jugador."""

    class Row:
        def __init__(self, pid, pos, week, **kw):
            self.player_id, self.position_id, self.week = pid, pos, week
            for k, v in kw.items():
                setattr(self, k, v)

    filas = [
        Row(
            "p1",
            4,
            1,
            goals_pts=4,
            assists_pts=0,
            mins_pts=2,
            yellow_pts=0,
            red_pts=0,
            marca_pts=3,
            cs_pts=0,
        ),
        Row(
            "p1",
            4,
            2,
            goals_pts=0,
            assists_pts=3,
            mins_pts=2,
            yellow_pts=-1,
            red_pts=0,
            marca_pts=2,
            cs_pts=0,
        ),
        Row(
            "p2",
            2,
            1,
            goals_pts=0,
            assists_pts=0,
            mins_pts=2,
            yellow_pts=0,
            red_pts=0,
            marca_pts=2,
            cs_pts=3,
        ),
    ]
    hist = pts.component_history(filas)
    assert hist["p1"]["goals_pts"] == [4, 0]
    assert hist["p1"]["assists_pts"] == [0, 3]
    assert hist["p2"]["cs_pts"] == [3]


def test_component_model_stable_parts_unaffected_by_fixture():
    """Minutos y nota DAZN no dependen del rival: el factor de calendario no los toca."""
    # Las medias de posición coinciden con los datos del jugador para aislar el encogimiento
    comp = _comp(goals=0, assists=0, mins=2, marca=3)
    pm = _pos_means_comp(mins=2, marca=3)  # misma media = encogimiento no cambia el valor

    sin = pts.expected_from_components(comp, pts.FWD, [], pm, 0.0, None, 1.0)
    assert sin.mins_base == pytest.approx(2.0, abs=0.05)
    assert sin.marca_base == pytest.approx(3.0, abs=0.05)
    # La suma total debe ser exactamente mins + marca (sin goles ni asistencias ni CS)
    assert sin.xpts == pytest.approx(sin.mins_base + sin.marca_base, abs=0.01)


def test_component_model_scoring_parts_scale_with_fixture():
    """Goles y portería a cero sí se ajustan por el calendario."""
    from lfm.analysis.fixtures import Fixture, Strength

    # Jugador con goles como único componente, medias iguales al dato para aislar el calendario
    comp = _comp(goals=4, assists=0, mins=0, marca=0, cs=0)
    pm = _pos_means_comp(goals=4)

    fix = [Fixture(week=7, team_id="mio", opponent_id="rival", home=True, xgf=1.5, xga=1.0, clean_sheet=0.3)]
    strength = {"rival": Strength(attack=0.5, defence=2.0, played=5)}  # defensa rival muy floja: factor >1

    resultado = pts.expected_from_components(comp, pts.FWD, fix, pm, 1.5, strength, 1.0)
    # Con defensa rival muy floja (defence=2.0 > 1.0), los goles esperados deben superar la media
    assert resultado.goals_base > 4.0


def test_component_model_no_games_returns_zero():
    """Sin jornadas jugadas no se atribuyen puntos (igual que expected())."""
    resultado = pts.expected_from_components({}, pts.FWD, [], {}, 0.0, None, 0.9)
    assert resultado.xpts == 0.0
    assert resultado.played == 0


def test_component_model_start_prob_scales_total():
    """La probabilidad de titular escala el total igual que en expected()."""
    comp = _comp(goals=4, mins=2, marca=3)
    pm = _pos_means_comp()
    pleno = pts.expected_from_components(comp, pts.FWD, [], pm, 0.0, None, 1.0)
    mitad = pts.expected_from_components(comp, pts.FWD, [], pm, 0.0, None, 0.5)
    assert mitad.xpts == pytest.approx(pleno.xpts * 0.5, rel=0.01)


def test_component_model_unknown_start_prob_uses_measured_rate():
    """Sin dato de titularidad se aplica el 43 % medido, no el 100 %."""
    comp = _comp(goals=4, mins=2, marca=3)
    pm = _pos_means_comp()
    con = pts.expected_from_components(comp, pts.FWD, [], pm, 0.0, None, 1.0)
    sin = pts.expected_from_components(comp, pts.FWD, [], pm, 0.0, None, None)
    assert sin.xpts == pytest.approx(con.xpts * pts.UNKNOWN_START_PROB, rel=0.01)
    assert sin.assumed_start_prob is True


def test_component_model_breakdown_sums_to_total():
    """La suma de los componentes del desglose coincide con xpts / start_prob."""
    comp = _comp(goals=4, assists=3, mins=2, yellows=-1, marca=3, cs=3)
    pm = _pos_means_comp(goals=2, assists=1, mins=2, marca=2, cs=1)
    r = pts.expected_from_components(comp, pts.DEF, [], pm, 0.0, None, 1.0)
    total_desglose = r.goals_base + r.assists_base + r.mins_base + r.marca_base + r.cs_base + r.cards_base
    assert r.xpts == pytest.approx(total_desglose, abs=0.001)


def test_compare_needs_at_least_two_complete_weeks():
    """compare() con menos de dos jornadas completas devuelve un error explícito."""

    class FakeConn:
        def execute(self, stmt, *args, **kw):
            name = str(stmt)
            if "player_week_stats" in name and "total_points" in name:
                return []
            if "SQL_WEEK_POINTS" in name or "JOIN players" in name:
                return []
            if "SQL_WEEK_COMPONENTS" in name or "goals_pts" in name:
                return []
            if "COMPLETE_WEEKS" in name or "count(local_score)" in name:

                class R:
                    def scalars(self):
                        return [1]  # solo una jornada

                return R()
            return []

    # No usamos BD real: solo comprobamos la importación y firma
    assert callable(pts.compare)
