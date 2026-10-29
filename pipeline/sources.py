"""Collecte des données statiques (exécutée rarement, en CI) :
BD Forêt® V2 (IGN, WFS Géoplateforme), forêts publiques et aires protégées (Géoplateforme),
communes (geo.api.gouv.fr), sol (SoilGrids/ISRIC WCS), relief (Copernicus DEM GLO-30),
observations (GBIF).
"""
from __future__ import annotations

import io
import re
import unicodedata
import xml.etree.ElementTree as ET

import numpy as np

from .common import http_get, log

WFS_URL = "https://data.geopf.fr/wfs/ows"


def norm(s) -> str:
    s = "" if s is None else str(s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------------
# Géoplateforme WFS
# ---------------------------------------------------------------------------
def wfs_typenames(session) -> list[str]:
    r = http_get(session, WFS_URL, {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetCapabilities"},
                 expect_json=False, timeout=180)
    root = ET.fromstring(r.content)
    names = []
    for el in root.iter():
        if el.tag.endswith("FeatureType"):
            for ch in el:
                if ch.tag.endswith("Name") and ch.text:
                    names.append(ch.text.strip())
    log.info("WFS Géoplateforme : %d types d'objets disponibles", len(names))
    return names


def find_typename(names: list[str], *patterns: str) -> str | None:
    for pat in patterns:
        rx = re.compile(pat, re.I)
        hits = [n for n in names if rx.search(n)]
        if hits:
            return sorted(hits, key=len)[0]
    return None


def _swap_if_needed(feat_coords_sample, bbox):
    """Vérifie l'ordre des axes renvoyé (lon, lat attendu)."""
    x, y = feat_coords_sample
    w, s, e, n = bbox
    return not (w - 1 <= x <= e + 1 and s - 1 <= y <= n + 1)


def wfs_fetch(session, typename: str, bbox, *, max_count=5000, depth=0, stats=None):
    """Récupère toutes les entités dans bbox=(w,s,e,n) en EPSG:4326.

    Si une requête atteint la limite du serveur, la boîte est divisée en 4 (récursif) :
    plus robuste que la pagination sans tri garanti.
    """
    stats = stats if stats is not None else {"requests": 0}
    w, s, e, n = bbox
    params = {
        "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature", "TYPENAMES": typename,
        "OUTPUTFORMAT": "application/json", "SRSNAME": "EPSG:4326",
        "BBOX": f"{w},{s},{e},{n},EPSG:4326", "COUNT": str(max_count),
    }
    data = http_get(session, WFS_URL, params, timeout=240)
    stats["requests"] += 1
    feats = data.get("features", [])
    if len(feats) >= max_count and depth < 6:
        mx, my = (w + e) / 2, (s + n) / 2
        out = []
        for sub in ((w, s, mx, my), (mx, s, e, my), (w, my, mx, n), (mx, my, e, n)):
            out.extend(wfs_fetch(session, typename, sub, max_count=max_count, depth=depth + 1, stats=stats))
        return out
    return feats


def tiles(bounds, step):
    w, s, e, n = bounds
    xs = np.arange(w, e, step)
    ys = np.arange(s, n, step)
    for x in xs:
        for y in ys:
            yield (float(x), float(y), float(min(x + step, e)), float(min(y + step, n)))


def fix_axis(features, bbox):
    """Inverse lat/lon si le serveur a renvoyé (lat, lon)."""
    from shapely.geometry import shape
    from shapely.ops import transform

    if not features:
        return []
    g0 = shape(features[0]["geometry"])
    c = g0.representative_point()
    swap = _swap_if_needed((c.x, c.y), bbox)
    out = []
    for f in features:
        if not f.get("geometry"):
            continue
        g = shape(f["geometry"])
        if swap:
            g = transform(lambda x, y, z=None: (y, x), g)
        props = dict(f.get("properties") or {})
        if f.get("id") is not None:
            props.setdefault("id", f["id"])
        out.append((g, props))
    if swap:
        log.warning("Ordre des axes lat/lon inversé détecté et corrigé")
    return out


# ---------------------------------------------------------------------------
# Classification BD Forêt V2 → classes CèpeRadar
# ---------------------------------------------------------------------------
def classify_bdforet(props: dict) -> int:
    """Classe à partir du libellé TFV (type de formation végétale) puis de l'essence.

    Les noms de champs varient selon les diffusions (tfv / TFV / libelle…) : recherche souple.
    """
    keys = {k.lower(): v for k, v in props.items()}
    tfv = norm(keys.get("tfv") or keys.get("libelle") or keys.get("lib_tfv") or "")
    code = norm(keys.get("code_tfv") or keys.get("cod_tfv") or "")
    ess = norm(keys.get("essence") or "")
    txt = f"{tfv} | {ess}"

    if "lande" in tfv:
        return 15
    if "herbac" in tfv:
        return 0
    if any(w in tfv for w in ("coupe", "incident", "jeune", "peuplement jeune")) or code.startswith("ff0") or code.startswith("fo0"):
        return 14
    if "peupleraie" in txt or "peuplier" in ess:
        return 11
    if "preponderant" in tfv:
        if "conifere" in tfv.split("preponderant")[0][-25:]:
            return 10
        return 9
    if code.startswith("ff31") or code.startswith("fo31"):
        return 9
    if code.startswith("ff32") or code.startswith("fo32"):
        return 10
    is_open = "ouverte" in tfv or code.startswith("fo")
    conif_words = ("pin", "conifere", "sapin", "epicea", "douglas", "meleze", "cedre", "cypres")
    if is_open:
        if any(w in txt for w in conif_words) and "feuillu" not in txt:
            return 16
        return 13
    if "pin maritime" in txt:
        return 1
    if "pin" in txt:
        return 2
    if any(w in txt for w in ("sapin", "epicea", "douglas", "meleze", "conifere", "cedre", "cypres")):
        return 3
    if "chene" in txt and "sempervirent" in txt:
        return 5
    if "chene" in txt:
        return 4
    if "hetre" in txt:
        return 6
    if "chataignier" in txt:
        return 7
    if "robinier" in txt:
        return 12
    if "mixte" in ess or ("melange" in tfv and "conifere" in tfv and "feuillu" in tfv):
        return 9
    if "feuillu" in txt:
        return 8
    if "foret" in tfv:
        return 8
    return 0


# ---------------------------------------------------------------------------
# Rastérisation sur la sous-grille (≈ 50 m)
# ---------------------------------------------------------------------------
def rasterize_classes(geoms_with_class, grid, sub):
    from rasterio.features import rasterize
    from rasterio.transform import from_origin

    w, s, e, n = grid.bounds
    shape = (grid.size * sub, grid.size * sub)
    transform = from_origin(w, n, grid.dlon / sub, grid.dlat / sub)
    if not geoms_with_class:
        return np.zeros(shape, dtype=np.uint8)
    return rasterize(geoms_with_class, out_shape=shape, transform=transform, fill=0, dtype="uint8", all_touched=False)


def block_fractions(raster: np.ndarray, grid, sub, n_classes: int) -> np.ndarray:
    """(lignes sud→nord, colonnes, classes) parts de surface."""
    n = grid.size
    out = np.zeros((n, n, n_classes), dtype=np.float32)
    for c in range(n_classes):
        m = (raster == c).reshape(n, sub, n, sub).sum(axis=(1, 3)) / float(sub * sub)
        out[:, :, c] = m
    return out[::-1, :, :]  # raster nord→sud ; grille sud→nord


def block_mean(mask: np.ndarray, grid, sub) -> np.ndarray:
    n = grid.size
    return mask.reshape(n, sub, n, sub).mean(axis=(1, 3))[::-1, :]


FOREST_CLASSES_V1 = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 16]
FOREST_CLASSES = FOREST_CLASSES_V1 + [17, 18]


def edge_density(raster: np.ndarray, grid, sub, classes=None) -> np.ndarray:
    forest = np.isin(raster, classes or FOREST_CLASSES)
    edge = np.zeros_like(forest)
    edge[1:, :] |= forest[1:, :] & ~forest[:-1, :]
    edge[:-1, :] |= forest[:-1, :] & ~forest[1:, :]
    edge[:, 1:] |= forest[:, 1:] & ~forest[:, :-1]
    edge[:, :-1] |= forest[:, :-1] & ~forest[:, 1:]
    return block_mean(edge.astype(np.float32), grid, sub)


# ---------------------------------------------------------------------------
# Communes
# ---------------------------------------------------------------------------
def fetch_communes(session, departements=("33", "40", "47", "24", "17", "16")):
    from shapely.geometry import shape

    out = []
    for d in departements:
        data = http_get(session, f"https://geo.api.gouv.fr/departements/{d}/communes",
                        {"format": "geojson", "geometry": "contour", "fields": "nom,code"}, timeout=120)
        for f in data.get("features", []):
            if f.get("geometry"):
                out.append((shape(f["geometry"]), f["properties"].get("nom", "?"), f["properties"].get("code", "")))
    log.info("Communes : %d contours", len(out))
    return out


def assign_points(points_lonlat: np.ndarray, polys: list):
    """Index du polygone contenant chaque point (-1 sinon)."""
    import shapely
    from shapely.strtree import STRtree

    tree = STRtree([p[0] for p in polys])
    pts = shapely.points(points_lonlat[:, 0], points_lonlat[:, 1])
    res = np.full(len(pts), -1, dtype=int)
    idx_pt, idx_poly = tree.query(pts, predicate="within")
    res[idx_pt] = idx_poly
    # points sans commune (côte) : plus proche
    missing = np.where(res < 0)[0]
    if len(missing):
        near = tree.nearest(pts[missing])
        res[missing] = near
    return res


# ---------------------------------------------------------------------------
# SoilGrids (ISRIC) — WCS en projection Homolosine native
# ---------------------------------------------------------------------------
IGH = "+proj=igh +lat_0=0 +lon_0=0 +datum=WGS84 +units=m +no_defs"


def fetch_soilgrids(session, grid, lat, lon):
    """Renvoie dict(ph, sand, clay, soc) aux centres de cellules (NaN si indisponible).

    Unités SoilGrids : pH×10, sable/argile en g/kg, COS en dg/kg → convertis.
    Résolution native 250 m, valeurs MODÉLISÉES (pas des mesures à la parcelle).
    """
    import rasterio
    from pyproj import Transformer

    tr = Transformer.from_crs("EPSG:4326", IGH, always_xy=True)
    w, s, e, n = grid.bounds
    xs, ys = tr.transform([w, e, w, e], [s, s, n, n])
    X0, X1, Y0, Y1 = min(xs) - 1000, max(xs) + 1000, min(ys) - 1000, max(ys) + 1000
    px, py = tr.transform(lon.ravel(), lat.ravel())
    specs = {
        "ph": ("phh2o", "phh2o_5-15cm_mean", 0.1),
        "sand": ("sand", "sand_5-15cm_mean", 0.1),
        "clay": ("clay", "clay_5-15cm_mean", 0.1),
        "soc": ("soc", "soc_0-5cm_mean", 0.1),  # g/kg
    }
    out = {}
    for key, (mapname, cov, scale) in specs.items():
        url = "https://maps.isric.org/mapserv"
        params = [
            ("map", f"/map/{mapname}.map"), ("SERVICE", "WCS"), ("VERSION", "2.0.1"),
            ("REQUEST", "GetCoverage"), ("COVERAGEID", cov), ("FORMAT", "GEOTIFF_INT16"),
            ("SUBSET", f"X({X0:.0f},{X1:.0f})"), ("SUBSET", f"Y({Y0:.0f},{Y1:.0f})"),
            ("SUBSETTINGCRS", "http://www.opengis.net/def/crs/EPSG/0/152160"),
            ("OUTPUTCRS", "http://www.opengis.net/def/crs/EPSG/0/152160"),
        ]
        try:
            r = http_get(session, url, params, expect_json=False, timeout=300, retries=3)
            with rasterio.MemoryFile(r.content) as mf, mf.open() as ds:
                vals = np.array([v[0] for v in ds.sample(zip(px, py))], dtype=float)
                nod = ds.nodata
            if nod is not None:
                vals[vals == nod] = np.nan
            vals[vals <= 0] = np.nan
            out[key] = (vals * scale).reshape(lat.shape)
            log.info("SoilGrids %s : %.0f %% de valeurs valides", key, 100 * np.isfinite(out[key]).mean())
        except Exception as ex:  # source facultative
            log.warning("SoilGrids %s indisponible : %s", key, ex)
            out[key] = np.full(lat.shape, np.nan)
    return out


# ---------------------------------------------------------------------------
# Relief : Copernicus DEM GLO-30 (COG publics sur AWS Open Data)
# ---------------------------------------------------------------------------
def fetch_dem(grid, sub=5):
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import from_origin
    from rasterio.warp import reproject

    w, s, e, n = grid.bounds
    shape = (grid.size * sub, grid.size * sub)
    dst = np.full(shape, np.nan, dtype=np.float32)
    dst_tr = from_origin(w, n, grid.dlon / sub, grid.dlat / sub)
    ok_tiles = 0
    for la in range(int(np.floor(s)), int(np.floor(n)) + 1):
        for lo in range(int(np.floor(w)), int(np.floor(e)) + 1):
            ns = f"N{la:02d}" if la >= 0 else f"S{-la:02d}"
            ew = f"E{lo:03d}" if lo >= 0 else f"W{-lo:03d}"
            name = f"Copernicus_DSM_COG_10_{ns}_00_{ew}_00_DEM"
            url = f"/vsicurl/https://copernicus-dem-30m.s3.amazonaws.com/{name}/{name}.tif"
            try:
                with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="3"):
                    with rasterio.open(url) as src:
                        tmp = np.full(shape, np.nan, dtype=np.float32)
                        reproject(source=rasterio.band(src, 1), destination=tmp, src_transform=src.transform,
                                  src_crs=src.crs, dst_transform=dst_tr, dst_crs="EPSG:4326",
                                  resampling=Resampling.average, dst_nodata=np.nan)
                        m = np.isfinite(tmp)
                        dst[m] = tmp[m]
                        ok_tiles += 1
            except Exception as ex:
                log.info("Tuile MNT %s absente ou illisible (%s) — normal en mer", name, str(ex)[:80])
    log.info("MNT Copernicus : %d tuiles lues", ok_tiles)
    # métriques par cellule
    lat_mid = grid.lat0
    dx = 111320.0 * np.cos(np.radians(lat_mid)) * grid.dlon / sub
    dy = 110574.0 * grid.dlat / sub
    gy, gx = np.gradient(dst, dy, dx)  # gy : vers le sud (lignes nord→sud)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    # Versant exposé au nord = le terrain descend vers le nord, donc l'altitude
    # augmente vers le sud (axe 0 des lignes orienté vers le sud → gy > 0).
    north_facing = (gy > 0) & (np.abs(gy) > np.abs(gx)) & (slope > 2.0)
    n_ = grid.size
    def bm(a):
        with np.errstate(invalid="ignore"):
            return np.nanmean(a.reshape(n_, sub, n_, sub), axis=(1, 3))[::-1, :]
    elev = bm(dst)
    slope_c = bm(slope)
    north_c = bm(north_facing.astype(np.float32))
    from scipy.ndimage import uniform_filter
    filled = np.where(np.isfinite(elev), elev, np.nanmean(elev) if np.isfinite(elev).any() else 0)
    tpi = elev - uniform_filter(filled, size=5, mode="nearest")
    return {"elev": elev, "slope": slope_c, "north_share": north_c, "tpi": tpi, "ok": ok_tiles > 0}


