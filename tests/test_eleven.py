"""El once: elegir entre las siete formaciones que el juego permite, sin inventarse ninguna."""

import json
from datetime import date
from unittest.mock import Mock

import pytest

from lfm.analysis import eleven as el


def p(pid, pos, xpts, **kw):
    return el.Pick(pid, pid, pos, xpts, **kw)


def plantilla(por=1, de=3, me=4, dl=3, base=5.0):
    """Una plantilla con puntos decrecientes, para que el orden sea predecible."""
    out = []
    for pos, n in ((el.GOALKEEPER, por), (el.DEFENDER, de), (el.MIDFIELD, me), (el.STRIKER, dl)):
        for i in range(n):
            out.append(p(f"{pos}-{i}", pos, base - i))
    return out


def test_the_formations_are_the_seven_the_game_allows():
    """Comprobadas contra GET /v4/teams/lineup/formations?option=free el 2026-09-09."""
    assert set(el.FORMATIONS) == {(5, 4, 1), (5, 3, 2), (4, 5, 1), (4, 4, 2), (4, 3, 3), (3, 5, 2), (3, 4, 3)}
    assert all(sum(f) == 10 for f in el.FORMATIONS)  # diez de campo mas el portero


def test_with_exactly_eleven_players_there_is_nothing_to_choose():
    """Es la plantilla real del 2026-09-09: 1-3-4-3. Solo cabe el 3-4-3 y juegan los once."""
    once = el.best(plantilla())
    assert once is not None
    assert once.formation == (3, 4, 3)
    assert once.feasible == 1
    assert once.forced is True
    assert once.bench == ()
    assert len(once.starters) == 11


def test_with_a_bigger_squad_it_picks_the_formation_that_scores_most():
    """Cinco delanteros buenos y defensas flojos: tiene que irse al 3-4-3, no al 5-4-1."""
    picks = [p("g", el.GOALKEEPER, 4)]
    picks += [p(f"d{i}", el.DEFENDER, 1.0) for i in range(5)]
    picks += [p(f"m{i}", el.MIDFIELD, 2.0) for i in range(5)]
    picks += [p(f"a{i}", el.STRIKER, 9.0) for i in range(3)]
    once = el.best(picks)
    assert once.formation == (3, 4, 3)
    assert once.feasible > 1
    assert once.forced is False
    assert once.xpts == 4 + 3 * 1.0 + 4 * 2.0 + 3 * 9.0


def test_the_injured_and_the_suspended_never_line_up():
    """No es una preferencia: el juego no los deja alinear."""
    picks = plantilla(de=5)  # cinco, para que queden tres sanos y el once siga siendo posible
    picks[1] = el.Pick("lesionado", "lesionado", el.DEFENDER, 99.0, injured=True)
    picks[2] = el.Pick("sancionado", "sancionado", el.DEFENDER, 99.0, suspended=True)
    once = el.best(picks)
    assert once is not None
    assert {"lesionado", "sancionado"}.isdisjoint({x.player_id for x in once.starters})


def test_without_a_goalkeeper_there_is_no_eleven_instead_of_one_with_ten():
    """Un once de diez no existe en el juego, y enseñarlo haría creer que se puede alinear."""
    assert el.best([x for x in plantilla() if x.position_id != el.GOALKEEPER]) is None


def test_a_squad_that_fits_no_formation_gets_no_eleven():
    """Dos defensas: ninguna de las siete formaciones baja de tres."""
    assert el.best(plantilla(de=2)) is None


def test_the_weakest_slot_is_the_starter_who_expects_least():
    picks = plantilla()
    picks[1] = el.Pick("no juega", "no juega", el.DEFENDER, 0.0, start_prob=0.0)
    once = el.best(picks)
    assert once.weakest.player_id == "no juega"
    assert once.weakest.position_id == el.DEFENDER


def test_changes_says_who_goes_in_and_who_comes_out():
    picks = plantilla(de=4)
    once = el.best(picks)
    puesto = {x.player_id for x in once.starters}
    banquillo = once.bench[0].player_id
    # se simula que tienes alineado al del banquillo en vez a uno de los titulares
    fuera = next(x.player_id for x in once.starters if x.position_id == el.DEFENDER)
    actual = (puesto - {fuera}) | {banquillo}
    entran, salen = el.changes(actual, once)
    assert [x.player_id for x in entran] == [fuera]
    assert [x.player_id for x in salen] == [banquillo]


