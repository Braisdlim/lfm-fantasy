"""El día de valor sigue a LaLiga (00:15 de Madrid), no a la fecha UTC de la captura."""

from datetime import UTC, date, datetime

from lfm.valueday import value_day


def test_the_capture_that_broke_the_15th():
    # 23:09 UTC del 15/09 = 01:09 de Madrid del 16: los valores ya son del 16
    assert value_day(datetime(2026, 9, 15, 23, 9, tzinfo=UTC)) == date(2026, 9, 16)


def test_before_the_update_it_is_still_yesterday():
    # 22:10 UTC = 00:10 de Madrid en verano: LaLiga aún no ha cambiado los valores
    assert value_day(datetime(2026, 9, 19, 22, 10, tzinfo=UTC)) == date(2026, 9, 19)
    assert value_day(datetime(2026, 9, 19, 22, 21, tzinfo=UTC)) == date(2026, 9, 20)


def test_winter_time_moves_the_boundary_one_hour():
    assert value_day(datetime(2026, 12, 9, 23, 10, tzinfo=UTC)) == date(2026, 12, 9)  # 00:10 Madrid
    assert value_day(datetime(2026, 12, 9, 23, 25, tzinfo=UTC)) == date(2026, 12, 10)


def test_the_evening_run_is_the_same_day():
    assert value_day(datetime(2026, 9, 19, 17, 25, tzinfo=UTC)) == date(2026, 9, 19)
