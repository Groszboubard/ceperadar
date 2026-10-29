# Modèle de favorabilité CèpeRadar (V1.1)

> V1.1 : humidité du sol hybride, forêt actualisée par satellite, géologie BRGM, états
> « incertain » et « données absentes ». Détail de l'audit et des chiffres avant/après :
> [AUDIT_V1.1.md](AUDIT_V1.1.md). Paramètres V1 conservés dans `model/params_v1.json`.

> L'indice (0–100) est un **indice environnemental**, pas une probabilité de trouver des cèpes.
> Il n'est pas encore calibré sur des récoltes réelles. Les paramètres sont des a priori
> écologiques, réunis dans `model/params.json` (source unique pour le calcul et l'interface).

## 1. Structure

```
Score(espèce, maille, date) = round( H(espèce, maille) × W(espèce, point météo, date) / 100 )
« Tous les cèpes »          = max des quatre espèces (l'espèce dominante est affichée)
```

Le produit impose que **les deux** composantes soient bonnes : météo parfaite (W = 90) sur
habitat incompatible (H = 10) → 9 ; habitat excellent (H = 90) par temps sec (W = 10) → 9.
Un 80+ exige H et W ≥ ~90.

## 2. Habitat H (permanent, maille ≈ 1 km × 1 km)

| Facteur | Source | Effet |
|---|---|---|
| Qualité du peuplement | BD Forêt® V2 (16 classes) | moyenne des affinités espèce × essence pondérée par la surface |
| Couverture forestière | BD Forêt® V2 | × 0,35 (5 % boisé) → × 1 (≥ 60 % boisé) ; < 5 % : maille exclue |
| Lisières | BD Forêt® V2 (rastérisée à ~50 m) | jusqu'à + 10 % |
| Mélange d'essences | indice de Simpson pins / chênes / hêtre-châtaignier / autres | jusqu'à + 8 % |
| Actualisation | ESA WorldCover 2021 + Hansen GFC | coupes ≤ 6 ans → coupe ; coupes 2009-2020 et « FF0 » reboisés → jeune peuplement ; bois hors BD Forêt → essence inconnue |
| pH indicatif | géologie BRGM 1/50 000 | × 0,85 à 1 hors plage ; neutre si inconnu (SoilGrids abandonné : erroné sur les sables) |
| Engorgement | géologie BRGM (tourbes, alluvions) | jusqu'à − 15 % |
| Relief | Copernicus DEM | ± 4 % maximum (relief modeste autour de Bordeaux) |

### Affinités espèce × essence (0–1)

| Classe BD Forêt | edulis | pinophilus | aereus | reticulatus |
|---|---|---|---|---|
| Pin maritime | 0,55 | 0,75 | 0,15 | 0,05 |
| Autres pins | 0,75 | 1,0 | 0,15 | 0,05 |
| Autres conifères | 0,6 | 0,5 | 0,05 | 0,05 |
| Chênes décidus | 0,85 | 0,2 | 1,0 | 1,0 |
| Chênes sempervirents | 0,4 | 0,2 | 0,65 | 0,4 |
| Hêtre | 0,9 | 0,35 | 0,5 | 0,85 |
| Châtaignier | 0,85 | 0,35 | 0,95 | 0,9 |
| Feuillus mélangés | 0,7 | 0,2 | 0,75 | 0,8 |
| Mixte (feuillus prépondérants) | 1,0 | 0,6 | 0,75 | 0,6 |
| Mixte (conifères prépondérants) | 0,9 | 0,85 | 0,45 | 0,35 |
| Peupleraie | 0,05 | 0 | 0 | 0,05 |
| Forêt ouverte, jeunes peuplements, landes | 0,1 – 0,6 | | | |

Justification : *B. edulis* est le plus ubiquiste (pins, chênes, hêtre, châtaignier,
épicéa) ; *B. pinophilus* est lié aux pins sur sols acides sableux ; *B. aereus* est
thermophile, associé aux chênes (dont chêne-liège) et au châtaignier sur sols acides ;
*B. reticulatus* est le cèpe d'été des chênaies-hêtraies-châtaigneraies. Les pinèdes pures
du massif landais ne reçoivent volontairement **pas** le maximum : les secteurs les plus
cités sont les mosaïques pin × chêne et les lisières, d'où les bonus lisière/mélange.

## 3. Météo W (point d'échantillonnage tous les ~9 km, quotidien)

Pour une date cible D, seules les données **jusqu'à la veille** sont utilisées.

- **R — pluie utile** = 0,65 × (1 − e^(−E/50 mm)) + 0,35 × déclencheur.
  E = pluie pondérée par un noyau de délai trapézoïdal : *edulis/pinophilus* pleinement
  efficace de 9 à 26 jours avant D (0 avant 5 j, 0 après 35 j) ; *aereus/reticulatus*
  6 à 21 jours (espèces estivales plus rapides). Déclencheur = épisode ≥ 30 mm en 3 jours
  survenu 8–16 j (5–12 j pour les espèces estivales) avant D.
  → Une grosse pluie **la veille** ne compte presque pas pour le lendemain (testé).
- **M — humidité du sol (V1.1, modèle C hybride)**, calculée par unité point météo × lithologie :
  - A' : réservoir de la couche 0–30 cm, capacité RU selon la géologie (sables landais 22 mm,
    dunes 18, graves 30, limons/molasses 55, calcaires 45, alluvions 70, tourbes 90 ; 35 si
    inconnue) ; interception canopée 1 mm + 12 % ; pertes 0,65 × ETP réduites linéairement sous
    40 % de réserve (Granier et al. 1999, modèle BILJOU) ; initialisé par l'humidité modélisée ;
  - B : humidité volumique Open-Meteo 3–9 et 9–27 cm, normalisée par son enveloppe régionale
    (centiles 5–95) — les m³/m³ ne sont jamais convertis directement en mm ;
  - C = 0,6 A' + 0,4 B ; |A' − B| > 0,35 ⇒ confiance × 0,65 (hachures « incertain ») ;
  - M = lissage de C entre 5 % et 50 % (V1 : réservoir 50 mm, 12 % → 65 %, qui annulait le score
    sur un tiers des points). Un jour sans donnée n'est jamais comblé.
