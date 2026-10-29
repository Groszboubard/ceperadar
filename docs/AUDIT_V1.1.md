# Audit V1 → V1.1 (29 octobre 2026)

Audit réalisé sur les données réellement publiées (branche `data`, calcul du 29/10/2026 à 8 h 25,
92 jours de météo Open-Meteo réelle). Scripts reproductibles : `audit/audit_v1.py`,
`audit/moisture_compare.py`, `audit/moisture_models.py`, `audit/sensitivity.py`
(`CEPERADAR_DATA=<dossier de la branche data> python -m audit.<script>`).

## 1. Constats vérifiés (prévision du 30/10/2026)

| Indicateur | Valeur mesurée |
|---|---|
| Mailles forestières / points météo | 20 999 / 360 |
| Points météo incomplets | 0 |
| Cèpe de Bordeaux : mailles à 0 | **31,5 %** |
| Cèpe de Bordeaux : mailles < 20 / 20–40 / ≥ 60 | 51,6 % / 27,5 % / 6,8 % |
| Points météo avec M = 0 (humidité) | **33 %** |
| Points météo avec W = 0 (cèpe de Bordeaux) | 30,6 % |
| Habitat médian (cèpe de Bordeaux) | 46 / 100 |
| Facteur T (température) | 1,00 partout (optimal) |
| Saison S | 1,00 (pleine saison) |

### Causes dominantes des scores rouges (cèpe de Bordeaux, scores < 20)

- **Humidité M = 0 : 72 %** des scores < 20 et **100 %** des scores nuls.
- Habitat : 27 % des scores < 20.
- Pluie, température, saison : ~1 %.

Pour le cèpe bronzé et le cèpe d'été, la saison (S = 0,33 et 0,10 fin octobre) et la température
dominent, ce qui est écologiquement normal : ces rouges-là sont des **conditions réellement
défavorables**.

## 2. Diagnostic du facteur humidité

- Les 116 points à réservoir < 6 mm ont reçu **16 mm de pluie en médiane sur 30 jours** (contre
  62 mm ailleurs) : la sécheresse relative est réelle, à l'est et au sud.
- Mais l'humidité volumique modélisée par Open-Meteo (3–9 cm) y vaut encore **0,17 m³/m³**
  (0,22 ailleurs ; enveloppe régionale 0,045–0,284) : les deux sources **se contredisent**.
- Le réservoir V1 (50 mm, pertes = 0,8 × ETP sans régulation) se vide linéairement et atteint 0 en
  quelques semaines ; avec le seuil 12 % → M = 0 → W = 0 → score 0 quelle que soit la
  qualité de l'habitat. Le facteur pluie R pénalise déjà ce manque d'eau : **double comptage**.
- Les 21 premiers jours de l'historique (29/07 → 18/08) sont vides dans l'API : la mise en route
  du bilan se fait sur 70 jours, ce qui reste suffisant.

### Comparaison des modèles (30/10/2026, cèpe de Bordeaux)

| Modèle | M = 0 | Scores nuls | < 20 | ≥ 60 |
|---|---|---|---|---|
| A — V1, réservoir 50 mm | 33 % | 32 % | 52 % | 7 % |
| A' — réservoir 0–30 cm, pertes régulées (RU 35 mm) | 12 % | 9 % | 40 % | 8 % |
| A' RU 22 mm (sable) / 55 mm (limon) | 13 % / 15 % | 8 % / 10 % | 39 % / 42 % | 8 % / 7 % |
| A' kc 0,5 / 0,8 | 11 % / 16 % | 7 % / 12 % | 37 % / 43 % | 8 % / 7 % |
| B — humidité modélisée seule | 0 % | 0 % | 32 % | 8 % |
| **C — hybride 0,6 A' + 0,4 B** | **2 %** | **0 %** | **33 %** | **8 %** |
| C, seuils M 0,10–0,60 | 9 % | 7 % | 37 % | 8 % |

