"""Generate strings.json and translations/{en,fr}.json (run from the repository root)."""

import json
import pathlib

P = ["hour", "day", "week", "month", "year"]
EN_P = {"hour": "this hour", "day": "today", "week": "this week", "month": "this month", "year": "this year"}
FR_P = {"hour": "de l'heure", "day": "du jour", "week": "de la semaine", "month": "du mois", "year": "de l'année"}


def steps(fr: bool) -> dict:
    def t(french: str, english: str) -> str:
        return french if fr else english

    return {
        "meter": {
            "title": "Wattendix",
            "description": t(
                "Seule la mesure de consommation du logement est nécessaire ; tout le reste est facultatif et se modifie ensuite. Commencez par dire comment cette mesure arrive dans Home Assistant.",
                "Only the home's consumption is required; everything else is optional and can be changed later. Start by telling how this measurement reaches Home Assistant.",
            ),
            "data": {
                "name": t("Nom", "Name"),
                "source_mode": t("Comment arrive la consommation", "How consumption arrives"),
                "price_mode": t("Prix de l'électricité", "Electricity price"),
                "subscription_mode": t("Abonnement", "Standing charge"),
            },
            "data_description": {
                "source_mode": t(
                    "Temps réel : une pince, un module de tableau, la téléinformation du compteur. En différé : les données du distributeur (Linky par Enedis ou votre fournisseur), qui arrivent le lendemain ; Wattendix suit alors le jour, la semaine, le mois et l'année, sans l'heure en cours.",
                    "Live: a clamp, a panel module, the meter's local port. Delayed: data from the grid operator or your supplier, arriving the next day; Wattendix then tracks day, week, month and year, without the current hour.",
                ),
                "price_mode": t(
                    "Sans prix, tout est suivi en kWh. « Un prix par capteur » convient quand heures pleines et heures creuses ont chacune leur capteur.",
                    "Without a price, everything is tracked in kWh. \"One price per sensor\" fits when peak and off-peak each have their own sensor.",
                ),
                "subscription_mode": t(
                    "Ignoré sans prix. Réparti au prorata des jours du mois.",
                    "Ignored without a price. Spread over the days of the month.",
                ),
            },
        },
        "source": {
            "title": t("Mesure de consommation", "Consumption measurement"),
            "description": t(
                "Choisissez ce qui mesure la consommation du logement. Plusieurs éléments sont additionnés : index heures pleines + index heures creuses, trois phases, plusieurs compteurs. En temps réel : compteurs d'énergie (Wh, kWh, MWh) ou puissances (W, kW) ; un compteur est plus fiable, il rattrape ce qui a été consommé pendant un arrêt de Home Assistant. Avec du solaire, choisissez le compteur d'import réseau.",
                "Pick what measures the home's consumption. Several items are added together: peak index + off-peak index, three phases, several meters. Live: energy counters (Wh, kWh, MWh) or power sensors (W, kW); a counter is more reliable, it catches up what was used while Home Assistant was stopped. With solar, pick the grid import counter.",
            ),
            "data": {
                "source": t("Consommation du logement", "Home consumption"),
                "max_power": t("Puissance maximale plausible", "Highest plausible power"),
            },
            "data_description": {
                "source": t(
                    "Capteurs, ou statistiques si vous avez choisi les statistiques importées.",
                    "Sensors, or statistics if you chose imported statistics.",
                ),
                "max_power": t(
                    "Un peu au-dessus de la puissance de votre abonnement. Un saut du compteur qui la dépasserait sur le temps écoulé est rejeté (compteur remis à zéro, valeur aberrante).",
                    "A little above your contract's power. A counter jump that would exceed it over the elapsed time is rejected (counter reset, absurd value).",
                ),
            },
        },
        "price": {
            "title": t("Prix de l'électricité", "Electricity price"),
            "description": t(
                "Le prix est appliqué à l'énergie au moment où elle est comptée : changer de tarif ne recalcule pas le passé.\n\n{sources}",
                "The price is applied to energy when it is counted: changing rates never recomputes the past.\n\n{sources}",
            ),
            "data": {
                "price": t("Prix du kWh", "Price per kWh"),
                "price_peak": t("Prix heures pleines", "Peak price"),
                "price_offpeak": t("Prix heures creuses", "Off-peak price"),
                "offpeak_ranges": t("Plages d'heures creuses", "Off-peak time ranges"),
                "price_entity": t("Entité donnant le prix du kWh", "Entity giving the price per kWh"),
                **{
                    f"source_price_{i}": t(f"Prix du kWh, capteur n° {i}", f"Price per kWh, sensor no. {i}")
                    for i in range(1, 7)
                },
            },
            "data_description": {
                "offpeak_ranges": t(
                    "Une ou plusieurs plages séparées par des virgules, par exemple 23:10-07:11 ou 01:00-07:00, 12:30-14:30.",
                    "One or more ranges separated by commas, for example 23:10-07:11 or 01:00-07:00, 12:30-14:30.",
                ),
                "price_entity": t(
                    "Son état doit être le prix actuel d'un kWh. La dernière valeur connue est gardée si elle devient indisponible.",
                    "Its state must be the current price of one kWh. The last known value is kept while it is unavailable.",
                ),
            },
        },
        "subscription": {
            "title": t("Abonnement", "Standing charge"),
            "data": {
                "subscription": t("Montant mensuel", "Monthly amount"),
                "subscription_entity": t("Entité donnant le montant mensuel", "Entity giving the monthly amount"),
            },
            "data_description": {
                "subscription_entity": t(
                    "La dernière valeur connue est gardée si l'entité devient indisponible.",
                    "The last known value is kept while the entity is unavailable.",
                ),
            },
        },
        "weather": {
            "title": t("Météo", "Weather"),
            "description": t(
                "Facultatif. Avec une température extérieure, Wattendix apprend combien le logement consomme selon le temps qu'il fait et affine ses estimations. L'idéal est de donner les deux : le thermomètre pour apprendre sur l'historique, la météo pour les prévisions.",
                "Optional. With an outdoor temperature, Wattendix learns how much the home uses depending on the weather and sharpens its estimates. Best is to give both: the thermometer to learn from history, the weather entity for forecasts.",
            ),
            "data": {
                "weather": t("Entité météo (prévisions)", "Weather entity (forecasts)"),
                "outdoor_sensor": t("Thermomètre extérieur", "Outdoor thermometer"),
            },
        },
        "heating": {
            "title": t("Chauffage", "Heating"),
            "description": t(
                "Facultatif. Avec la consommation de la pompe à chaleur, Wattendix la compare à ce qui est attendu pour le froid qu'il a fait (degrés-jours).",
                "Optional. With the heat pump's consumption, Wattendix compares it to what is expected for how cold it has been (degree-days).",
            ),
            "data": {
                "heat_pump": t("Consommation de la pompe à chaleur", "Heat pump consumption"),
                "hdd_base": t("Base des degrés-jours", "Degree-day base"),
                "season_month": t("Mois de début de la saison de chauffe", "First month of the heating season"),
            },
            "data_description": {
                "heat_pump": t(
                    "Compteurs d'énergie ou puissances, additionnés (plusieurs radiateurs, plusieurs unités). Laissez vide pour ignorer.",
                    "Energy counters or power sensors, added together (several heaters or units). Leave empty to skip.",
                ),
                "hdd_base": t(
                    "Température extérieure sous laquelle le logement commence à chauffer.",
                    "Outdoor temperature below which the home starts heating.",
                ),
                "season_month": t("1 = janvier … 12 = décembre.", "1 = January … 12 = December."),
            },
        },
    }


