from datetime import date

import pytest

from lfm.collectors.value_history import normalize


def test_official_history_uses_local_dates_preserves_today_and_skips_missing_values():
    payload = [
        {"date": "2026-10-08T00:00:00+02:00", "marketValue": 100},
        {"date": "2026-10-09T00:00:00+02:00", "marketValue": 110},
        {"date": "2026-10-10T00:00:00+02:00", "marketValue": 120},
        {"date": "2026-10-07T00:00:00+02:00", "marketValue": 0},
    ]
    assert normalize(payload, date(2026, 10, 9)) == [{"day": "2026-10-08", "value": 100}]


def test_official_history_refuses_conflicting_days_and_invalid_shapes():
    point = {"date": "2026-10-08T00:00:00+02:00", "marketValue": 100}
    with pytest.raises(ValueError, match="distintos"):
        normalize([point, {**point, "marketValue": 101}], date(2026, 10, 9))
    with pytest.raises(ValueError, match="formato"):
        normalize({}, date(2026, 10, 9))
    with pytest.raises(ValueError, match="inválido"):
        normalize([{**point, "marketValue": True}], date(2026, 10, 9))