Sur la série août–octobre, le désaccord |A' − B| > 0,35 touche 15 à 48 % des points selon la
période : il est traité comme une **incertitude** (hachures) et non comme un état sec.

**Lecture** : le changement supprime les zéros artificiels mais ne fait presque pas bouger la
part des zones favorables (7 → 8 % ≥ 60). La V1.1 n'est donc pas « plus verte » là où les
conditions sont bonnes ; elle est moins binaire là où l'information est contradictoire.

## 3. Sol : SoilGrids n'est pas fiable localement

| Secteur | Sable SoilGrids | Argile | pH | Réalité de terrain |
|---|---|---|---|---|
| Landes (Le Barp – Belin) | 59 % | 18 % | 5,9 | sables > 90 %, podzols, pH ≈ 4–4,5 |
| Dunes Lacanau – Hourtin | 46 % | 22 % | 6,0 | sable dunaire quasi pur |
| Entre-deux-Mers | 35 % | 26 % | 6,6 | calcaires et molasses |

Le pH SoilGrids ≈ 6 pénalisait à tort les pinèdes landaises pour le cèpe de Bordeaux et le cèpe
des pins (plage favorable 4–6). V1.1 : géologie BRGM 1/50 000 (formation → réserve utile,
pH indicatif, engorgement) ; SoilGrids n'est plus utilisé dans le score.

## 4. Peuplements forestiers

Codes BD Forêt® V2 effectivement présents (153 570 polygones) et correspondance vérifiée :

| Code IGN | Libellé officiel | Polygones | Classe V1 | Traitement V1.1 |
|---|---|---|---|---|
| FF0 | Forêt fermée sans couvert arboré | 23 246 | jeune/coupe (affinité 0,1–0,15) | si arboré en 2021 (WorldCover) ou coupé 2009-2020 → « jeune peuplement reconstitué » ; sinon coupe |
| FO0 | Forêt ouverte sans couvert arboré | 46 | jeune/coupe | idem |
| FF1-00-00 / FF1-00 | Mélange de feuillus / feuillus purs en îlots | 24 189 / 22 315 | feuillus mélangés | inchangé |
| FF1G01-01 | Chênes décidus purs | 15 498 | chênes décidus | inchangé |
| FF2-51-51 | Pin maritime pur | 14 391 | pin maritime | coupe rase ≤ 6 ans (Hansen) → coupe |
| FF31 / FF32 | Mélanges feuillus/conifères | 13 174 / 8 619 | mixtes | inchangé |
| LA4 / LA6 | Lande / formation herbacée | 10 778 / 192 | lande / hors forêt | inchangé |

`FF0` désigne des surfaces forestières sans arbres au moment de la photo-interprétation (coupes
rases, plantations très jeunes, peuplements détruits). Dans le massif landais, ces surfaces ont
généralement été replantées : 10 ans après le millésime de la BD Forêt, beaucoup sont devenues
de jeunes pinèdes. La V1 les traitait comme des coupes (2 578 mailles à dominante « jeune/coupe »,
habitat médian 25). La V1.1 vérifie leur état actuel par satellite au lieu de supposer.
Inversement, les coupes rases récentes (dont les incendies de 2022) détectées par Hansen sont
déclassées même si la BD Forêt indique encore une pinède. Les boisements arborés en 2021 mais
absents de la BD Forêt reçoivent une affinité prudente (essence inconnue) et une confiance réduite.

## 4 bis. Sols : ce qui a été tenté, et ce qui est réellement utilisé

| Source | Résultat | Décision |
|---|---|---|
| SoilGrids 250 m | texture et pH faux sur les sables (voir § 3) | **retiré** du score |
| BRGM BD Charm-50 (InfoTerre) | renvoie une page web au lieu du fichier | code conservé, inactif tant que le téléchargement échoue |
| BRGM WFS (lithologie 1/1 000 000) | le pare-feu du BRGM rejette les serveurs GitHub Actions | idem |
| INRAE BDGSF « classes de RU » | fichier récupéré, mais codes 1-5 sans légende ; la conversion testée attribuait aux dunes littorales la plus forte réserve (58 mm) : incohérent | **désactivé** |

