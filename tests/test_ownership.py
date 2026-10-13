"""La etiqueta de propiedad decide si un jugador te hace ganar posiciones o solo puntos."""

from lfm.analysis import ownership as ow


def filas(*pares):
    """(player_id, quien) donde quien es 'yo' o el nombre de un rival."""
    return [(p, q, q == "yo", q) for p, q in pares]


def test_a_player_only_i_have_is_a_differential():
    r = ow.classify(filas(("p1", "yo")), rivals_total=4)
    assert r["p1"].label == ow.DIFERENCIAL
    assert r["p1"].rival_count == 0


def test_a_player_everyone_has_is_neutralised():
    """Si lo tienen los cuatro rivales y yo, sus puntos no mueven la clasificacion."""
    r = ow.classify(filas(("p1", "yo"), ("p1", "a"), ("p1", "b"), ("p1", "c"), ("p1", "d")), rivals_total=4)
    assert r["p1"].label == ow.NEUTRALIZADO


def test_a_player_some_rivals_have_is_shared_not_neutralised():
    r = ow.classify(filas(("p1", "yo"), ("p1", "a"), ("p1", "b")), rivals_total=4)
    assert r["p1"].label == ow.COMPARTIDO
    assert r["p1"].rivals == ("a", "b")


def test_a_player_a_rival_has_and_i_do_not_is_a_threat():
    r = ow.classify(filas(("p1", "a")), rivals_total=4)
    assert r["p1"].label == ow.AMENAZA
    assert r["p1"].mine is False


def test_a_player_nobody_has_is_free():
    """No aparece en ninguna plantilla, asi que no aparece en el resultado."""
    r = ow.classify(filas(("p1", "yo")), rivals_total=4)
    assert "p2" not in r
    assert ow.label_of(r, "p2") == ow.LIBRE


def test_the_same_rival_is_never_counted_twice():
    """Si la consulta repitiera una fila (dos dias colandose, dos ligas), un rival contado dos
    veces convertiria un diferencial en compartido sin que nada haya cambiado."""
    r = ow.classify(filas(("p1", "a"), ("p1", "a")), rivals_total=4)
    assert r["p1"].rivals == ("a",)
    r2 = ow.classify(filas(("p1", "yo"), ("p1", "a"), ("p1", "a")), rivals_total=2)
    assert r2["p1"].label == ow.COMPARTIDO  # dos rivales, pero solo uno lo tiene de verdad