# ---------------------------------------------------------------------------
# GBIF
# ---------------------------------------------------------------------------
GBIF_SPECIES = {
    "edulis": "Boletus edulis",
    "pinophilus": "Boletus pinophilus",
    "aereus": "Boletus aereus",
    "reticulatus": "Boletus reticulatus",
}


def fetch_gbif(session, bounds):
    w, s, e, n = bounds
    out = []
    for key, name in GBIF_SPECIES.items():
        m = http_get(session, "https://api.gbif.org/v1/species/match", {"name": name, "kingdom": "Fungi"})
        tk = m.get("acceptedUsageKey") or m.get("usageKey")
        if not tk:
            log.warning("GBIF : taxon introuvable %s", name)
            continue
        offset = 0
        while True:
            d = http_get(session, "https://api.gbif.org/v1/occurrence/search", {
                "taxonKey": tk, "decimalLatitude": f"{s},{n}", "decimalLongitude": f"{w},{e}",
                "hasCoordinate": "true", "hasGeospatialIssue": "false", "limit": 300, "offset": offset,
            })
            for r in d.get("results", []):
                if r.get("basisOfRecord") == "FOSSIL_SPECIMEN":
                    continue
                out.append({
                    "sp": key, "lat": r.get("decimalLatitude"), "lon": r.get("decimalLongitude"),
                    "date": (r.get("eventDate") or "")[:10], "y": r.get("year"), "m": r.get("month"), "d": r.get("day"),
                    "unc": r.get("coordinateUncertaintyInMeters"), "basis": r.get("basisOfRecord"),
                    "lic": (r.get("license") or "").split("/")[-2] if r.get("license") else None,
                    "ds": r.get("datasetName") or r.get("institutionCode"), "key": r.get("key"),
                })
            offset += 300
            if d.get("endOfRecords", True) or offset > 20000:
                break
        log.info("GBIF %s (taxon %s) : %d observations cumulées", name, tk, len(out))
    return out


