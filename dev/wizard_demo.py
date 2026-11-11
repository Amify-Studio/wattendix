"""Prepare the development instance for the wizard screenshots (invented home).

    python dev/wizard_demo.py fr     demo entities named in French + a "Maison" entry
    python dev/wizard_demo.py en     same in English, entry "Home"
    python dev/wizard_demo.py clean  remove the demo entries

It also writes dev/config/www/auth.html (ignored by git): opening
http://localhost:18124/local/auth.html?lang=fr signs a fresh browser in.
"""

from __future__ import annotations

import json
import sys

import ha

NAMES = {
    "fr": {"title": "Maison", "meter": "Compteur général", "heat": "Pompe à chaleur",
           "outdoor": "Thermomètre extérieur", "weather": "Météo maison"},
    "en": {"title": "Home", "meter": "Main meter", "heat": "Heat pump",
           "outdoor": "Outdoor thermometer", "weather": "Home weather"},
}
AUTH = """<!doctype html><meta charset="utf-8"><script>
const lang = new URLSearchParams(location.search).get("lang") || "fr";
localStorage.setItem("hassTokens", JSON.stringify({access_token: %s, token_type: "Bearer",
  expires_in: 315360000, refresh_token: "", hassUrl: location.origin, clientId: location.origin + "/",
  expires: Date.now() + 315360000000}));
localStorage.setItem("selectedLanguage", JSON.stringify(lang));
location.replace("/config/integrations/integration/wattcast");
</script>"""


def entries(access: str) -> list[dict]:
    titles = {names["title"] for names in NAMES.values()}
    return [e for e in ha.http("/api/config/config_entries/entry", token=access)
            if e["domain"] == "wattcast" and e["title"] in titles]


def clean(access: str) -> None:
    for entry in entries(access):
        ha.http(f"/api/config/config_entries/entry/{entry['entry_id']}", token=access, method="DELETE")
        print("removed", entry["title"])


def main() -> None:
    access = ha.token()
    lang = sys.argv[1]
    clean(access)
    if lang == "clean":
        return
    www = ha.DEV / "config" / "www"
    www.mkdir(exist_ok=True)
    (www / "auth.html").write_text(AUTH % json.dumps(access), encoding="utf-8")
    n = NAMES[lang]
    energy = {"unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"}
    states = {
        f"sensor.demo_{lang}_meter": ("18452.6", {**energy, "friendly_name": n["meter"]}),
        f"sensor.demo_{lang}_heat_pump": ("3127.4", {**energy, "friendly_name": n["heat"]}),
        f"sensor.demo_{lang}_outdoor": ("6.9", {"unit_of_measurement": "°C", "device_class": "temperature",
                                              "state_class": "measurement", "friendly_name": n["outdoor"]}),
        f"weather.demo_{lang}": ("cloudy", {"temperature": 7, "temperature_unit": "°C",
                                           "friendly_name": n["weather"], "supported_features": 1}),
    }
    for entity_id, (state, attributes) in states.items():
        ha.http(f"/api/states/{entity_id}", {"state": state, "attributes": attributes}, access)
    answers = [
        {"name": n["title"], "source_mode": "live", "price_mode": "peak_offpeak", "subscription_mode": "fixed"},
        {"source": [f"sensor.demo_{lang}_meter"], "max_power": 9},
        {"price_peak": 0.2068, "price_offpeak": 0.1579, "offpeak_ranges": "22:00-06:00"},
        {"subscription": 16.4},
        {"weather": f"weather.demo_{lang}", "outdoor_sensor": f"sensor.demo_{lang}_outdoor"},
        {"heat_pump": [f"sensor.demo_{lang}_heat_pump"], "hdd_base": 18, "season_month": 10},
    ]
    step = ha.http("/api/config/config_entries/flow", {"handler": "wattcast", "show_advanced_options": False}, access)
    for answer in answers:
        step = ha.http(f"/api/config/config_entries/flow/{step['flow_id']}", answer, access)
        if step.get("errors"):
            sys.exit(f"refused at {step.get('step_id')}: {step['errors']}")
    print(step.get("type"), step.get("title"))


if __name__ == "__main__":
    main()
