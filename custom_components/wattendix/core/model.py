"""Learned consumption model.

From past days (24 hourly kWh values + the day's temperature) it builds:
- a table of the mean daily consumption per 2 °C temperature bin (typically
  U-shaped: heating on the left, cooling on the right);
- for each bin, the cumulative share of the day already consumed at each hour.

Nothing here is specific to a home: everything comes from the data.
"""

from __future__ import annotations

from typing import Any

BIN_WIDTH = 2.0
MIN_DAYS = 14  # days needed before the model is used
MIN_BIN_DAYS = 3  # days needed for a bin to count
MIN_PROFILE_DAYS = 8  # days needed for a temperature-specific hourly profile
MIN_VALID_HOURS = 22


def _bin(temp: float) -> int:
    return int(temp // BIN_WIDTH)


def _center(index: int) -> float:
    return index * BIN_WIDTH + BIN_WIDTH / 2


def clean_day(hours: list[float | None], max_kwh: float) -> list[float] | None:
    """24 plausible hourly values, gaps filled with the day's mean; None if unusable."""
    if len(hours) != 24:
        return None
    valid = [h for h in hours if h is not None and 0 <= h <= max_kwh]
    if len(valid) < MIN_VALID_HOURS:
        return None
    mean = sum(valid) / len(valid)
    return [h if h is not None and 0 <= h <= max_kwh else mean for h in hours]


def _cumulative(hourly: list[float]) -> list[float]:
    total = sum(hourly)
    if total <= 0:
        return [i / 24 for i in range(25)]
    out, acc = [0.0], 0.0
    for value in hourly:
        acc += value
        out.append(round(acc / total, 4))
    out[-1] = 1.0
    return out


def learn(
    days: list[dict[str, Any]],
    hour_prices: list[float] | None,
    max_kwh: float,
) -> dict[str, Any]:
    """Build the model. ``days``: [{"date", "t": float|None, "h": [24 values]}]."""
    rows: list[tuple[int, list[float], list[float] | None]] = []
    for day in days:
        if day.get("t") is None:
            continue
        hours = clean_day(day.get("h") or [], max_kwh)
        if hours is None:
            continue
        costs = [h * p for h, p in zip(hours, hour_prices)] if hour_prices else None
        rows.append((_bin(day["t"]), hours, costs))

    def profiles(selection: list[tuple[int, list[float], list[float] | None]]) -> dict[str, Any]:
        kwh = [sum(r[1][h] for r in selection) for h in range(24)]
        out: dict[str, Any] = {"pk": _cumulative(kwh)}
        if hour_prices:
            out["pc"] = _cumulative([sum(r[2][h] for r in selection) for h in range(24)])  # type: ignore[index]
        return out

    model: dict[str, Any] = {"days": len(rows), "bins": [], "ready": False}
    if not rows:
        return model
    model["global"] = profiles(rows)
    for index in sorted({r[0] for r in rows}):
        own = [r for r in rows if r[0] == index]
        if len(own) < MIN_BIN_DAYS:
            continue
        entry: dict[str, Any] = {
            "t": _center(index),
            "n": len(own),
            "kwh": round(sum(sum(r[1]) for r in own) / len(own), 3),
        }
        if hour_prices:
            entry["cost"] = round(sum(sum(r[2]) for r in own) / len(own), 4)  # type: ignore[arg-type]
        for reach in (1, 2):
            near = [r for r in rows if abs(r[0] - index) <= reach]
            if len(near) >= MIN_PROFILE_DAYS:
                entry.update(profiles(near))
                break
        else:
            entry.update(model["global"])
        model["bins"].append(entry)
    model["ready"] = len(rows) >= MIN_DAYS and len(model["bins"]) >= 1
    return model


def expected(model: dict[str, Any] | None, temp: float | None, key: str) -> float | None:
    """Expected daily ``key`` ('kwh' or 'cost') at mean temperature ``temp``."""
    if not model or not model.get("ready") or temp is None:
        return None
    bins = [b for b in model["bins"] if key in b]
    if not bins:
        return None
    if temp <= bins[0]["t"]:
        return bins[0][key]
    if temp >= bins[-1]["t"]:
        return bins[-1][key]
    for low, high in zip(bins, bins[1:]):
        if low["t"] <= temp < high["t"]:
            return low[key] + (high[key] - low[key]) * (temp - low["t"]) / (high["t"] - low["t"])
    return None


def profile(model: dict[str, Any] | None, temp: float | None, key: str) -> list[float] | None:
    """Cumulative hourly profile (25 values) of the bin nearest to ``temp``."""
    if not model or not model.get("ready") or temp is None or not model["bins"]:
        return None
    name = "pc" if key == "cost" else "pk"
    nearest = min(model["bins"], key=lambda b: abs(b["t"] - temp))
    return nearest.get(name) or nearest.get("pk")


def fit_line(points: list[tuple[float, float]]) -> dict[str, float] | None:
    """Least squares y = base + slope * x, with R².

    A negative base has no physical meaning here (consumption with no demand):
    the line is then fitted through the origin, which also keeps mild days
    from being judged against an expectation close to zero.
    """
    n = len(points)
    if n < 2:
        return None
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    sxx = sum((p[0] - mx) ** 2 for p in points)
    if sxx <= 0:
        return None
    slope = sum((p[0] - mx) * (p[1] - my) for p in points) / sxx
    base = my - slope * mx
    if base < 0:
        base = 0.0
        slope = sum(p[0] * p[1] for p in points) / sum(p[0] ** 2 for p in points)
    syy = sum((p[1] - my) ** 2 for p in points)
    residual = sum((p[1] - base - slope * p[0]) ** 2 for p in points)
    r2 = 1 - residual / syy if syy > 0 else 0.0
    return {"base": round(base, 3), "slope": round(slope, 4), "r2": round(r2, 3), "n": n}