# ---------------------------------------------------------------------------
# V1.1 — Couvert arboré actuel (ESA WorldCover 2021, 10 m) et coupes (Hansen GFC)
# ---------------------------------------------------------------------------
def _read_into_subgrid(urls, grid, sub, resampling, dtype="uint8"):
    """Lit des rasters EPSG:4326 publics (COG/GeoTIFF via HTTP) dans la sous-grille de CèpeRadar.

    Lecture fenêtrée avec rééchantillonnage direct (les aperçus du COG sont utilisés), car les
    deux grilles sont en degrés : pas de reprojection, seulement un changement de pas.
    """
    import rasterio
    from rasterio.windows import from_bounds

    w, s, e, n = grid.bounds
    H = W = grid.size * sub
    px, py = grid.dlon / sub, grid.dlat / sub
    dst = np.zeros((H, W), dtype=dtype)
    ok = []
    for url in urls:
        try:
            with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="4", GDAL_HTTP_RETRY_DELAY="5",
                              CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif"):
                with rasterio.open(("/vsicurl/" + url) if url.startswith("http") else url) as src:
                    b = src.bounds
                    iw, ie = max(w, b.left), min(e, b.right)
                    is_, in_ = max(s, b.bottom), min(n, b.top)
                    if iw >= ie or is_ >= in_:
                        continue
                    c0 = int(round((iw - w) / px)); c1 = int(round((ie - w) / px))
                    r0 = int(round((n - in_) / py)); r1 = int(round((n - is_) / py))
                    if c1 <= c0 or r1 <= r0:
                        continue
                    # bornes exactes des pixels cibles
                    win = from_bounds(w + c0 * px, n - r1 * py, w + c1 * px, n - r0 * py, src.transform)
                    data = src.read(1, window=win, out_shape=(r1 - r0, c1 - c0), resampling=resampling, boundless=True, fill_value=0)
                    tgt = dst[r0:r1, c0:c1]
                    m = data > 0
                    tgt[m] = data[m].astype(dtype)
                    ok.append(url.rsplit("/", 1)[-1])
        except Exception as ex:
            log.warning("Lecture impossible %s : %s", url.rsplit("/", 1)[-1], str(ex)[:160])
    return dst, ok


