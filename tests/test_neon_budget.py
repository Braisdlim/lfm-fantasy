from datetime import UTC, datetime, timedelta

import pytest

from lfm.jobs.neon_budget import HARD, SOFT, assess


def project():
    now = datetime.now(UTC)
    return {
        "settings": {"quota": dict(HARD)},
        "data_transfer_bytes": 100,
        "compute_time_seconds": 100,
        "synthetic_storage_size": 100,
        "consumption_period_start": (now - timedelta(days=1)).isoformat(),
        "consumption_period_end": (now + timedelta(days=1)).isoformat(),
    }


def test_normal_usage_does_not_change_collection_cadence():
    assert assess(project())["collect"]


@pytest.mark.parametrize("metric", SOFT)
def test_stops_at_reserve_before_provider_limit(metric):
    p = project()
    p[metric] = SOFT[metric] - 1
    assert assess(p)["collect"]
    p[metric] += 1
    assert not assess(p)["collect"]


@pytest.mark.parametrize("metric", SOFT)
@pytest.mark.parametrize("invalid", [None, -1, "100", True])
def test_unknown_usage_never_means_zero(metric, invalid):
    p = project()
    p[metric] = invalid
    assert not assess(p)["collect"]


@pytest.mark.parametrize("quota", HARD)
def test_removed_or_raised_provider_limit_stops_collecting(quota):
    for value in (None, 0, HARD[quota] + 1):
        p = project()
        p["settings"]["quota"][quota] = value
        assert not assess(p)["collect"]


def test_real_blocked_october_usage_pauses_and_new_period_resumes():
    p = project()
    p.update(
        data_transfer_bytes=5_521_034_496, compute_time_seconds=29_366, synthetic_storage_size=354_033_664
    )
    assert not assess(p)["collect"]
    p.update(data_transfer_bytes=0, compute_time_seconds=0)
    assert assess(p)["collect"]


def test_expired_or_patch_placeholder_period_is_not_trusted():
    p = project()
    p["consumption_period_end"] = datetime.now(UTC).isoformat()
    assert not assess(p)["collect"]
    p["consumption_period_start"] = "0001-01-01T00:00:00Z"
    p["consumption_period_end"] = "0001-01-01T00:00:00Z"
    assert not assess(p)["collect"]
