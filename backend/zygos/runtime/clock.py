"""The local-time line the model is told each turn.

Pure: the caller passes the aware ``now``; nothing here reads a clock except the
default zone lookup in ``resolve_zone``.

Stability: Experimental.
"""

from __future__ import annotations

from datetime import datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo

_GAP_MIN = timedelta(minutes=10)


def _plural(n: int, unit: str) -> str:
    return f"{n} {unit}" if n == 1 else f"{n} {unit}s"


def _gap_text(gap: timedelta) -> str:
    seconds = int(gap.total_seconds())
    if seconds < 60 * 60:
        return _plural(seconds // 60, "minute")
    if seconds < 48 * 3600:
        return _plural(seconds // 3600, "hour")
    return _plural(seconds // 86400, "day")


def time_context_line(now: datetime, previous_user_at: datetime | None, tz_label: str) -> str:
    line = (f"Current local time: {now.strftime('%A')} {now.day} {now.strftime('%B %Y, %H:%M')} "
            f"({tz_label}).")
    if previous_user_at is not None:
        gap = now - previous_user_at
        if gap >= _GAP_MIN:
            line += f" The user's previous message was {_gap_text(gap)} ago."
    return line


def resolve_zone(configured: str | None) -> tuple[tzinfo, str]:
    """The configured IANA zone, else the system's local zone."""
    if configured:
        return ZoneInfo(configured), configured
    local = datetime.now().astimezone().tzinfo
    return local, local.tzname(None)