def _tile_names(grid, step, fmt):
    w, s, e, n = grid.bounds
    out = []
    for la in range(int(np.floor(s / step) * step), int(np.floor(n / step) * step) + 1, step):
        for lo in range(int(np.floor(w / step) * step), int(np.floor(e / step) * step) + 1, step):
            out.append(fmt(la, lo))
    return out


def fetch_worldcover(grid, sub):
    """Classes ESA WorldCover 2021 v200 (10 = couvert arboré). Licence CC BY 4.0."""
    from rasterio.enums import Resampling

    def name(la, lo):
        ns = f"N{la:02d}" if la >= 0 else f"S{-la:02d}"
        ew = f"E{lo:03d}" if lo >= 0 else f"W{-lo:03d}"
        return f"https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{ns}{ew}_Map.tif"

    urls = _tile_names(grid, 3, name)
    r, ok = _read_into_subgrid(urls, grid, sub, Resampling.mode)
    log.info("WorldCover 2021 : %d tuiles lues (%s)", len(ok), ok)
    return r, ok


def fetch_hansen_lossyear(session, grid, sub, versions=("GFC-2024-v1.12", "GFC-2023-v1.11")):
    """Année de perte de couvert arboré (1 = 2001 … 24 = 2024), Hansen et al. / UMD, CC BY 4.0."""
    from rasterio.enums import Resampling

    for v in versions:
        base = f"https://storage.googleapis.com/earthenginepartners-hansen/{v}"
        try:
            lst = http_get(session, f"{base}/lossyear.txt", expect_json=False, timeout=60, retries=2).text.split()
        except Exception as ex:
            log.warning("Index Hansen %s indisponible : %s", v, ex)
            continue

        def name(la, lo):
            lat_s = f"{la + 10:02d}N" if la + 10 >= 0 else f"{-(la + 10):02d}S"
            lon_s = f"{-lo:03d}W" if lo < 0 else f"{lo:03d}E"
            want = f"_{lat_s}_{lon_s}.tif"
            hit = [u for u in lst if u.endswith(want)]
            return hit[0] if hit else f"{base}/Hansen_{v}_lossyear_{lat_s}_{lon_s}.tif"

        urls = sorted(set(_tile_names(grid, 10, name)))
        r, ok = _read_into_subgrid(urls, grid, sub, Resampling.nearest)
        if ok:
            log.info("Hansen %s : %d tuiles lues ; part de pixels avec perte = %.2f %%", v, len(ok), 100 * (r > 0).mean())
            return r, v
    return None, None


