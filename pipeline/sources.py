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


def edge_density(raster: np.ndarray, grid, sub) -> np.ndarray:
    forest = np.isin(raster, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 16])
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
