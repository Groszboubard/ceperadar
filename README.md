# CèpeRadar

Carte personnelle de prospection des cèpes dans un rayon de 100 km autour de Bordeaux :
chaque soir vers 19 h 30, un indice de favorabilité (0–100) est recalculé pour ~1 km² de
forêt à partir des peuplements forestiers, du sol, du relief et de la météo réelle.

**Site** : https://groszboubard.github.io/ceperadar/ (installable sur Android : menu ⋮ → « Ajouter à l'écran d'accueil »)

## Fonctionnement

```
GitHub Actions (gratuit, dépôt public)
 ├─ build_static  (1er lancement + le 3 du mois)  BD Forêt V2, forêts publiques, aires
 │                protégées, communes, SoilGrids, Copernicus DEM, GBIF → static/cells.json
 ├─ update        (19 h 30 et 5 h 30, heure de Paris)  Open-Meteo → scores → forecast/
 ├─ backtest      (mensuel)  ERA5 + observations GBIF → static/backtest.json
 └─ deploy        interface React/MapLibre + données → GitHub Pages
Branche `data` : dernier état des données (réécrite à chaque calcul, sans historique git).
```

Aucun serveur permanent, aucune clé d'API, 0 €. Le site reste en ligne même si un calcul échoue :
il affiche alors l'ancienneté des données.

## Commandes

```bash
pip install -r requirements.txt
python -m pytest tests                       # tests du moteur (données synthétiques)
CEPERADAR_DATA=./data python -m pipeline.build_static
CEPERADAR_DATA=./data python -m pipeline.update --kind manual
CEPERADAR_DATA=./data python -m pipeline.backtest
cd web && npm ci && npm test && npm run build
```

Recalcul manuel : onglet **Actions** du dépôt → « CèpeRadar — calcul et publication » →
**Run workflow** (cocher « Reconstruire les couches permanentes » si besoin).

## Données personnelles

Favoris et journal de cueillette sont stockés **uniquement dans le navigateur** (IndexedDB).
Ils ne sont jamais envoyés ni publiés. Sauvegarde : onglet Favoris ou Journal → « Exporter ».
Vider les données du site dans le navigateur les efface : exporter régulièrement.

## Documentation

- [Modèle et justifications](docs/MODELE.md)
- [Sources de données, licences et limites](docs/SOURCES.md)

## Avertissement

Indice environnemental indicatif. La forêt landaise et médocaine est majoritairement privée :
cueillette soumise à l'accord du propriétaire. Respecter les arrêtés préfectoraux (incendie,
accès aux massifs) et les réglementations des aires protégées. Ne consommer un champignon
qu'après identification certaine.
