"""Drive the Wattendix config flow on the development instance, like the UI does.

    python dev/flow.py minimal     kWh only
    python dev/flow.py full        peak/off-peak + standing charge + weather + heating
"""

from __future__ import annotations

import json
import sys

import ha

VARIANTS = {
    # Someone with almost nothing: a live counter, kWh only.
    "minimal": [
        {"name": "Wattendix kWh", "source_mode": "live", "price_mode": "none", "subscription_mode": "none"},
        {"source": ["sensor.dev_home_energy"], "max_power": 36},
        {},  # weather: nothing
    ],
    # Everything: peak/off-peak ranges, standing charge, weather, thermometer, heat pump.
    "full": [
        {"name": "Wattendix", "source_mode": "live", "price_mode": "peak_offpeak", "subscription_mode": "fixed"},
        {"source": ["sensor.dev_home_energy"], "max_power": 12},
        {"price_peak": 0.1807, "price_offpeak": 0.1387, "offpeak_ranges": "23:10-07:11"},
        {"subscription": 19.37},
        {"weather": "weather.dev_weather", "outdoor_sensor": "sensor.dev_outdoor_temperature"},
        {"heat_pump": ["sensor.dev_heat_pump_energy"], "hdd_base": 16, "season_month": 10},
    ],
    # Cloud meter data only: peak and off-peak statistics arriving the next day.
    "linky": [
        {"name": "Wattendix Linky", "source_mode": "statistics", "price_mode": "per_source", "subscription_mode": "fixed"},
        {"source": ["linky_test:peak", "linky_test:offpeak"], "max_power": 12},
        {"source_price_1": 0.1807, "source_price_2": 0.1387},
        {"subscription": 19.37},
        {"weather": "weather.dev_weather", "outdoor_sensor": "sensor.dev_outdoor_temperature"},
        {"hdd_base": 18, "season_month": 10},
    ],
    # A sensor that only gives yesterday's consumption.
    "daily": [
        {"name": "Wattendix Veille", "source_mode": "daily_value", "price_mode": "fixed", "subscription_mode": "none"},
        {"source": ["sensor.dev_last_reading"], "max_power": 12},
        {"price": 0.17},
        {},
    ],
    # Several live sensors added together, one of them a power sensor.
    "multi": [
        {"name": "Wattendix Multi", "source_mode": "live", "price_mode": "none", "subscription_mode": "none"},
        {"source": ["sensor.dev_home_energy", "sensor.dev_extra_power"], "max_power": 36},
        {},
    ],
    # Refused: time ranges on daily totals.
    "refused": [
        {"name": "x", "source_mode": "statistics", "price_mode": "peak_offpeak", "subscription_mode": "none"},
    ],
}


def run(variant: str) -> None:
    access = ha.token()
    step = ha.http("/api/config/config_entries/flow", {"handler": "wattendix", "show_advanced_options": False}, access)
    for answers in VARIANTS[variant]:
        print("step", step.get("step_id"), "fields", [f["name"] for f in step.get("data_schema", [])])
        step = ha.http(f"/api/config/config_entries/flow/{step['flow_id']}", answers, access)
        if step.get("errors"):
            print("errors:", step["errors"])
            return
    print(json.dumps({k: step.get(k) for k in ("type", "title", "step_id", "errors")}, ensure_ascii=False))
    if step.get("type") == "create_entry":
        print("options:", step["result"].get("entry_id"))


if __name__ == "__main__":
    run(sys.argv[1])
