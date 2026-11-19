from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from zygos.config.schema import PersonalizationConfig
from zygos.runtime.clock import resolve_zone, time_context_line

LONDON = ZoneInfo("Europe/London")
NOW = datetime(2026, 11, 19, 7, 41, tzinfo=LONDON)


def test_exact_format():
    assert time_context_line(NOW, None, "Europe/London") == \
        "Current local time: Thursday 19 November 2026, 07:41 (Europe/London)."


def test_day_has_no_leading_zero_and_clock_is_24h():
    now = datetime(2026, 3, 5, 18, 5, tzinfo=LONDON)
    assert time_context_line(now, None, "X") == \
        "Current local time: Thursday 5 March 2026, 18:05 (X)."


def test_no_gap_clause_under_ten_minutes():
    assert "previous" not in time_context_line(NOW, NOW - timedelta(minutes=9, seconds=59), "Z")
    assert "previous" not in time_context_line(NOW, None, "Z")


@pytest.mark.parametrize("delta,phrase", [
    (timedelta(minutes=10), "10 minutes"),
    (timedelta(minutes=59, seconds=59), "59 minutes"),
    (timedelta(minutes=60), "1 hour"),
    (timedelta(hours=3, minutes=40), "3 hours"),
    (timedelta(hours=47, minutes=59), "47 hours"),
    (timedelta(hours=48), "2 days"),
    (timedelta(hours=100), "4 days"),
])
def test_gap_wording(delta, phrase):
    line = time_context_line(NOW, NOW - delta, "Europe/London")
    assert line.endswith(f" The user's previous message was {phrase} ago.")


def test_days_are_floored():
    assert "2 days ago" in time_context_line(NOW, NOW - timedelta(hours=71), "Z")


def test_resolve_zone_configured():
    tz, label = resolve_zone("Europe/London")
    assert label == "Europe/London" and tz == ZoneInfo("Europe/London")


def test_resolve_zone_default_is_system_local():
    tz, label = resolve_zone(None)
    assert label == datetime.now().astimezone().tzname()
    assert tz is not None


def test_config_accepts_and_rejects_zone():
    assert PersonalizationConfig(time_zone="Europe/London").time_zone == "Europe/London"
    assert PersonalizationConfig().time_zone is None
    with pytest.raises(ValidationError, match="Not/AZone"):
        PersonalizationConfig(time_zone="Not/AZone")
