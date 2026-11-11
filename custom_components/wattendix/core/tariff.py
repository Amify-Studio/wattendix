"""Energy price: none, fixed, peak/off-peak by time ranges, or an entity."""

from __future__ import annotations

import re
from datetime import datetime

MODE_NONE = "none"
MODE_FIXED = "fixed"
MODE_PEAK = "peak_offpeak"
MODE_ENTITY = "entity"

_RANGE = re.compile(r"^\s*(\d{1,2})[:hH](\d{2})?\s*-\s*(\d{1,2})[:hH](\d{2})?\s*$")


def parse_ranges(text: str) -> list[tuple[int, int]]:
    """'23:10-07:11, 12:30-14:00' -> [(1390, 431), (750, 840)] (minutes of the day).

    Raises ValueError on a malformed range.
    """
    ranges: list[tuple[int, int]] = []
    for part in re.split(r"[,;]", text or ""):
        if not part.strip():
            continue
        match = _RANGE.match(part)
        if not match:
            raise ValueError(part.strip())
        h1, m1, h2, m2 = (int(g or 0) for g in match.groups())
        if h1 > 24 or h2 > 24 or m1 > 59 or m2 > 59:
            raise ValueError(part.strip())
        start, end = (h1 * 60 + m1) % 1440, (h2 * 60 + m2) % 1440
        if start == end:
            raise ValueError(part.strip())
        ranges.append((start, end))
    return ranges


def _in_ranges(minute: int, ranges: list[tuple[int, int]]) -> bool:
    for start, end in ranges:
        if start < end:
            if start <= minute < end:
                return True
        elif minute >= start or minute < end:
            return True
    return False


class Tariff:
    """Price of a kWh now, and for each hour of a day at the current rates."""

    def __init__(
        self,
        mode: str = MODE_NONE,
        fixed: float | None = None,
        peak: float | None = None,
        offpeak: float | None = None,
        ranges: list[tuple[int, int]] | None = None,
    ) -> None:
        self.mode = mode
        self.fixed = fixed
        self.peak = peak
        self.offpeak = offpeak
        self.ranges = ranges or []

    @property
    def active(self) -> bool:
        return self.mode != MODE_NONE

    def is_offpeak(self, now: datetime) -> bool | None:
        if self.mode != MODE_PEAK:
            return None
        return _in_ranges(now.hour * 60 + now.minute, self.ranges)

    def price(self, now: datetime, entity_price: float | None = None) -> float | None:
        """Price applied to energy consumed now."""
        if self.mode == MODE_FIXED:
            return self.fixed
        if self.mode == MODE_PEAK:
            return self.offpeak if self.is_offpeak(now) else self.peak
        if self.mode == MODE_ENTITY:
            return entity_price
        return None

    def hour_prices(self, entity_price: float | None = None) -> list[float] | None:
        """Mean price of each local hour 0..23 at today's rates (None without price)."""
        if self.mode == MODE_FIXED and self.fixed is not None:
            return [self.fixed] * 24
        if self.mode == MODE_ENTITY and entity_price is not None:
            return [entity_price] * 24
        if self.mode == MODE_PEAK and self.peak is not None and self.offpeak is not None:
            prices = []
            for hour in range(24):
                off = sum(_in_ranges(hour * 60 + m, self.ranges) for m in range(60)) / 60
                prices.append(self.offpeak * off + self.peak * (1 - off))
            return prices
        return None