En production, la réserve utile de la couche 0-30 cm est donc **une valeur unique de 35 mm** et le
pH n'intervient plus (facteur neutre). La validation montre que l'AUC temporelle ne varie pas
quand cette réserve passe de 22 à 55 mm : l'enjeu sur le classement est faible, mais la
différenciation sables / sols argileux reste une limite connue. La géologie sera utilisée
automatiquement si le BRGM redevient téléchargeable (reconstruction mensuelle).

## 5. Résolution météo

360 points à ~9 km → ~690 points à ~6,5 km. Les précipitations d'Open-Meteo en France proviennent
de modèles de 1,5 à 11 km (AROME en tête) : resserrer l'échantillonnage récupère une partie de la
résolution réellement disponible ; aucune interpolation n'est ajoutée. L'humidité du sol est en
outre différenciée par la géologie de chaque maille (unités point météo × lithologie), ce qui
aurait cassé les grands aplats sans inventer de micro-météo ; faute de source de sol exploitable
(§ 4 bis), cette différenciation n'est pas active aujourd'hui. Contrôle de continuité : 2 points sur 360
avaient un cumul de pluie 30 j atypique par rapport à leurs voisins (est du domaine).

## 6. Ce qui n'a PAS été changé (et pourquoi)

- Les fenêtres pluie/température par espèce et les affinités : pas d'observation locale suffisante
  pour les réestimer ; la sensibilité est mesurée dans la validation.
- La structure multiplicative H × W : conservée (un habitat incompatible ou une vraie sécheresse
  doivent rester limitants), seuls les effets de seuil de l'humidité ont été corrigés.

## 7. Validation historique (29/10/2026)

61 observations publiques datées depuis 2015 dans le rayon de 100 km (51 iNaturalist, 10 GBIF ;
35 cèpes de Bordeaux, 16 bronzés, 9 d'été, 1 des pins). Aucune n'a servi à régler un paramètre.
Météo : ERA5 aux 15 mailles de 0,25° les plus observées.

| Test (AUC ; 0,5 = hasard) | V1 | V1.1 |
|---|---|---|
| Date observée vs reste de l'année (n = 41) | 0,89 [0,87–0,92] | 0,89 [0,86–0,91] |
| Référence « saison seule » | 0,82 [0,78–0,85] | |
| Date observée vs ± 30 jours (effet saison retiré) | 0,66 [0,61–0,70] | 0,65 [0,60–0,69] |
| Identifications « recherche » seules (n = 30) | 0,92 | 0,91 |
| Maille observée vs mailles forestières (n = 34) | 0,70 [0,64–0,77] | 0,68 [0,61–0,75] |
| Référence « couverture forestière seule » | 0,56 [0,49–0,63] | |
| Automnes humides / secs (V1.1) | | 0,89 (n = 25) / 0,89 (n = 16) |

Lecture :
- le score météo classe mieux les dates d'observation que la saison seule, y compris à ± 30 jours :
  la dynamique pluie/température apporte une information réelle, modeste ;
- **V1 et V1.1 ne sont pas distinguables** sur ces données (écarts dans les intervalles) ; la V1.1
  n'apporte pas de gain mesurable de classement, elle supprime des zéros artificiels et
  rend l'incertitude visible ;
- l'habitat classe mieux les lieux observés que la simple couverture forestière ;
- la sensibilité aux paramètres d'humidité (RU 22-55 mm, kc 0,5-0,8, seuils, modèle seul / bilan
  seul) est nulle sur l'AUC temporelle : ces observations ne permettent pas de les départager ;
- par espèce, seuls les effectifs « tous cèpes » dépassent 30 : les résultats par espèce sont non
  concluants ; le cèpe des pins n'a qu'une observation ;
- biais : 28 % d'observations le week-end (attendu 29 %) ; distance médiane à Bordeaux 48 km contre
  65 km pour l'ensemble des forêts (biais vers les zones proches).
