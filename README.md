# Wattcast

**Votre facture d'électricité en direct, et là où elle va finir.**
*Your electricity bill, live — and where it is heading.* ([English below](#english))

Wattcast est une intégration Home Assistant, livrée avec sa carte Lovelace. À partir d'un seul capteur de consommation, elle suit ce que le logement a consommé cette heure, aujourd'hui, cette semaine, ce mois et cette année, et **estime le total de chaque période avant qu'elle soit finie** — en kWh, et en euros dès qu'un prix est renseigné.

## Ce qu'elle fait

- **Compteurs par période** : heure, jour, semaine, mois, année, avec la période précédente et la moyenne des dernières périodes.
- **Estimation de fin de période** = déjà consommé + attendu d'ici la fin (+ abonnement de la période entière pour les coûts).
- **Modèle météo appris tout seul** : avec une température extérieure, Wattcast lit l'historique du recorder et apprend combien le logement consomme selon la température du jour (table par tranches de 2 °C), et à quelles heures. Aucun réglage, aucune constante propre à un logement.
- **Prix** : tarif fixe, heures pleines / heures creuses avec plages réglables, ou une entité de prix existante. Le prix est appliqué au moment de la consommation : un changement de tarif ne recalcule jamais le passé.
- **Abonnement** réparti au prorata des jours du mois, avec mémoire de la dernière valeur connue si l'entité source disparaît.
- **Tendance** en % par rapport à la période précédente, calculée sur l'énergie seule (l'abonnement ne la dilue pas).
- **Comparaison annuelle** en kWh « à date » avec l'année précédente.
- **Chauffage** (facultatif) : degrés-jours et consommation de la pompe à chaleur comparée à ce qui est attendu pour le froid qu'il a fait.
- **Compteur protégé** : un retour à zéro ou un saut aberrant du capteur source n'est pas compté.

Tout est facultatif sauf le capteur de consommation. Sans prix, tout fonctionne en kWh.

## Installation

### Avec HACS

1. HACS → menu ⋮ → *Dépôts personnalisés* → ajoutez `https://github.com/Amify-Studio/wattcast`, type *Intégration*.
2. Installez **Wattcast**, puis redémarrez Home Assistant.
3. *Paramètres → Appareils et services → Ajouter une intégration → Wattcast*.

### À la main

Copiez `custom_components/wattcast` dans le dossier `custom_components` de votre configuration, puis redémarrez.

La carte est servie par l'intégration : rien à ajouter dans les ressources Lovelace.

## Configuration

L'assistant avance par niveaux ; chacun peut être modifié ensuite par *Configurer*, sans perdre les compteurs.

| Niveau | Ce qu'on donne | Ce que ça apporte |
| --- | --- | --- |
| **Consommation** (obligatoire) | Un ou plusieurs capteurs, additionnés | Compteurs et estimations en kWh |
| **Prix** | Tarif fixe, HP/HC par plages (`23:10-07:11`), un prix par capteur, ou entité | Tout en euros |
| **Abonnement** | Montant mensuel ou entité | Montants « facture » complets |
| **Météo** | Entité `weather` et/ou thermomètre extérieur | Estimations affinées par la température |
| **Chauffage** | Consommation de la PAC (un ou plusieurs capteurs), base des degrés-jours | Suivi du chauffage |

### Comment arrive la consommation

Le premier écran demande comment la mesure arrive dans Home Assistant :

- **Temps réel** — pince, module de tableau, téléinformation du compteur. Compteurs d'énergie (Wh, kWh, MWh) ou puissances (W, kW). Un compteur est préférable : il rattrape ce qui a été consommé pendant un arrêt de Home Assistant. Tout capteur peut être choisi, même sans classe « énergie » ; c'est l'unité qui est vérifiée.
- **En différé, statistiques importées** — les données du distributeur ou du fournisseur (Linky par Enedis, etc.), qui arrivent le lendemain sous forme de statistiques long terme. On choisit les statistiques directement, même sans entité.
- **En différé, relevé de la veille** — un capteur dont l'état est la consommation du jour précédent.

En différé, il n'y a qu'un total par jour : Wattcast suit le dernier jour reçu, la semaine, le mois et l'année, sans période « heure ». Les jours pas encore reçus (aujourd'hui compris) font partie de l'estimation. Les plages horaires HP/HC ne peuvent pas s'appliquer à un total journalier : utilisez un tarif fixe, ou **un prix par capteur** quand heures pleines et heures creuses ont chacune leur capteur ou leur statistique.

Avec du solaire, choisissez le compteur d'import réseau.

Pour la météo, l'idéal est de donner **les deux** : le thermomètre a un historique dans le recorder (apprentissage immédiat sur plus d'un an), l'entité météo fournit les prévisions des jours suivants. Avec l'entité météo seule, Wattcast apprend au fil des jours à partir de l'installation.

## La carte

