from datetime import date, timedelta
from types import SimpleNamespace

from lfm.analysis import drift, recommend, trend


def observations(values, *, start=date(2026, 7, 1), source="laliga_api", pid="1"):
    return [
        SimpleNamespace(player_id=pid, day=start + timedelta(days=i), source=source, v=v)
        for i, v in enumerate(values)
    ]


def test_gaps_and_source_changes_break_days_in_training_and_current_history():
    rows = observations([100, 101, 102, 103])
    rows[2].source = rows[3].source = "other"
    assert list(drift.consecutive_segments(rows).values()) == [[100, 101], [102, 103]]
    assert recommend.current_series(rows, rows[-1].day) == {"1": [102, 103]}
    rows = observations([100, 101, 102, 103])
    rows[2].day += timedelta(days=1)
    rows[3].day += timedelta(days=1)
    assert list(drift.consecutive_segments(rows).values()) == [[100, 101], [102, 103]]
    assert recommend.current_series(rows, rows[-1].day + timedelta(days=1)) == {}


def test_continuation_stops_on_a_flat_day_and_is_capped_at_seven():
    rows = observations([100, 90, 100, 110, 110, 120, 130, 140, 150, 160, 170, 180])
    cases = trend.cases_from(rows)
    assert next(c for c in cases if c.day == rows[2].day).days == 1
    assert next(c for c in cases if c.day == rows[3].day).days == 0
    assert all(c.day + timedelta(days=7) <= rows[-1].day for c in cases)
    long = trend.cases_from(observations([100, 90, *range(100, 140)]))
    assert any(c.days == 7 for c in long)
    assert all(c.days <= 7 for c in long)


def test_no_case_uses_a_future_window_with_missing_days():
    rows = observations([100, 90, *range(100, 110)])
    del rows[6]
    assert not trend.cases_from(rows)


def test_fitting_is_unchanged_by_appending_future_data():
    rows = observations([100, 90, *range(100, 160)])
    cutoff = rows[40].day
    assert trend.fit(rows, cutoff) == trend.fit(rows[:40], cutoff)


def test_publication_requires_both_validation_and_enough_comparable_cases():
    values = [100, 90, 100, 110]
    bucket = drift.bucket_with_magnitude(values)
    table = {bucket: [0, 1, 3, 5, 7] * 30}
    assert trend.outlook(values, table, {"passed": False})["status"] == "unvalidated"
    assert trend.outlook(values, {bucket: [7]}, {"passed": True})["status"] == "insufficient"
    result = trend.outlook(values, table, {"passed": True})
    assert result["days"] == 3 and result["low_days"] <= result["days"] <= result["high_days"]
    assert result["stop_within_3d"] == 0.4


def test_failed_or_small_backtests_do_not_publish():
    assert not trend.validate([], date(2026, 9, 26))["passed"]
    # Un único grupo no puede batir al baseline: ambos dan la misma mediana.
    cases = [
        trend.Case(date(2026, 7, 1) + timedelta(days=d), "same", d % 8) for d in range(80) for _ in range(20)
    ]
    assert not trend.validate(cases, date(2026, 9, 26))["passed"]


def test_historical_ranges_are_preserved_when_falling_back():
    table = {"baseline": drift.summarize([-0.2, -0.1, 0, 0.1, 0.2], "baseline")}
    result = drift.expected(table, [100, 110])
    assert result.bucket == drift.UNKNOWN_STREAK
    assert result.low == -0.2 and result.high == 0.1