def effective_classes(base, worldcover, lossyear, hp, current_year=2026):
    """Actualise les classes BD Forêt avec le couvert 2021 et les coupes détectées par satellite.

    - perte de couvert depuis ≤ loss_recent_years ans → coupe récente (14), quelle que soit l'essence cartographiée ;
    - perte entre loss_young_years et loss_recent_years ans → jeune peuplement reconstitué (17) ;
    - « sans couvert arboré » BD Forêt (14) redevenu arboré en 2021 → jeune peuplement reconstitué (17) ;
    - hors BD Forêt mais arboré en 2021 → boisement non cartographié (18), essence inconnue.
    """
    eff = base.copy()
    forest_cls = np.isin(base, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 16])
    tree21 = worldcover == 10 if worldcover is not None else np.zeros_like(base, dtype=bool)
    if lossyear is not None:
        age = np.where(lossyear > 0, current_year - (2000 + lossyear.astype(int)), 999)
        recent = (age <= hp["loss_recent_years"])
        young = (age > hp["loss_recent_years"]) & (age <= hp["loss_young_years"])
    else:
        recent = young = np.zeros_like(base, dtype=bool)
    eff[(base == 14) & (tree21 | young) & ~recent] = 17
    eff[forest_cls & young & (base != 11)] = 17
    eff[(forest_cls | (base == 14)) & recent] = 14
    if worldcover is not None:
        eff[(base == 0) & tree21] = 18
    return eff


# ---------------------------------------------------------------------------
# V1.1 — Lithologie BRGM (cartes géologiques harmonisées à 1/50 000)
# ---------------------------------------------------------------------------
LITHO = [
    # clé, libellé, réserve utile 0-30 cm (mm), pH indicatif, hydromorphie (0-1)
    ("inconnue", "Lithologie inconnue", None, None, 0.0),
    ("sable_landes", "Sables éoliens (plateau landais)", 22, 4.5, 0.2),
    ("dune", "Sables dunaires littoraux", 18, 5.5, 0.0),
    ("graves", "Graves, galets, terrasses", 30, 5.5, 0.0),
    ("sable", "Sables (autres formations)", 28, 5.0, 0.0),
    ("limon", "Limons, molasses, colluvions", 55, 6.3, 0.1),
    ("argile_alluvions", "Argiles, alluvions, vases", 70, 6.8, 0.6),
    ("calcaire", "Calcaires, marnes, craie", 45, 7.8, 0.0),
    ("tourbe", "Tourbes, marais", 90, 5.0, 1.0),
]
LITHO_KEYS = [x[0] for x in LITHO]


def classify_litho(text: str) -> int:
    t = norm(text)
    def k(key):
        return LITHO_KEYS.index(key)
    if any(w in t for w in ("tourbe", "marais", "tourbeux")):
        return k("tourbe")
    if "dune" in t:
        return k("dune")
    if "sable" in t and any(w in t for w in ("landes", "eolien", "couverture", "castets", "belin")):
        return k("sable_landes")
    if any(w in t for w in ("calcaire", "craie", "marne", "dolomie", "calcarenite")):
        return k("calcaire")
    if any(w in t for w in ("alluvion", "vase", "fluvio-marin", "fluviomarin", "estuarien", "argile")) and "sable" not in t[:20]:
        return k("argile_alluvions")
    if any(w in t for w in ("grave", "galet", "cailloutis", "terrasse")):
        return k("graves")
    if any(w in t for w in ("limon", "molasse", "colluvion", "loess")):
        return k("limon")
    if "sable" in t or "sablo" in t or "gres" in t:
        return k("sable")
    if "alluvion" in t or "argile" in t:
        return k("argile_alluvions")
    return k("inconnue")


