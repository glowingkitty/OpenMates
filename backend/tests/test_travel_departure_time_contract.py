"""Provider-independent local departure-window filtering for historical results."""
# contract-test-file: infrastructure
import pytest
from backend.apps.travel.skills.search_connections import SearchConnectionsSkill


@pytest.mark.parametrize("departure,expected", [
    ("2027-01-01T22:00:00", True), ("2027-01-02T01:00:00", True),
    ("2027-01-01T12:00:00", False), (None, False),
])
def test_historical_overnight_departure_window(departure, expected):
    assert SearchConnectionsSkill._matches_time_window(departure, "21:00", "02:00") is expected


def test_historical_daytime_window_is_inclusive():
    assert SearchConnectionsSkill._matches_time_window("09:00", "09:00", "17:00")
    assert not SearchConnectionsSkill._matches_time_window("08:59", "09:00", "17:00")
