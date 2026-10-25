"""Owner-local time for trading-session preferences (default Asia/Dubai, UTC+4, no daylight saving).

Everything stored and compared internally stays UTC. Local time is only used to interpret the owner's
session windows such as "18:00-19:00 Dubai". Economic-event times always come from the calendar feed,
never from hard-coded local times.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone, tzinfo

_FIXED = {"Asia/Dubai": 4.0, "UTC": 0.0}


def get_tz(name: str) -> tzinfo:
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:   # Windows without the tzdata package
        if name in _FIXED:
            return timezone(timedelta(hours=_FIXED[name]), name)
        raise


def parse_hhmm(s: str) -> time:
    h, m = s.strip().split(":")
    return time(int(h), int(m))


def in_local_window(now_utc: datetime, windows: list[tuple[str, str]], tz_name: str) -> bool:
    """True if `now_utc` falls in any [start, end) local-time window. A window whose end is before its
    start wraps past midnight (e.g. 22:00-02:00)."""
    local = now_utc.astimezone(get_tz(tz_name)).time()
    for a, b in windows:
        start, end = parse_hhmm(a), parse_hhmm(b)
        if (start <= local < end) if start < end else (local >= start or local < end):
            return True
    return False