def fetch_brgm_litho(grid, sub, departements=("33", "40", "47", "24", "17", "16")):
    """Rastérise la lithologie BRGM (couche des formations géologiques) sur la sous-grille."""
    import shapefile  # pyshp
    import shapely
    import tempfile, zipfile, os
    from pyproj import Transformer
    from rasterio.features import rasterize
    from rasterio.transform import from_origin
    from shapely.geometry import shape as shp_shape
    import requests

    w, s, e, n = grid.bounds
    out_shape = (grid.size * sub, grid.size * sub)
    transform = from_origin(w, n, grid.dlon / sub, grid.dlat / sub)
    shapes = []
    stats = {"ok": [], "failed": [], "texts": {}, "errors": []}
    from shapely.geometry import box
    roi = box(w, s, e, n)
    for d in departements:
        content = None
        for url in (f"https://infoterre.brgm.fr/telechargements/BDCharm50/GEO050K_HARM_{int(d):03d}.zip",):
            try:
                r = requests.get(url, timeout=900, headers={"User-Agent": "Mozilla/5.0 (CepeRadar/1.1; usage personnel)"}, allow_redirects=True)
                if r.status_code == 200 and r.content[:2] == b"PK":
                    content = r.content
                    break
                msg = f"{url} : HTTP {r.status_code}, {len(r.content)} octets, type {r.headers.get('content-type')}, début {r.content[:80]!r}"
                log.warning("BRGM %s", msg)
                stats["errors"].append(msg[:300])
            except Exception as ex:
                log.warning("BRGM %s : %s", url, ex)
                stats["errors"].append(f"{url} : {str(ex)[:200]}")
        if content is None:
            stats["failed"].append(d)
            continue
        with tempfile.TemporaryDirectory() as tmp:
            zp = os.path.join(tmp, "z.zip")
            open(zp, "wb").write(content)
            with zipfile.ZipFile(zp) as z:
                names = z.namelist()
                shp = [x for x in names if x.lower().endswith(".shp") and "fgeol" in x.lower()]
                if not shp:
                    log.warning("BRGM %s : couche des formations introuvable (%s)", d, [x for x in names if x.endswith('.shp')][:10])
                    stats["failed"].append(d)
                    continue
                z.extractall(tmp)
            path = os.path.join(tmp, shp[0])
            prj = path[:-4] + ".prj"
            src_crs = "EPSG:2154"
            if os.path.exists(prj):
                txt = open(prj, encoding="latin-1").read()
                if "Lambert_Conformal_Conic" not in txt and "GCS" in txt and "PROJCS" not in txt:
                    src_crs = "EPSG:4326"
            tr = Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)
            rd = shapefile.Reader(path, encoding="latin-1")
            fields = [f[0] for f in rd.fields[1:]]
            cnt = 0
            for sr in rd.iterShapeRecords():
                try:
                    g = shp_shape(sr.shape.__geo_interface__)
                except Exception:
                    continue
                g = shapely.transform(g, lambda xy: np.column_stack(tr.transform(xy[:, 0], xy[:, 1])))
                if not g.intersects(roi):
                    continue
                rec = dict(zip(fields, sr.record))
                text = " ".join(str(v) for k, v in rec.items() if isinstance(v, str) and k.upper() in
                                ("DESCR", "DESCRIPTION", "LEGENDE", "NOTATION", "LITHOLOGIE", "LITHO", "TYPE_GEOL", "AP_LOCALE", "NOM"))
                if not text.strip():
                    text = " ".join(str(v) for v in rec.values() if isinstance(v, str))
                c = classify_litho(text)
                key = LITHO_KEYS[c]
                stats["texts"].setdefault(key, {})
                short = text[:90]
                stats["texts"][key][short] = stats["texts"][key].get(short, 0) + 1
                if c > 0:
                    shapes.append((g, c))
                    cnt += 1
            stats["ok"].append(d)
            log.info("BRGM %s : %d polygones utiles (champs %s)", d, cnt, fields[:12])
    if not shapes:
        # Repli : service WFS géologie du BRGM (découverte des couches)
        try:
            shapes += _brgm_wfs_shapes(grid, stats)
        except Exception as ex:
            stats["errors"].append(f"WFS BRGM : {str(ex)[:300]}")
    for key in stats["texts"]:
        stats["texts"][key] = sorted(stats["texts"][key].items(), key=lambda x: -x[1])[:12]
    if not shapes:
        return None, stats
    r = rasterize(shapes, out_shape=out_shape, transform=transform, fill=0, dtype="uint8")
    return r, stats


