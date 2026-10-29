# Sources de données

| Donnée | Source | Licence / gratuité | Résolution, fraîcheur | Limites |
|---|---|---|---|---|
| Peuplements forestiers | IGN BD Forêt® V2, WFS Géoplateforme (`data.geopf.fr/wfs`), couche découverte automatiquement (`LANDCOVER.FORESTINVENTORY.V2…`) | Licence Ouverte Etalab 2.0, sans clé | polygones ≥ 0,5 ha ; millésime départemental | photo-interprétation souvent > 10 ans ; coupes et tempêtes récentes absentes ; pas d'âge des peuplements |
| Forêts publiques | Géoplateforme (couche `FORETS.PUBLIQUES`) | Licence Ouverte | polygones | ne dit rien des parcelles privées ni des arrêtés en cours |
| Aires protégées | Géoplateforme / INPN (réserves naturelles nationales et régionales, APPB, réserves biologiques) | Licence Ouverte | polygones | Natura 2000 non pris en compte (pas d'interdiction générale de cueillette) |
| Communes | geo.api.gouv.fr | Licence Ouverte | contours | nommage des secteurs uniquement |
| Météo récente et prévue | Open-Meteo Forecast API (`past_days` = prévisions archivées à courte échéance, sans délai de réanalyse) ; humidité du sol 3–9 et 9–27 cm | CC BY 4.0, gratuit non commercial : 10 000 appels/jour | modèles 1,5–11 km (AROME, ARPEGE, ICON, IFS selon la variable) ; échantillonné tous les ~6,5 km (V1 : 9 km) | précipitations convectives localement mal placées ; humidité et température du sol = sorties de modèle |
| Historique (validation) | Open-Meteo Historical Weather API (ERA5) | CC BY 4.0 | ~25 km, J−5 | trop grossier pour la production, utilisé uniquement en validation et pour les références 2015-2024 |
| Couvert arboré actuel (V1.1) | ESA WorldCover 2021 v200, COG sur AWS Open Data | CC BY 4.0 | 10 m, 2021 | classe « arbres » sans essence |
| Coupes rases (V1.1) | Hansen/UMD Global Forest Change (perte annuelle jusqu'en 2024) | CC BY 4.0 | 30 m, annuel | détecte les pertes, pas les replantations |
| Géologie (V1.1) | BRGM, cartes géologiques harmonisées 1/50 000 (BD Charm-50), téléchargement InfoTerre | réutilisation libre, attribution BRGM | 1/50 000 | lithologie ≠ sol : réserve utile et pH indicatifs par formation |
| Sol (V1, abandonné) | SoilGrids 2.0 (ISRIC) | CC BY 4.0 | 250 m, modélisé | erroné sur les sables landais et dunaires (≈ 50 % de sable, pH 6) : plus utilisé dans le score |
| Observations (validation) | iNaturalist API + GBIF | CC0 / CC BY / CC BY-NC | point + précision | identifications à confirmer ; observations floutées exclues du test spatial |
| Relief | Copernicus DEM GLO-30 (AWS Open Data) | licence Copernicus DEM (libre, attribution) | 30 m | MNS (sommet de canopée en forêt) : pentes lissées à l'échelle de 1 km |
| Observations | GBIF (dont iNaturalist) | CC0 / CC BY / CC BY-NC selon jeu | point + incertitude | observations opportunistes ; absence ≠ absence de cèpes |
| Fond de carte | Plan IGN v2 et orthophotos, WMTS Géoplateforme | Licence Ouverte, sans clé | — | — |

## Choix et sources écartées

- **MNT** : Copernicus GLO-30 plutôt que le RGE ALTI® IGN car il est diffusé en COG lisible
  directement (sans service de calcul à quotas) ; le relief n'a qu'un poids de ± 4 %.
- **Météo-France** (API portail) : nécessite un compte et une clé ; Open-Meteo redistribue déjà
  les modèles Météo-France sans clé.
- **Référentiel Régional Pédologique de Gironde / GIS Sol** : pas de service de téléchargement
  automatisable sans compte ; la géologie BRGM 1/50 000 sert de substitut documenté.
- **ERA5-Land** en production : réanalyse disponible avec ~5 jours de retard, inadaptée au calcul du
  soir ; utilisée uniquement pour la validation (ERA5).
- **Sentinel-2 / indices de végétation** : traitement trop lourd pour un calcul gratuit quotidien ;
  WorldCover 2021 + Hansen couvrent le besoin (état du couvert, coupes).
- **Stations Météo-France** : densité trop faible en forêt et accès API avec clé ; non intégrées.
- **Risque incendie / arrêtés** : pas de flux ouvert structuré exploitable ; l'interface renvoie à
  la vérification des arrêtés préfectoraux.
- Les prédictions d'autres applications ne sont jamais utilisées comme observations.

## Quotas consommés

- Open-Meteo : premier calcul V1.1 ≈ 6 000 appels pondérés (92 jours, ~690 points, étalés sur ~1 h 30
  pour rester sous 5 000/h), puis ≈ 900 par calcul grâce au cache (2 calculs/jour) ; validation
  mensuelle ≈ 5 000 (job séparé).
- GitHub Actions : illimité pour un dépôt public ; ~3–5 min par calcul quotidien.
- GitHub Pages : site statique < 20 Mo.