- **T — température** : trapèzes par espèce sur la moyenne de l'air à 20 jours (poids 0,5),
  7 jours (0,25) et du sol à 6 cm sur 7 jours (0,25). Plages optimales (20 j) : edulis
  10,5–16,5 °C, pinophilus 9–15 °C, aereus 15–22 °C, reticulatus 16–23 °C.
- **S — saison** : courbe par espèce (edulis : pic mi-septembre à mi-novembre ; aereus :
  juillet–début octobre ; reticulatus : juin–août ; pinophilus : printemps + automne).
  Facteur appliqué : 0,15 + 0,85 × S (une pousse hors saison reste possible).
- Pénalités : gel (Tmin ≤ 0 °C sur 3 j → × 0,7 ; ≤ −2 °C → × 0,3), jours ≥ 30 °C
  (− 8 % par jour, plancher × 0,5). Bonus « coup de froid » d'automne (≤ + 12 %) pour
  edulis/pinophilus, faible car mal établi dans la littérature.

```
W = R^0,45 × M^0,30 × T^0,25 × (0,15 + 0,85 S) × gel × chaleur × (1 + bonus)
```

### Appui bibliographique

- Suivi de dix ans de *B. edulis* en hêtraie d'Europe centrale (bioRxiv, 2025,
  « Predicting porcini… ») : fenêtre de pluie optimale ~26 jours (26–32 selon les sites),
  effet linéaire positif de la pluie ; température moyenne optimale ≈ 13 °C sur 20 jours,
  fructification surtout entre 10 et 15 °C.
- Salerni, Paoli & Perini (2023), *Italian Journal of Mycology* 52 : réponse de *B. edulis*
  aux pics de pluie et aux pics de chaleur (effet inhibiteur des hausses brutales de Tmax).
- Santolamazza-Carbone et al. (2023), *Frontiers in Soil Science* : le mycélium de
  *B. edulis* / *B. reticulatus* dépend du bilan hydrique des 1–2 mois précédents.
- Écologie des espèces (hôtes, sols acides, thermophilie d'*aereus*, saison estivale de
  *reticulatus*) : flores mycologiques et synthèses usuelles.

## 4. États affichés

- **Score calculé** : couleur de l'échelle.
- **Incertain** (confiance < 50) : couleur + hachures. Causes : sources d'humidité en désaccord,
  échéance lointaine, point météo atypique, essence non cartographiée.
- **Données absentes** : gris. Jamais assimilé à un score défavorable.

## 5. Confiance

`confiance = min(confiance statique de la maille, confiance météo de la date)`

- statique : 85, − 10 sans géologie, − 5 sans relief, − 10 si la maille est boisée à < 15 %,
  − 20 × part d'essence non cartographiée, − 5 si l'actualisation satellite a échoué ;
- humidité : × 0,65 si les deux sources divergent, × 0,85 si une seule est disponible ;
- météo : 1 − 0,6 × (part des entrées issues de prévisions) − 0,05 × (échéance − 1),
  plafonnée à 0,95 (résolution ~9 km : jamais « certain » à l'échelle d'un arbre).
- Élevée ≥ 75, Moyenne ≥ 50, Faible sinon. Point météo incomplet → score inconnu.

## 6. Validation (pipeline/backtest.py)

Observations GBIF datées depuis 2015 (incertitude ≤ 5 km) ; météo ERA5 aux points qui en
concentrent le plus ; même moteur que la production. Métriques AUC (0,5 = hasard) :
date observée vs reste de l'année, vs ±30 jours (effet saison retiré), comparée à un
modèle « saison seule » ; maille observée vs mailles forestières, comparée à « couverture
seule ». Résultats affichés dans l'onglet Infos. Biais : observations opportunistes
(lieux accessibles, week-ends), absence ≠ absence de cèpes.

## 7. Recalibrer

1. Noter chaque sortie dans le Journal (y compris les sorties sans cèpe).
2. Exporter le journal (JSON/CSV).
3. Comparer les scores archivés (`runs/` sur la branche `data`) aux sorties notées et
   ajuster `model/params.json` (fenêtres de pluie, plages thermiques, affinités).