def _brgm_wfs_shapes(grid, stats):
    """Repli : carte lithologique simplifiée de la France à 1/1 000 000 (WFS BRGM, MapServer).

    Lue avec GDAL/OGR (pyogrio), qui gère le GML et la pagination du WFS.
    """
    import pyogrio
    import shapely
    from pyproj import Transformer
    from shapely.geometry import box

    import requests
    import tempfile
    import xml.etree.ElementTree as ET

    base = "https://geoservices.brgm.fr/geologie"
    sess = requests.Session()
    sess.headers["User-Agent"] = "Mozilla/5.0 (CepeRadar/1.1; usage personnel)"
    r = sess.get(base, params={"SERVICE": "WFS", "REQUEST": "GetCapabilities"}, timeout=120)
    names = [el.text.strip() for el in ET.fromstring(r.content).iter() if el.tag.endswith("Name") and el.text and ":" in el.text]
    stats["wfs_typenames"] = names[:200]
    cands = [x for x in names if re.search(r"LITHO", x, re.I)] + [x for x in names if re.search(r"FGEOL|GEO050K|formation", x, re.I)]
    stats["wfs_candidates"] = cands[:20]
    if not cands:
        return []
    tn = cands[0]
    meta = geoms = fields = None
    for ver, extra in (("1.1.0", {"TYPENAME": tn}), ("1.0.0", {"TYPENAME": tn}), ("2.0.0", {"TYPENAMES": tn})):
        rr = sess.get(base, params={"SERVICE": "WFS", "VERSION": ver, "REQUEST": "GetFeature", **extra}, timeout=600)
        if rr.status_code != 200 or b"Rejected" in rr.content[:400] or b"Exception" in rr.content[:600]:
            stats["errors"].append(f"WFS {tn} v{ver} : HTTP {rr.status_code} {rr.content[:150]!r}")
            continue
        with tempfile.NamedTemporaryFile(suffix=".gml", delete=False) as fh:
            fh.write(rr.content)
            path = fh.name
        try:
            meta, _, geoms, fields = pyogrio.raw.read(path)
            stats["wfs_version"] = ver
            stats["wfs_bytes"] = len(rr.content)
            break
        except Exception as ex:
            stats["errors"].append(f"Lecture GML v{ver} : {str(ex)[:200]}")
    if meta is None:
        return []
    crs = meta.get("crs") or "EPSG:4326"
    names_f = list(meta["fields"])
    stats["wfs_fields"] = names_f
    tr = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    w, s_, e, n = grid.bounds
    roi = box(w, s_, e, n)
    shapes = []
    for k, wkb in enumerate(geoms):
        if wkb is None:
            continue
        g = shapely.from_wkb(wkb)
        g = shapely.transform(g, lambda xy: np.column_stack(tr.transform(xy[:, 0], xy[:, 1])))
        if not g.intersects(roi):
            continue
        text = " ".join(str(fields[i][k]) for i in range(len(names_f)) if isinstance(fields[i][k], str))
        c = classify_litho(text)
        key = LITHO_KEYS[c]
        stats["texts"].setdefault(key, {})
        stats["texts"][key][text[:90]] = stats["texts"][key].get(text[:90], 0) + 1
        if c > 0:
            shapes.append((g, c))
    stats["wfs_layer"] = tn
    stats["scale"] = "1/1 000 000" if "1M" in tn.upper() else "inconnue"
    log.info("WFS BRGM %s (%s) : %d polygones utiles, champs %s", tn, crs, len(shapes), names_f)
    return shapes


def saxton_rawls_ru(sand_pct, clay_pct, soc_gkg, depth_mm=300):
    """Réserve utile (mm) par fonctions de pédotransfert de Saxton & Rawls (2006)."""
    S = np.asarray(sand_pct, float) / 100
    C = np.asarray(clay_pct, float) / 100
    OM = np.clip(np.asarray(soc_gkg, float) * 1.724 / 10, 0.5, 8)
    t15 = -0.024 * S + 0.487 * C + 0.006 * OM + 0.005 * S * OM - 0.013 * C * OM + 0.068 * S * C + 0.031
    wp = t15 + (0.14 * t15 - 0.02)
    t33 = -0.251 * S + 0.195 * C + 0.011 * OM + 0.006 * S * OM - 0.027 * C * OM + 0.452 * S * C + 0.299
    fc = t33 + (1.283 * t33 ** 2 - 0.374 * t33 - 0.015)
    return (fc - wp) * depth_mm


# ---------------------------------------------------------------------------
# V1.1 — Réserve utile des sols (INRAE / GIS Sol, BDGSF 1/1 000 000, Licence Ouverte)
# ---------------------------------------------------------------------------
INRAE_RU_DOI = "doi:10.15454/JPB9RB"


