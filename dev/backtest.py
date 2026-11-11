"""Replay the daily estimate on the recorded history of the development instance.

For each past day, the model is learned without that day, then the day's total
is estimated at several hours from what was consumed so far. Prints the mean
absolute error of each method.

    python dev/backtest.py [energy_entity] [temperature_entity]
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import ha

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORE = ROOT / "custom_components" / "wattcast" / "core"
spec = importlib.util.spec_from_file_location(
    "wattcast_core", CORE / "__init__.py", submodule_search_locations=[str(CORE)]
)
package = importlib.util.module_from_spec(spec)
sys.modules["wattcast_core"] = package
spec.loader.exec_module(package)

from wattcast_core import model as mdl  # noqa: E402
from wattcast_core.engine import build_days, remaining_today  # noqa: E402
from wattcast_core.tariff import MODE_PEAK, Tariff, parse_ranges  # noqa: E402

TZ = ZoneInfo("Europe/Paris")
HOURS = (6, 9, 12, 15, 18, 21)


def load(energy: str, temperature: str) -> list[dict]:
    ws = ha.WS()
    stats = ws.call({
        "type": "recorder/statistics_during_period", "start_time": "2025-01-01T00:00:00+00:00",
        "statistic_ids": [energy, temperature], "period": "hour", "types": ["change", "min", "max"],
    })
    hourly = {int(r["start"] / 1000): r["change"] for r in stats.get(energy, []) if r.get("change") is not None}
    temps = {int(r["start"] / 1000): (r["min"], r["max"]) for r in stats.get(temperature, [])
             if r.get("min") is not None}
    return build_days(hourly, temps, TZ, {}, datetime.now(TZ).date())


def main() -> None:
    energy = sys.argv[1] if len(sys.argv) > 1 else "sensor.dev_home_energy"
    temperature = sys.argv[2] if len(sys.argv) > 2 else "sensor.dev_outdoor_temperature"
    prices = Tariff(MODE_PEAK, peak=0.1807, offpeak=0.1387, ranges=parse_ranges("23:10-07:11")).hour_prices()
    days = [d for d in load(energy, temperature) if d.get("t") is not None and mdl.clean_day(d["h"], 36)]
    print(len(days), "usable days")
    errors: dict[str, dict[int, list[float]]] = {m: {h: [] for h in HOURS} for m in ("model", "average")}
    seasons: dict[str, list[float]] = {"cold": [], "mild": []}
    for index, day in enumerate(days):
        if index < 30:
            continue
        model = mdl.learn(days[:index] + days[index + 1:], prices, 36)
        costs = [h * p for h, p in zip(mdl.clean_day(day["h"], 36), prices)]
        total = sum(costs)
        recent = [sum(h * p for h, p in zip(mdl.clean_day(d["h"], 36), prices)) for d in days[index - 7:index]]
        average = sum(recent) / len(recent)
        for hour in HOURS:
            done = sum(costs[:hour])
            for method in errors:
                expected = mdl.expected(model, day["t"], "cost") if method == "model" else None
                profile = mdl.profile(model, day["t"], "cost") if method == "model" else None
                remaining, _ = remaining_today(done, expected, profile, hour, average)
                error = abs(done + remaining - total) / total * 100
                errors[method][hour].append(error)
                if method == "model":
                    seasons["cold" if day["t"] < 12 else "mild"].append(error)
    for method, by_hour in errors.items():
        every = [e for values in by_hour.values() for e in values]
        detail = "  ".join(f"{h}h {sum(v) / len(v):4.1f}%" for h, v in by_hour.items())
        print(f"{method:8s} mean {sum(every) / len(every):4.1f}%   {detail}")
    for name, values in seasons.items():
        print(f"model, {name} days: {sum(values) / len(values):4.1f}% over {len(values) // len(HOURS)} days")


if __name__ == "__main__":
    main()
