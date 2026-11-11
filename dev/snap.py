"""Print the main Wattendix values of the development instance."""
import json, sys
import ha
sys.stdout.reconfigure(encoding="utf-8")
keys = sys.argv[1:] or ["cout_du_jour", "cout_de_la_semaine", "cout_du_mois", "cout_de_l_annee", "chauffage_de_la_saison", "methode", "kwh_consommation_du_jour", "sauts"]
for s in ha.http("/api/states", token=ha.token()):
    if s["entity_id"].startswith("sensor.wattendix") and any(k in s["entity_id"] for k in keys):
        a = {k: v for k, v in s["attributes"].items() if k in ("estimate", "previous", "average", "trend", "energy_cost", "expected", "gap", "model_base", "model_slope", "model_r2", "reason", "days_learned", "temperature_today", "temperature_bias", "temperature_bias_days", "expected_cost_today", "counter_resets")}
        print(f"{s['entity_id'][16:]:42s} {s['state']:>10s}  {json.dumps(a, ensure_ascii=False)}")