def test_no_changes_when_the_lineup_already_matches():
    once = el.best(plantilla())
    entran, salen = el.changes({x.player_id for x in once.starters}, once)
    assert entran == () and salen == ()


def test_current_ids_reads_the_lineup_the_api_returns():
    """Forma real del 2026-09-09: agrupado por linea, con el jugador dentro de playerMaster."""
    payload = {
        "formation": {
            "goalkeeper": [{"playerMaster": {"id": "184", "nickname": "David Soria"}}],
            "defender": [{"playerMaster": {"id": 1337}}],
            "midfield": [],
            "striker": [{"playerMaster": {"id": "2768"}}],
            "coach": 0,
            "bench": {},
            "tacticalFormation": 3,
        }
    }
    assert el.current_ids(payload) == {"184", "1337", "2768"}


def test_current_ids_never_explodes_on_a_shape_it_does_not_know():
    """Si la API cambia, la pantalla tiene que decir 'no se sabe', no romper el job."""
    for basura in (None, {}, [], {"formation": None}, {"formation": {"defender": [1, 2]}}):
        assert el.current_ids(basura) == set()


def test_improvement_is_zero_when_he_would_not_make_the_eleven():
    """Con once justos, un delantero peor que los tres que tienes no cambia nada."""
    picks = plantilla()
    assert el.improvement(picks, p("malo", el.STRIKER, 0.1)) == 0.0


def test_improvement_counts_only_what_he_adds_over_the_one_he_replaces():
    """No son sus puntos: son sus puntos menos los del que se sienta."""
    picks = plantilla()  # delanteros con 5, 4 y 3 puntos
    assert el.improvement(picks, p("crack", el.STRIKER, 9.0)) == pytest.approx(6.0)


def test_a_new_player_can_be_worth_more_than_the_one_he_replaces_by_opening_a_formation():
    """Con 1-3-4-3 solo cabe el 3-4-3. Un cuarto defensa abre el 4-3-3, asi que ademas de
    sentar al peor defensa deja fuera al peor medio: por eso suma mas que su diferencia directa."""
    picks = plantilla()  # defensas 5-4-3, medios 5-4-3-2, delanteros 5-4-3
    directa = 9.0 - 3.0  # lo que le saca al defensa mas flojo
    assert el.improvement(picks, p("gran defensa", el.DEFENDER, 9.0)) == pytest.approx(directa + 1.0)
    # y se comprueba que el dibujo cambia de verdad
    assert el.best([*picks, p("gran defensa", el.DEFENDER, 9.0)]).formation == (4, 3, 3)


def test_it_says_what_is_missing_instead_of_just_failing():
    """El 2026-09-16 la plantilla real eran 4 DEF, 4 MED y 4 DEL: **sin portero**. La app decia
    «todavia no hay once calculado», que es lo contrario de ayudar."""
    sin_portero = [x for x in plantilla(de=4, me=4, dl=4) if x.position_id != el.GOALKEEPER]
    assert el.best(sin_portero) is None
    assert el.missing_for_eleven(sin_portero) == ["1 portero"]


def test_nothing_is_missing_when_an_eleven_is_possible():
    assert el.missing_for_eleven(plantilla()) == []


def test_it_counts_every_line_that_falls_short():
    flaca = plantilla(por=1, de=1, me=1, dl=1)
    assert el.missing_for_eleven(flaca) == ["2 defensas", "2 medios"]


def test_the_injured_do_not_count_towards_the_minimums():
    picks = plantilla()
    picks[0] = el.Pick("portero", "portero", el.GOALKEEPER, 4.0, injured=True)
    assert el.missing_for_eleven(picks) == ["1 portero"]


def test_incomplete_squad_still_saves_individual_forecasts(monkeypatch):
    picks = plantilla(me=2)
    monkeypatch.setattr(el, "picks_from", lambda conn: picks)
    conn = Mock()

    result = el.save(conn, team_id="mine", day=date(2026, 9, 27))

    assert result == {"eleven": None, "missing": ["1 medio"]}
    assert conn.execute.call_count == 2
    saved = conn.execute.call_args.args[1]
    assert saved["formation"] is None
    assert saved["feasible"] == 0
    rows = json.loads(saved["rows"])
    assert len(rows) == len(picks)
    assert all(not row["chosen"] and row["xpts"] is not None for row in rows)