def _parse_ru_class(text) -> float:
    """« 50 à 100 mm », « < 50 », « > 200 » … → valeur centrale en mm (NaN si illisible)."""
    if text is None:
        return np.nan
    if isinstance(text, (int, float)) and np.isfinite(text):
        return float(text) if text > 20 else np.nan  # un code de classe (1, 2, 3…) n'est pas une valeur
    nums = [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", str(text))]
    if not nums:
        return np.nan
    t = str(text)
    if len(nums) >= 2:
        return (nums[0] + nums[1]) / 2
    if "<" in t or "inf" in t.lower() or "moins" in t.lower():
        return nums[0] * 0.75
    if ">" in t or "sup" in t.lower() or "plus" in t.lower():
        return nums[0] * 1.15
    return nums[0]


def fetch_inrae_ru(grid, sub):
    """Rastérise la réserve utile (mm, profil entier) de la BDGSF sur la sous-grille."""
    import os
    import tempfile
    import zipfile

    import pyogrio
    import requests
    import shapely
    from pyproj import Transformer
    from rasterio.features import rasterize
    from rasterio.transform import from_origin
    from shapely.geometry import box

    stats = {"errors": []}
    sess = requests.Session()
    sess.headers["User-Agent"] = "Mozilla/5.0 (CepeRadar/1.1; usage personnel)"
    files = None
    base = None
    for b in ("https://entrepot.recherche.data.gouv.fr", "https://data.inrae.fr"):
        try:
            r = sess.get(f"{b}/api/datasets/:persistentId/", params={"persistentId": INRAE_RU_DOI}, timeout=120)
            files = r.json()["data"]["latestVersion"]["files"]
            base = b
            break
        except Exception as ex:
            stats["errors"].append(f"{b} : {str(ex)[:200]}")
    if not files:
        return None, stats
    stats["files"] = [f["dataFile"]["filename"] for f in files]
    tmp = tempfile.mkdtemp()
    for f in files:
        name = f["dataFile"]["filename"]
        if not re.search(r"\.(shp|shx|dbf|prj|cpg|zip)$", name, re.I):
            continue
        r = sess.get(f"{base}/api/access/datafile/{f['dataFile']['id']}", params={"format": "original"}, timeout=600)
        if r.status_code != 200:
            stats["errors"].append(f"{name} : HTTP {r.status_code}")
            continue
        path = os.path.join(tmp, name)
        open(path, "wb").write(r.content)
        if name.lower().endswith(".zip"):
            with zipfile.ZipFile(path) as z:
                z.extractall(tmp)
    shps = [os.path.join(dp, x) for dp, _, fs in os.walk(tmp) for x in fs if x.lower().endswith(".shp")]
    stats["shapefiles"] = [os.path.basename(x) for x in shps]
    if not shps:
        return None, stats
    meta, _, geoms, fields = pyogrio.raw.read(shps[0])
    names = list(meta["fields"])
    stats["fields"] = names
    # Champ portant la classe de réserve utile. Les champs RESERVE_ / RESERVE_ID / AREA /
    # PERIMETER sont des identifiants ou des géométries : ils ne doivent JAMAIS être lus comme
    # des millimètres. Seules des valeurs textuelles exprimées en mm sont acceptées.
    cand = [i for i, n in enumerate(names) if re.fullmatch(r"(classe|classe_ru|ru|lib.*|libelle.*|class.*)", n, re.I)]
    stats["ru_field"] = [names[i] for i in cand]
    distinct = {}
    for i in cand:
        vals = {}
        for v in fields[i]:
            vals[str(v)] = vals.get(str(v), 0) + 1
        distinct[names[i]] = sorted(vals.items(), key=lambda x: -x[1])[:20]
    stats["distinct_values"] = distinct
    crs = meta.get("crs") or "EPSG:27582"
    tr = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    w, s_, e, n = grid.bounds
    roi = box(w, s_, e, n)
    shapes = []
    examples = {}
    for k, wkb in enumerate(geoms):
        if wkb is None:
            continue
        val = np.nan
        for i in cand:
            raw = fields[i][k]
            if not isinstance(raw, str) or "mm" not in raw.lower():
                continue  # code de classe numérique sans libellé : non interprétable
            val = _parse_ru_class(raw)
            if np.isfinite(val):
                examples[str(fields[i][k])] = round(val)
                break
        if not np.isfinite(val):
            continue
        g = shapely.from_wkb(wkb)
        g = shapely.transform(g, lambda xy: np.column_stack(tr.transform(xy[:, 0], xy[:, 1])))
        if g.intersects(roi):
            shapes.append((g, int(np.clip(round(val), 1, 255))))
    stats["classes"] = examples
    if not shapes and "CLASSE" in names:
        # Codes de classe ordinaux sans libellé (1 à 5 ; 9 = hors sol). Légende officielle non publiée :
        # hypothèse documentée = classes usuelles des cartes de RU (< 50, 50-100, 100-150, 150-200, > 200 mm),
        # sens vérifié par la géographie (les sables landais doivent avoir la plus faible réserve, INRAE).
        ci = names.index("CLASSE")
        coded = []
        for k, wkb in enumerate(geoms):
            try:
                code = int(float(fields[ci][k]))
            except (TypeError, ValueError):
                continue
            if wkb is None or not 1 <= code <= 5:
                continue
            g = shapely.from_wkb(wkb)
            g = shapely.transform(g, lambda xy: np.column_stack(tr.transform(xy[:, 0], xy[:, 1])))
            if g.intersects(roi):
                coded.append((g, code))
        if coded:
            codes_r = rasterize(coded, out_shape=(grid.size * sub, grid.size * sub),
                                transform=from_origin(w, n, grid.dlon / sub, grid.dlat / sub), fill=0, dtype="uint8")
            def box_median(la0, la1, lo0, lo1):
                r0 = int((n - la1) / (grid.dlat / sub)); r1 = int((n - la0) / (grid.dlat / sub))
                c0 = int((lo0 - w) / (grid.dlon / sub)); c1 = int((lo1 - w) / (grid.dlon / sub))
                v = codes_r[r0:r1, c0:c1]
                v = v[v > 0]
                return float(np.median(v)) if len(v) else np.nan
            landes = box_median(44.45, 44.70, -0.90, -0.60)
            other = box_median(44.70, 44.85, -0.35, 0.00)  # Entre-deux-Mers (calcaires, molasses)
            ascending = not (np.isfinite(landes) and np.isfinite(other) and landes > other)
            mids = [37.5, 75, 125, 175, 230] if ascending else [230, 175, 125, 75, 37.5]
            lut = np.zeros(256, dtype=np.uint8)
            for c in range(1, 6):
                lut[c] = int(round(mids[c - 1]))
            stats["assumption"] = {"codes": "1-5 ordinal, 9 = hors sol", "classes_mm": "<50, 50-100, 100-150, 150-200, >200",
                                   "order": "croissant" if ascending else "décroissant",
                                   "median_code_landes": landes, "median_code_entre_deux_mers": other,
                                   "note": "légende officielle non publiée : correspondance supposée, sens vérifié par la géographie"}
            stats["n_polygons"] = len(coded)
            log.info("INRAE BDGSF : codes ordinaux, sens %s (Landes %.1f / Entre-deux-Mers %.1f)", stats["assumption"]["order"], landes, other)
            return lut[codes_r], stats
    stats["n_polygons"] = len(shapes)
    log.info("INRAE BDGSF réserve utile : %d polygones, classes %s", len(shapes), examples)
    if not shapes:
        return None, stats
    r = rasterize(shapes, out_shape=(grid.size * sub, grid.size * sub),
                  transform=from_origin(w, n, grid.dlon / sub, grid.dlat / sub), fill=0, dtype="uint8")
    return r, stats
