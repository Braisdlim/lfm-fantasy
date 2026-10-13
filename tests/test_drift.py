"""Deriva del valor: la distribución empírica condicionada a la racha."""

import pytest

from lfm.analysis import drift

# --- rachas censuradas: series demasiado cortas para saber dónde empezó la racha ------------------


def test_a_streak_that_eats_the_whole_series_is_censored():
    """Un jugador que entra hoy y sube mañana no lleva "1 día subiendo": lleva al menos uno."""
    assert drift.censored([100, 110]) is True
    assert drift.censored([100, 110, 120]) is True
    assert drift.censored([100, 90, 100, 110]) is False  # la racha empieza dentro de la serie


def test_a_flat_or_empty_series_is_not_censored():
    assert drift.censored([]) is False
    assert drift.censored([100]) is False
    assert drift.censored([100, 100]) is False  # racha cero, no hay nada que censurar


def test_a_short_censored_streak_falls_back_instead_of_claiming_a_bucket():
    tabla = {
        "baseline": drift.Drift(-0.014, 0.187, 44000, "baseline"),
        "subiendo 1 día": drift.Drift(0.072, 0.67, 880, "subiendo 1 día"),
    }
    corta = drift.expected(tabla, [100, 110])  # solo dos días conocidos
    assert corta.bucket == drift.UNKNOWN_STREAK
    assert corta.mean == tabla["baseline"].mean


def test_a_long_censored_streak_keeps_its_bucket_because_it_is_a_lower_bound():
    """Belocian, 2026-09-09: ocho días de serie bajando los ocho. Sustituir su racha por la media
    general (−0,4 % frente a −6 %) lo hacía parecer mejor y empujaba a comprarlo."""
    tabla = {
        "baseline": drift.Drift(-0.004, 0.187, 31532, "baseline"),
        "bajando 4-7 días": drift.Drift(-0.06, 0.10, 900, "bajando 4-7 días"),
    }
    serie = [3_700_000, 3_578_224, 3_481_768, 3_395_013, 3_304_513, 3_227_334, 3_153_830, 3_093_226]
    assert drift.censored(serie) is True  # sí está censurada
    assert drift.unreliable(serie) is False  # pero sigue informando
    assert drift.expected(tabla, serie).bucket == "bajando 4-7 días"


def test_a_long_series_still_gets_its_bucket():
    tabla = {
        "baseline": drift.Drift(-0.014, 0.187, 44000, "baseline"),
        "subiendo 1 día": drift.Drift(0.072, 0.67, 880, "subiendo 1 día"),
    }
    larga = drift.expected(tabla, [100, 120, 110, 105, 100, 110])
    assert larga.bucket == "subiendo 1 día"


def test_censoring_is_harmless_in_the_open_bucket():
    """Si toda la serie sube y son nueve días, «8+» es cierto sepamos o no dónde empezó."""
    tabla = {
        "baseline": drift.Drift(-0.014, 0.187, 44000, "baseline"),
        "subiendo 8+ días": drift.Drift(0.118, 0.80, 2482, "subiendo 8+ días"),
    }
    e = drift.expected(tabla, list(range(100, 110)))
    assert e.bucket == "subiendo 8+ días"


# --- racha con tamaño (candidato, 2026-09-20) ----------------------------------------------------


def test_streak_change_measures_the_whole_streak():
    assert drift.streak_change([100, 110, 108, 106, 104]) == pytest.approx(104 / 110 - 1)
    assert drift.streak_change([100, 100]) == 0.0


def test_a_long_but_tiny_fall_is_not_the_same_state_as_a_collapse():
    leve = [100, 99.8, 99.6, 99.4, 99.2, 99.0]
    fuerte = [100, 96, 92, 88, 84, 80]
    assert drift.bucket_of(drift.streak(leve)) == drift.bucket_of(drift.streak(fuerte))
    assert drift.bucket_with_magnitude(leve).endswith("leve")
    assert drift.bucket_with_magnitude(fuerte).endswith("fuerte")


def test_the_magnitude_model_falls_back_to_the_current_one_when_the_cell_is_thin():
    table = {"baseline": drift.Drift(-0.01, 0.2, 5000, "baseline")}
    d = drift.expected_magnitude({}, table, [100, 99, 98, 97, 96, 95])
    assert d.bucket == "baseline"
