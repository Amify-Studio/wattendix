"""Feed the development Home Assistant with data read from a real instance.

Nothing is ever written to the real instance: it is only read.

    python dev/mirror.py import    copy the long-term statistics once
    python dev/mirror.py live      mirror current values every 30 s (Ctrl+C to stop)
    python dev/mirror.py once      mirror current values a single time

Entity mapping: dev/mirror.json (see dev/mirror.example.json).
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys
import time

import ha

DEV = pathlib.Path(__file__).resolve().parent
CONFIG = json.loads((DEV / "mirror.json").read_text(encoding="utf-8"))

ATTRS = {
    "energy": {"unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"},
    "heat_pump": {"unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"},
    "temperature": {"unit_of_measurement": "°C", "device_class": "temperature", "state_class": "measurement"},
}


def real() -> tuple[str, str]:
    env = {}
    for line in pathlib.Path(CONFIG["env_file"]).read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env["HA_URL"].rstrip("/"), env["HA_TOKEN"]


def iso(ms: float) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).isoformat()


def import_statistics() -> None:
    url, access = real()
    source = ha.WS(url, access)
    target = ha.WS()
    for group in ("energy", "heat_pump", "temperature"):
        for dev_id, real_id in CONFIG.get(group, {}).items():
            is_temp = group == "temperature"
            rows = source.call({
                "type": "recorder/statistics_during_period",
                "start_time": "2024-01-01T00:00:00+00:00",
                "statistic_ids": [real_id],
                "period": "hour",
                "types": ["mean", "min", "max"] if is_temp else ["sum", "state"],
            }).get(real_id, [])
            if is_temp:
                stats = [{"start": iso(r["start"]), "mean": r["mean"], "min": r["min"], "max": r["max"]}
                         for r in rows if r.get("mean") is not None]
            else:
                stats = [{"start": iso(r["start"]), "sum": r["sum"], "state": r["state"]}
                         for r in rows if r.get("sum") is not None]
            metadata = {
                "has_mean": is_temp,
                "has_sum": not is_temp,
                "mean_type": 1 if is_temp else 0,
                "name": None,
                "source": "recorder",
                "statistic_id": dev_id,
                "unit_of_measurement": "°C" if is_temp else "kWh",
                "unit_class": "temperature" if is_temp else "energy",
            }
            target.call({"type": "recorder/import_statistics", "metadata": metadata, "stats": stats})
            print(f"{dev_id}: {len(stats)} hours imported from {real_id}")


def mirror_once(source: ha.WS, access: str) -> None:
    for group in ("energy", "heat_pump", "temperature"):
        for dev_id, real_id in CONFIG.get(group, {}).items():
            state = source.call({"type": "get_states"})
            value = next((s["state"] for s in state if s["entity_id"] == real_id), None)
            if value in (None, "unknown", "unavailable"):
                continue
            ha.http(f"/api/states/{dev_id}", {"state": value, "attributes": {
                **ATTRS[group], "friendly_name": dev_id.split(".")[1].replace("_", " ").capitalize()}}, access)
    weather = CONFIG.get("weather")
    if weather:
        response = source.call({
            "type": "call_service", "domain": "weather", "service": "get_forecasts",
            "service_data": {"type": "daily"}, "target": {"entity_id": weather}, "return_response": True,
        })
        forecast = response["response"][weather]["forecast"]
        states = source.call({"type": "get_states"})
        current = next(s for s in states if s["entity_id"] == weather)
        ha.http("/api/states/sensor.dev_forecast", {"state": "ok", "attributes": {
            "temperature": current["attributes"].get("temperature"), "forecast": forecast}}, access)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "once"
    if mode == "import":
        import_statistics()
        return
    url, access = real()
    source = ha.WS(url, access)
    dev_access = ha.token()
    while True:
        try:
            mirror_once(source, dev_access)
        except Exception as err:  # noqa: BLE001 - keep mirroring through hiccups
            print("mirror error:", err)
            try:
                source = ha.WS(url, access)
            except Exception:  # noqa: BLE001
                pass
        if mode != "live":
            break
        time.sleep(30)


if __name__ == "__main__":
    main()
