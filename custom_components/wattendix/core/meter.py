"""Turn a raw sensor into trusted kWh increments.

Energy counters are differentiated, with three guards:
- a small dip (sensor jitter) keeps the high-water mark, so nothing is counted twice;
- a real drop (counter reset, or a glitch to 0) restarts from the new value;
- an upward jump larger than ``max_kw`` could deliver in the elapsed time is
  rejected. If it merely brings the counter back above its value before a
  drop, only the plausible difference with that earlier value is counted.

Power sensors are integrated over time (left rectangle), skipping gaps.
"""

from __future__ import annotations

from typing import Any

ENERGY_FACTORS = {"wh": 0.001, "kwh": 1.0, "mwh": 1000.0}
POWER_FACTORS = {"w": 0.001, "kw": 1.0, "mw": 1000.0}

MIN_WINDOW = 60.0  # seconds: floor of the plausibility window
JITTER_KWH = 1.0  # dips below this are jitter, not a reset
POWER_MAX_GAP = 300.0  # seconds: longer silences of a power sensor are not integrated


def kind_of(unit: str | None) -> str | None:
    """'energy', 'power' or None for an unsupported unit."""
    key = (unit or "").strip().lower()
    if key in ENERGY_FACTORS:
        return "energy"
    if key in POWER_FACTORS:
        return "power"
    return None


def convert(value: float, unit: str | None) -> float | None:
    """Value in kWh (energy) or kW (power)."""
    key = (unit or "").strip().lower()
    factor = ENERGY_FACTORS.get(key) or POWER_FACTORS.get(key)
    return None if factor is None else value * factor


class Meter:
    """State of one source sensor. ``data`` is JSON-serialisable and persisted."""

    def __init__(self, max_kw: float, data: dict[str, Any] | None = None) -> None:
        self.max_kw = max_kw
        self.d: dict[str, Any] = data if data is not None else {}
        self.d.setdefault("source", None)
        self.d.setdefault("kind", None)
        self.d.setdefault("value", None)
        self.d.setdefault("ts", None)
        self.d.setdefault("drop", None)
        self.d.setdefault("rejected", 0)
        self.d.setdefault("resets", 0)
        self.d.setdefault("last_rejected", None)

    def bind(self, source: str, kind: str) -> None:
        """Forget the reference when the source entity or its nature changes."""
        if self.d["source"] != source or self.d["kind"] != kind:
            self.d.update(source=source, kind=kind, value=None, ts=None, drop=None)

    def _allowed(self, since: float | None, ts: float) -> float:
        window = MIN_WINDOW if since is None else max(ts - since, MIN_WINDOW)
        return self.max_kw * window / 3600.0

    def feed_energy(self, value: float, ts: float) -> float:
        """New counter reading in kWh; returns the kWh to count."""
        d = self.d
        last = d["value"]
        if last is None:
            d.update(value=value, ts=ts)
            return 0.0
        delta = value - last
        if delta == 0:
            return 0.0
        if delta < 0:
            if -delta <= JITTER_KWH and d["drop"] is None:
                return 0.0  # jitter: keep the high-water mark
            if d["drop"] is None:
                d["drop"] = {"value": last, "ts": d["ts"], "counted": 0.0}
            d["resets"] += 1
            d.update(value=value, ts=ts)
            return 0.0
        drop = d["drop"]
        if delta <= self._allowed(d["ts"], ts):
            if drop is not None:
                drop["counted"] += delta
                if value >= drop["value"]:
                    d["drop"] = None
            d.update(value=value, ts=ts)
            return delta
        # Implausible jump.
        counted, recovered = 0.0, False
        if drop is not None and value >= drop["value"]:
            # Back above the value before the drop: count what really happened since.
            missing = value - drop["value"] - drop["counted"]
            if 0 <= missing <= self._allowed(drop["ts"], ts):
                counted, recovered = missing, True
        if not recovered:
            d["rejected"] += 1
            d["last_rejected"] = {"ts": ts, "from": last, "to": value}
        d["drop"] = None
        d.update(value=value, ts=ts)
        return counted

    def feed_power(self, value: float | None, ts: float) -> float:
        """New power reading in kW (None when unavailable); returns kWh."""
        d = self.d
        last, last_ts = d["value"], d["ts"]
        if value is not None and (value < 0 or value > self.max_kw):
            if value > self.max_kw:
                d["rejected"] += 1
                d["last_rejected"] = {"ts": ts, "from": last, "to": value}
            value = None if value > self.max_kw else 0.0
        d.update(value=value, ts=ts)
        if last is None or last_ts is None:
            return 0.0
        gap = ts - last_ts
        if gap <= 0 or gap > POWER_MAX_GAP:
            return 0.0
        return last * gap / 3600.0