def build(fr: bool) -> dict:
    def t(french: str, english: str) -> str:
        return french if fr else english

    errors = {
        "bad_unit": t(
            "Unité non reconnue : il faut Wh, kWh, MWh, W ou kW.",
            "Unsupported unit: Wh, kWh, MWh, W or kW is required.",
        ),
        "bad_daily_unit": t(
            "Un relevé quotidien doit être une énergie : Wh, kWh ou MWh.",
            "A daily reading must be an energy: Wh, kWh or MWh.",
        ),
        "bad_statistic": t(
            "Statistique inutilisable : il faut une énergie cumulée en Wh, kWh ou MWh.",
            "Unusable statistic: a cumulative energy in Wh, kWh or MWh is required.",
        ),
        "no_source": t("Choisissez au moins un élément.", "Pick at least one item."),
        "too_many_sources": t(
            "Un prix par capteur est limité à 6 capteurs.", "One price per sensor is limited to 6 sensors."
        ),
        "delayed_price": t(
            "Des données en différé ne donnent qu'un total par jour : les plages horaires ne s'appliquent pas. Utilisez un tarif fixe, ou un prix par capteur si heures pleines et creuses sont séparées.",
            "Delayed data only gives one total per day: time ranges cannot apply. Use a flat rate, or one price per sensor if peak and off-peak are separate.",
        ),
        "bad_ranges": t(
            "Plages invalides. Exemple : 23:10-07:11, 12:30-14:30",
            "Invalid ranges. Example: 23:10-07:11, 12:30-14:30",
        ),
    }
    sensors: dict = {}
    for p in P:
        sensors[f"energy_{p}"] = {"name": t(f"Consommation {FR_P[p]}", f"Energy {EN_P[p]}")}
        sensors[f"energy_{p}_estimate"] = {
            "name": t(f"Consommation estimée {FR_P[p]}", f"Estimated energy {EN_P[p]}")
        }
        sensors[f"cost_{p}"] = {"name": t(f"Coût {FR_P[p]}", f"Cost {EN_P[p]}")}
        sensors[f"cost_{p}_estimate"] = {"name": t(f"Coût estimé {FR_P[p]}", f"Estimated cost {EN_P[p]}")}
    sensors["price"] = {"name": t("Prix du kWh", "Price per kWh")}
    sensors["subscription"] = {"name": t("Abonnement mensuel", "Monthly standing charge")}
    sensors["method"] = {
        "name": t("Méthode d'estimation", "Estimation method"),
        "state": {
            "model": t("Modèle météo", "Weather model"),
            "average": t("Moyenne des 7 derniers jours", "Last 7 days average"),
            "pace": t("Rythme du jour", "Today's pace"),
        },
    }
    sensors["rejected_jumps"] = {"name": t("Sauts de compteur rejetés", "Rejected counter jumps")}
    spans = {"day": ("du jour", "today"), "month": ("du mois", "this month"), "season": ("de la saison", "this season")}
    for p, (french, english) in spans.items():
        sensors[f"degree_days_{p}"] = {"name": t(f"Degrés-jours {french}", f"Degree-days {english}")}
    for p in ("month", "season"):
        french, english = spans[p]
        sensors[f"heating_{p}"] = {"name": t(f"Chauffage {french}", f"Heating {english}")}
    selectors = {
        "price_mode": {
            "options": {
                "none": t("Aucun (suivi en kWh)", "None (kWh only)"),
                "fixed": t("Tarif fixe", "Flat rate"),
                "peak_offpeak": t("Heures pleines / heures creuses (plages horaires)", "Peak / off-peak hours (time ranges)"),
                "per_source": t("Un prix par capteur (index HP et HC séparés)", "One price per sensor (separate peak and off-peak)"),
                "entity": t("Entité de prix existante", "Existing price entity"),
            }
        },
        "source_mode": {
            "options": {
                "live": t("Temps réel (pince, module, téléinformation)", "Live (clamp, module, meter port)"),
                "statistics": t(
                    "En différé : statistiques importées (Linky, fournisseur)",
                    "Delayed: imported statistics (grid operator, supplier)",
                ),
                "daily_value": t(
                    "En différé : capteur donnant la consommation de la veille",
                    "Delayed: sensor giving yesterday's consumption",
                ),
            }
        },
        "subscription_mode": {
            "options": {
                "none": t("Aucun", "None"),
                "fixed": t("Montant mensuel fixe", "Fixed monthly amount"),
                "entity": t("Entité existante", "Existing entity"),
            }
        },
    }
    step = steps(fr)
    # Shown when the first meter is created: the frontend only loads the card of
    # a newly set up integration when the page is opened again.
    create_entry = {
        "first": "\n\n".join(
            [
                t(
                    "Les capteurs de Wattendix sont créés.",
                    "The Wattendix sensors are created.",
                ),
                t(
                    "**Pour ajouter la carte Wattendix** à un tableau de bord, rechargez d'abord la page du navigateur (ou fermez et rouvrez l'application) : Home Assistant ne charge une nouvelle carte qu'à l'ouverture de la page.",
                    "**To add the Wattendix card** to a dashboard, reload the browser page first (or close and reopen the app): Home Assistant only loads a new card when the page opens.",
                ),
            ]
        )
    }
    return {
        "config": {"step": step, "error": errors, "create_entry": create_entry},
        "options": {"step": step, "error": errors},
        "selector": selectors,
        "entity": {"sensor": sensors},
    }


if __name__ == "__main__":
    base = pathlib.Path("custom_components/wattendix")
    english = json.dumps(build(False), indent=2, ensure_ascii=False) + "\n"
    (base / "strings.json").write_text(english, encoding="utf-8", newline="\n")
    (base / "translations" / "en.json").write_text(english, encoding="utf-8", newline="\n")
    (base / "translations" / "fr.json").write_text(
        json.dumps(build(True), indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print("translations written")