```yaml
type: custom:wattcast-card
periods: [day, week, month, year]   # hour, day, week, month, year
display: auto                       # auto | cost | energy
layout: tiles                       # tiles | table (tableau résumé) | mini (tableau nu, très compact)
# columns: [current, estimate, previous, average, trend]   # colonnes du tableau
# descending: true                  # tableau : plus longue période en premier
# charts: true                      # une courbe par période sous les tuiles
# entry: <id de l'entrée>           # s'il y a plusieurs compteurs
# title: Électricité
# hide_heating: true
# hide_info: true
```

Chaque tuile montre le montant en cours, une barre vers l'estimation (le repère marque la période précédente), la pastille de tendance, l'estimation et la période précédente. La carte n'affiche que ce que la configuration fournit ; un appui sur une tuile ouvre l'historique de l'entité. Elle a un éditeur visuel.

En disposition `table`, la même information tient dans un tableau résumé (une ligne par période, colonnes au choix). Avec `charts: true`, chaque période a sa courbe : cumul en cours, estimation, période précédente et moyenne, dessinée sans dépendance et reconstruite depuis l'historique du compteur.

## Comment l'estimation est calculée

- **Heure** : rythme de l'heure précédente.
- **Jour** : consommation attendue pour la température du jour × part de la journée restant à venir (profil horaire appris), corrigée par le rythme observé depuis minuit. Plus la journée avance, plus le rythme réel pèse (rapport borné entre 0,5 et 2).
- **Semaine, mois** : reste d'aujourd'hui + valeur attendue de chaque jour restant, d'après les prévisions ; moyenne des 7 derniers jours au-delà de l'horizon des prévisions.
- **Année** : en kWh, mêmes mois que l'an dernier quand ils sont connus ; sinon moyenne des derniers mois.

Tant que l'historique est insuffisant (moins de 14 jours avec température), l'estimation du jour utilise la **moyenne des 7 derniers jours**. Le capteur *Méthode d'estimation* indique la méthode en cours (`Modèle météo`, `Moyenne des 7 derniers jours`, `Rythme du jour`) et, dans ses attributs, la table apprise, la température retenue et le décalage mesuré entre votre thermomètre et les prévisions.

Sur un an de données réelles d'une maison chauffée par pompe à chaleur, l'erreur moyenne de l'estimation du jour (rejouée à 6 h, 9 h, 12 h, 15 h, 18 h et 21 h, modèle appris sans le jour testé) passe de 9,8 % avec la moyenne des 7 jours à 6,1 % avec le modèle. `dev/backtest.py` rejoue ce test.

## Entités

Par période : `Consommation …`, `Consommation estimée …`, et avec un prix `Coût …`, `Coût estimé …`. Les attributs des capteurs en cours portent `estimate`, `previous`, `average`, `trend`. S'y ajoutent `Prix du kWh`, `Abonnement mensuel`, `Méthode d'estimation`, `Sauts de compteur rejetés`, et pour le chauffage `Degrés-jours …` et `Chauffage du mois / de la saison` (attributs `expected`, `gap`, `per_degree_day`).

## Bon à savoir

- **Au premier démarrage**, Wattcast reprend l'historique du recorder pour remplir les périodes en cours et précédentes. Les coûts de cet historique sont estimés au tarif d'aujourd'hui ; à partir de l'installation, ils sont comptés au prix du moment.
- **Sauts de compteur** : un saut qui dépasserait la *puissance maximale plausible* sur le temps écoulé est rejeté et compté dans le capteur de diagnostic. Réglez cette puissance un peu au-dessus de celle de votre abonnement.
- **Pas dans cette version** : production solaire, tarifs dynamiques heure par heure, comparaison annuelle des coûts.

---

## English

Wattcast is a Home Assistant integration shipped with its Lovelace card. From a single consumption sensor it tracks what the home used this hour, today, this week, this month and this year, and **estimates each period's total before it ends** — in kWh, and in money once a price is given.

- **Only one sensor is required**: the home's total consumption, as an energy counter (Wh, kWh, MWh) or a power sensor (W, kW). Everything else is optional and can be changed later from *Configure*.
- **Price**: flat rate, peak / off-peak with editable time ranges, or an existing price entity. Prices apply when energy is used; a rate change never recomputes the past.
- **Standing charge** spread over the days of the month, remembering the last known value.
- **Self-learned weather model**: with an outdoor temperature, Wattcast learns from the recorder how much the home uses depending on the day's temperature and at which hours. Until 14 days are available it falls back to the average of the last 7 days; the *Estimation method* sensor tells which one is in use.
- **Heating** (optional): degree-days and heat pump consumption against what the weather calls for.
- **Guarded counter**: a reset to zero or an absurd jump of the source is not counted.

Install through HACS as a custom repository (`https://github.com/Amify-Studio/wattcast`, type *Integration*), restart, then add the **Wattcast** integration. The card (`custom:wattcast-card`) is served by the integration and has a visual editor.

## Development

```bash
python -m pytest                                # tests of the calculation core (no Home Assistant needed)
docker compose -f dev/docker-compose.yml up -d  # test instance on http://localhost:18124
python dev/make_translations.py                 # regenerate strings.json and translations
```

Wattcast est édité par Amify-Studio, sous licence MIT. / Wattcast is published by Amify-Studio under the MIT licence.
