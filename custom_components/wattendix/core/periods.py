"""Calendar periods: hour, day, week (Monday), month, year."""

from __future__ import annotations

from datetime import datetime, timedelta

PERIODS = ("hour", "day", "week", "month", "year")


def start_of(period: str, now: datetime) -> datetime:
    """Start of the period containing ``now`` (aware, local time)."""
    start = now.replace(minute=0, second=0, microsecond=0)
    if period == "hour":
        return start
    start = start.replace(hour=0, fold=0)
    if period == "day":
        return start
    if period == "week":
        return start - timedelta(days=start.weekday())
    if period == "month":
        return start.replace(day=1)
    if period == "year":
        return start.replace(month=1, day=1)
    raise ValueError(period)


def end_of(period: str, now: datetime) -> datetime:
    """Start of the next period."""
    start = start_of(period, now)
    if period == "hour":
        return datetime.fromtimestamp(start.timestamp() + 3600, start.tzinfo)
    if period == "day":
        return start + timedelta(days=1)
    if period == "week":
        return start + timedelta(days=7)
    if period == "month":
        return (start + timedelta(days=32)).replace(day=1)
    return start.replace(year=start.year + 1)


def previous_start(period: str, start: datetime) -> datetime:
    """Start of the period just before the one starting at ``start``."""
    return start_of(period, datetime.fromtimestamp(start.timestamp() - 60, start.tzinfo))


def fraction(period: str, now: datetime) -> float:
    """Share of the period already elapsed, 0..1."""
    start = start_of(period, now).timestamp()
    end = end_of(period, now).timestamp()
    return min(1.0, max(0.0, (now.timestamp() - start) / (end - start)))


def days_in_month(now: datetime) -> int:
    """Number of days of the month containing ``now``."""
    return ((now.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)).day


def season_start(now: datetime, month: int) -> datetime:
    """Start of the heating season containing ``now`` (1st of ``month``)."""
    start = start_of("day", now).replace(month=month, day=1)
    if start > now:
        start = start.replace(year=start.year - 1)
    return start
