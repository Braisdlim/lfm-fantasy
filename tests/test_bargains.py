"""El excedente compara con quien cuesta lo mismo; si no, 'chollo' solo dice 'barato'."""

from dataclasses import dataclass

from lfm.analysis import bargains as bg


@dataclass
class R:
    player_id: str
    name: str
    position_id: int
    club: str
    value: int
    points_total: int | None
    start_prob: float | None = 0.9
    minutes: int | None = 400
    games: int | None = 4
    injured: bool = False
    suspended: bool = False


def jug(pid, valor, pts, **kw):
    return R(pid, pid, kw.pop("pos", 2), "C", valor, pts, **kw)


def test_who_does_not_play_never_shows_up_however_cheap():
    """Sin este corte los diez primeros del ranking real tenian 0 minutos y 0 % de titular."""
    assert not bg.eligible(jug("a", 600_000, 17, minutes=0, start_prob=0.0))
    assert not bg.eligible(jug("b", 600_000, 17, minutes=100))
    assert not bg.eligible(jug("c", 600_000, 17, start_prob=0.3))
    assert not bg.eligible(jug("d", 600_000, 17, injured=True))
    assert not bg.eligible(jug("e", 600_000, 17, suspended=True))
    assert bg.eligible(jug("f", 600_000, 17))


def test_the_cheapest_does_not_win_just_for_being_cheap():
    """Todos rinden lo que toca para su precio: nadie tiene excedente, aunque el barato
    tenga muchisimos mas puntos por millon que el caro."""
    filas = [jug(f"p{i}", i * 1_000_000, i * 2) for i in range(1, 12)]
    r = bg.rank(filas)
    assert all(abs(b.surplus) < 3 for b in r), [(b.name, b.surplus) for b in r]


def test_the_one_who_beats_his_price_range_comes_first():
    filas = [jug(f"p{i}", i * 1_000_000, i * 2) for i in range(1, 12)]
    filas.append(jug("crack", 3_500_000, 40))
    r = bg.rank(filas)
    assert r[0].name == "crack"
    assert r[0].surplus > 25
    assert r[0].expected > 0


def test_positions_are_compared_apart():
    """Un defensa de 5 M no se mide contra un delantero de 5 M: no puntuan igual."""
    defensas = [jug(f"d{i}", i * 1_000_000, 10, pos=2) for i in range(1, 12)]
    delanteros = [jug(f"a{i}", i * 1_000_000, 40, pos=4) for i in range(1, 12)]
    r = {b.name: b for b in bg.rank(defensas + delanteros)}
    assert r["d5"].expected == 10
    assert r["a5"].expected == 40
    assert r["a5"].surplus == 0


def test_the_extremes_of_each_position_get_no_verdict():
    """Al mas caro solo se le podria comparar con gente mas barata, y saldria chollo siempre.
    Antes de arreglarlo, con once jugadores que rendian exactamente lo que costaban, el mas caro
    sacaba +11 de excedente y el mas barato -11."""
    filas = [jug(f"p{i}", i * 1_000_000, i * 2) for i in range(1, 12)]
    juzgados = {b.name for b in bg.rank(filas)}
    assert "p1" not in juzgados and "p11" not in juzgados
    assert "p6" in juzgados


def test_a_position_with_too_few_players_gets_no_verdict_instead_of_an_invented_one():
    """Con tres porteros no hay vecinos suficientes a ambos lados de ninguno."""
    assert bg.rank([jug(f"g{i}", i * 1_000_000, i * 5, pos=1) for i in range(1, 4)]) == []
    assert bg.rank([jug("solo", 5_000_000, 30, pos=1)]) == []
