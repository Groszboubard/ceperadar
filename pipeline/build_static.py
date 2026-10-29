"""Construit les couches statiques (forêt, sol, relief, accès, communes, observations).

Usage : python -m pipeline.build_static [--skip-gbif]
Sortie : $CEPERADAR_DATA/static/{cells.json, gbif.json, static_meta.json}
Exécuté en CI au premier lancement puis une fois par mois (les référentiels évoluent peu).
"""
from __future__ import annotations

import argparse
import collections
import re
import datetime as dt
import sys

import numpy as np
import requests

from . import habitat, sources
from .common import DATA_DIR, Grid, load_params, load_params_v1, log, write_json


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-gbif", action="store_true")
    ap.add_argument("--skip-soil", action="store_true")
    ap.add_argument("--skip-dem", action="store_true")
    args = ap.parse_args(argv)

    params = load_params()
    params_v1 = load_params_v1()
    grid = Grid.from_params(params)
    sub = params["region"]["subpixels"]
    n_classes = len(params["forest_classes"])
    session = requests.Session()
    meta = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "sources": {}}

    circle = grid.in_circle_mask()
    lat, lon = grid.centers()
    w, s, e, n = grid.bounds
    log.info("Grille %d×%d, %d cellules dans le cercle de %.0f km", grid.size, grid.size, circle.sum(), grid.radius_km)

    # ---- 1. BD Forêt V2 --------------------------------------------------------------
    names = sources.wfs_typenames(session)
    tn_forest = sources.find_typename(names, r"FORESTINVENTORY\.V2.*formation", r"FORESTINVENTORY\.V2", r"BDFORET.*V2")
    if not tn_forest:
        log.error("Couche BD Forêt V2 introuvable dans le WFS. Types proches : %s",
                  [x for x in names if "FOREST" in x.upper()][:20])
        sys.exit(2)
    log.info("BD Forêt : couche %s", tn_forest)
    stats = {"requests": 0}
    geoms = []
    tfv_counter = collections.Counter()
    class_counter = collections.Counter()
    prop_keys = set()
    seen = set()
    for tb in sources.tiles(grid.bounds, 0.25):
        # ne charger que les tuiles qui touchent le cercle
        tlat = np.array([tb[1], tb[1], tb[3], tb[3], (tb[1] + tb[3]) / 2])
        tlon = np.array([tb[0], tb[2], tb[0], tb[2], (tb[0] + tb[2]) / 2])
        from .common import haversine_km
        if haversine_km(grid.lat0, grid.lon0, tlat, tlon).min() > grid.radius_km + 25:
            continue
        feats = sources.wfs_fetch(session, tn_forest, tb, stats=stats)
        for g, props in sources.fix_axis(feats, tb):
            prop_keys.update(props.keys())
            fid = props.get("id") or props.get("ID") or props.get("cleabs") or (round(g.area, 12), round(g.centroid.x, 6))
            if fid in seen:
                continue
            seen.add(fid)
            c = sources.classify_bdforet(props)
            low = {k.lower(): v for k, v in props.items()}
            tfv_counter[f"{low.get('code_tfv', '')} | {low.get('tfv', '')} | {low.get('essence', '')}"] += 1
            class_counter[c] += 1
            if c > 0 and not g.is_empty:
                geoms.append((g, c))
        log.info("  tuile %s : %d entités (total %d)", [round(v, 2) for v in tb], len(feats), len(geoms))
    if len(geoms) < 1000:
        log.error("Trop peu de polygones forestiers (%d) : arrêt pour ne pas publier une carte vide", len(geoms))
        sys.exit(3)
    log.info("BD Forêt : %d polygones, %d requêtes. Champs : %s", len(geoms), stats["requests"], sorted(prop_keys))
    for k, v in tfv_counter.most_common(60):
        log.info("  TFV %6d  %s", v, k)
    raster = sources.rasterize_classes(geoms, grid, sub)
    del geoms
    # V1 (pour comparaison) : classes BD Forêt brutes
    n_v1 = len(params_v1["forest_classes"])
    fractions_v1 = sources.block_fractions(raster, grid, sub, n_v1)
    edge_v1 = sources.edge_density(raster, grid, sub, sources.FOREST_CLASSES_V1)
    forest_frac_v1 = fractions_v1[:, :, sources.FOREST_CLASSES_V1].sum(axis=2)

    # V1.1 : actualisation par le couvert arboré 2021 et les coupes détectées par satellite
    wc = ly = None
    try:
        wc, wc_ok = sources.fetch_worldcover(grid, sub)
        if not wc_ok:
            wc = None
    except Exception as ex:
        log.warning("WorldCover indisponible : %s", ex)
    try:
        ly, ly_ver = sources.fetch_hansen_lossyear(session, grid, sub)
    except Exception as ex:
        log.warning("Hansen indisponible : %s", ex)
        ly_ver = None
    eff = sources.effective_classes(raster, wc, ly, params["habitat"])
    change = {}
    for a, b in [(14, 17), (0, 18)]:
        change[f"{a}->{b}"] = int(((raster == a) & (eff == b)).sum())
    change["foret->14 (coupe récente)"] = int((np.isin(raster, sources.FOREST_CLASSES_V1) & (eff == 14)).sum())
    change["foret->17 (coupe 2009-2020)"] = int((np.isin(raster, sources.FOREST_CLASSES_V1) & (eff == 17)).sum())
    px_ha = (grid.dlat / sub * 110574) * (grid.dlon / sub * 111320 * np.cos(np.radians(grid.lat0))) / 1e4
    meta["sources"]["forest_update"] = {
        "worldcover": bool(wc is not None), "hansen": ly_ver, "pixel_ha": round(px_ha, 3),
        "changes_ha": {k: round(v * px_ha) for k, v in change.items()},
        "note": "WorldCover 2021 (ESA, CC BY 4.0) ; Hansen/UMD Global Forest Change (CC BY 4.0).",
    }
    log.info("Actualisation forestière (ha) : %s", meta["sources"]["forest_update"]["changes_ha"])
    del wc, ly
    fractions = sources.block_fractions(eff, grid, sub, n_classes)
    edge = sources.edge_density(eff, grid, sub)
    del raster, eff
    forest_frac = fractions[:, :, sources.FOREST_CLASSES].sum(axis=2)

    # Lithologie BRGM (texture, réserve utile, pH indicatif, hydromorphie)
    litho_r = None
    try:
        litho_r, litho_stats = sources.fetch_brgm_litho(grid, sub)
        meta["sources"]["brgm"] = {"ok": litho_stats["ok"], "failed": litho_stats["failed"], "examples": litho_stats["texts"],
                                   "errors": litho_stats.get("errors", [])[:12], "wfs_layer": litho_stats.get("wfs_layer"),
                                   "wfs_candidates": litho_stats.get("wfs_candidates"), "wfs_typenames": litho_stats.get("wfs_typenames", [])[:60],
                                   "name": "BRGM — cartes géologiques harmonisées 1/50 000 (BD Charm-50)"}
    except Exception as ex:
        log.warning("BRGM indisponible : %s", ex)
        meta["sources"]["brgm"] = {"error": str(ex)[:300]}
    # Réserve utile des sols INRAE (BDGSF 1/1 000 000) : profil entier → couche 0-30 cm (≈ 1/3)
    ru_prof = np.full((grid.size, grid.size), np.nan)
    try:
        ru_r, ru_stats = sources.fetch_inrae_ru(grid, sub)
        meta["sources"]["inrae_ru"] = {**ru_stats, "name": "INRAE / GIS Sol — réserve utile, BDGSF 1/1 000 000", "licence": "Licence Ouverte 2.0"}
        if ru_r is not None:
            nb = grid.size
            tot = ru_r.reshape(nb, sub, nb, sub).astype(np.float32).sum(axis=(1, 3))
            cnt = (ru_r > 0).reshape(nb, sub, nb, sub).sum(axis=(1, 3))
            with np.errstate(invalid="ignore", divide="ignore"):
                ru_prof = np.where(cnt > 0, tot / np.maximum(cnt, 1), np.nan)[::-1, :]
            del ru_r
    except Exception as ex:
        log.warning("Réserve utile INRAE indisponible : %s", ex)
        meta["sources"]["inrae_ru"] = {"error": str(ex)[:300]}
    n_lith = len(sources.LITHO)
    if litho_r is not None:
        lith_fr = sources.block_fractions(litho_r, grid, sub, n_lith)
        del litho_r
    else:
        lith_fr = np.zeros((grid.size, grid.size, n_lith), dtype=np.float32)
        lith_fr[:, :, 0] = 1
    meta["sources"]["bdforet"] = {
        "name": "IGN BD Forêt® V2", "layer": tn_forest, "licence": "Licence Ouverte Etalab 2.0",
        "url": "https://geoservices.ign.fr/bdforet", "polygons": int(sum(class_counter.values())),
        "fields": sorted(prop_keys), "tfv_top": tfv_counter.most_common(80),
        "class_counts": {str(k): v for k, v in sorted(class_counter.items())},
        "note": "Millésimes départementaux variables (prises de vue souvent > 10 ans) ; polygones ≥ 0,5 ha.",
    }

    # ---- 2. Forêts publiques et aires protégées ---------------------------------------
    def fetch_layer_raster(patterns, label):
        tn = sources.find_typename(names, *patterns)
        if not tn:
            log.warning("Couche %s introuvable", label)
            return None, None, []
        feats = sources.fix_axis(sources.wfs_fetch(session, tn, grid.bounds), grid.bounds)
        polys, labels = [], []
        for i, (g, props) in enumerate(feats):
            low = {k.lower(): v for k, v in props.items()}
            nm = low.get("nom") or low.get("nom_site") or low.get("llib_frt") or low.get("libelle") or low.get("nom_foret") or label
            labels.append(str(nm))
            polys.append((g, i + 1))
        log.info("%s : couche %s, %d polygones", label, tn, len(polys))
        if not polys:
            return tn, None, []
        from rasterio.features import rasterize
        from rasterio.transform import from_origin
        r = rasterize(polys, out_shape=(grid.size * sub, grid.size * sub),
                      transform=from_origin(w, n, grid.dlon / sub, grid.dlat / sub), fill=0, dtype="uint16")
        return tn, r, labels

    access = {}
    tn_pub, r_pub, lab_pub = fetch_layer_raster([r"FORETS\.PUBLIQUES", r"FORET.*PUBLIQUE"], "Forêts publiques")
    access["pub_frac"] = sources.block_mean((r_pub > 0).astype(np.float32), grid, sub) if r_pub is not None else np.full((grid.size,) * 2, np.nan)
    candidates = [x for x in names if re.search(r"protect|patrinat|reserv|biotop|apb|rnn|rnr|znieff|natura", x, re.I)]
    meta["wfs_protected_candidates"] = candidates[:80]
    log.info("Couches candidates aires protégées : %s", candidates[:80])
    prot_layers = [
        ([r"PROTECTEDAREAS\.RN:", r"PROTECTEDAREAS\.RN\b", r"(^|[:._])rnn([:._]|$)", r"reserves?_naturelles?_nationales?"], "Réserve naturelle nationale"),
        ([r"PROTECTEDAREAS\.RNR", r"(^|[:._])rnr([:._]|$)", r"reserves?_naturelles?_regionales?"], "Réserve naturelle régionale"),
        ([r"PROTECTEDAREAS\.APB", r"patrinat_apb:", r"(^|[:._])(apb|appb)([:._]|$)", r"biotope"], "Arrêté de protection de biotope"),
        ([r"PROTECTEDAREAS\.RB:", r"patrinat_rb:", r"(^|[:._])rb([:._]|$)", r"reserves?_biologiques?"], "Réserve biologique"),
    ]
    prot_frac = np.zeros((grid.size, grid.size), dtype=np.float32)
    prot_name = np.full((grid.size, grid.size), -1, dtype=int)
    prot_names: list[str] = []
    meta["sources"]["protected"] = []
    for pats, label in prot_layers:
        try:
            tn, r, labels = fetch_layer_raster(pats, label)
        except Exception as ex:
            log.warning("Aires protégées %s indisponibles : %s", label, ex)
            continue
        meta["sources"]["protected"].append({"type": label, "layer": tn, "n": len(labels)})
        if r is None:
            continue
        frac = sources.block_mean((r > 0).astype(np.float32), grid, sub)
        # nom majoritaire par cellule
        nb = grid.size
        blocks = r.reshape(nb, sub, nb, sub).transpose(0, 2, 1, 3).reshape(nb, nb, sub * sub)[::-1]
        for (i, j) in zip(*np.where(frac > 0)):
            vals = blocks[i, j][blocks[i, j] > 0]
            v = int(np.bincount(vals).argmax())
            if frac[i, j] > prot_frac[i, j]:
                nm = f"{label} — {labels[v - 1]}"
                if nm not in prot_names:
                    prot_names.append(nm)
                prot_name[i, j] = prot_names.index(nm)
        prot_frac = np.maximum(prot_frac, frac)
    meta["sources"]["public_forests"] = {"layer": tn_pub, "n": len(lab_pub), "name": "Forêts publiques (ONF) — Géoplateforme"}

    # ---- 3. Communes -------------------------------------------------------------------
    communes = sources.fetch_communes(session)
    mf = params["region"]["min_forest_fraction"]
    sel = circle & ((forest_frac >= mf) | (forest_frac_v1 >= mf))
    pts = np.column_stack([lon[sel], lat[sel]])
    com_idx = sources.assign_points(pts, communes)
    used = sorted(set(com_idx.tolist()))
    remap = {old: k for k, old in enumerate(used)}
    commune_names = [communes[i][1] for i in used]
    commune_codes = [communes[i][2] for i in used]

    # ---- 4. Sol (SoilGrids) ------------------------------------------------------------
    if args.skip_soil:
        soil = {k: np.full(lat.shape, np.nan) for k in ("ph", "sand", "clay", "soc")}
    else:
        soil = sources.fetch_soilgrids(session, grid, lat, lon)
    meta["sources"]["soilgrids"] = {"name": "SoilGrids 2.0 (ISRIC)", "licence": "CC BY 4.0", "resolution": "250 m (modélisé)",
                                    "valid_ph": float(np.isfinite(soil["ph"][sel]).mean())}

    # ---- 5. Relief (Copernicus DEM) ------------------------------------------------------
    if args.skip_dem:
        dem = {k: np.full(lat.shape, np.nan) for k in ("elev", "slope", "north_share", "tpi")}
        dem["ok"] = False
    else:
        dem = sources.fetch_dem(grid)
    meta["sources"]["dem"] = {"name": "Copernicus DEM GLO-30", "licence": "Licence Copernicus DEM (libre, attribution)", "ok": bool(dem["ok"])}

    # ---- 6. Habitat ----------------------------------------------------------------------
    lf = lith_fr[sel].astype(float)                      # parts de lithologie par cellule
    known = lf[:, 1:].sum(axis=1)
    lith_major = np.where(known > 0.3, np.argmax(lf[:, 1:], axis=1) + 1, 0)
    lith_ph = np.array([np.nan if x[3] is None else x[3] for x in sources.LITHO])
    lith_ru = np.array([np.nan if x[2] is None else x[2] for x in sources.LITHO])
    lith_hyd = np.array([x[4] for x in sources.LITHO])
    with np.errstate(invalid="ignore", divide="ignore"):
        ph_litho = np.where(known > 0.3, (lf[:, 1:] * np.nan_to_num(lith_ph[1:])).sum(axis=1) / np.maximum(known, 1e-9), np.nan)
        hydro = np.where(known > 0.3, (lf[:, 1:] * lith_hyd[1:]).sum(axis=1) / np.maximum(known, 1e-9), 0.0)
    cells_static = {
        "fractions": fractions[sel].astype(float), "forest_frac": forest_frac[sel].astype(float),
        "edge": edge[sel].astype(float), "ph": ph_litho, "hydro": hydro, "slope": dem["slope"][sel],
        "north_share": dem["north_share"][sel], "tpi": dem["tpi"][sel],
    }
    H = habitat.habitat_scores(cells_static, params)
    mix = habitat.mix_index(cells_static["fractions"])
    # V1 recalculée à l'identique pour la comparaison
    cells_v1 = {
        "fractions": fractions_v1[sel].astype(float), "forest_frac": forest_frac_v1[sel].astype(float),
        "edge": edge_v1[sel].astype(float), "ph": soil["ph"][sel], "slope": dem["slope"][sel],
        "north_share": dem["north_share"][sel], "tpi": dem["tpi"][sel],
    }
    H_v1 = habitat.habitat_scores(cells_v1, params_v1)
    unk = (cells_static["fractions"][:, [17, 18]].sum(axis=1) / np.maximum(cells_static["forest_frac"], 1e-9))

    # ---- 7. Points météo -----------------------------------------------------------------
    rg = params["region"]
    pi = np.rint((lat[sel] - grid.lat0) / rg["weather_dlat"]).astype(int)
    pj = np.rint((lon[sel] - grid.lon0) / rg["weather_dlon"]).astype(int)
    keys = sorted(set(zip(pi.tolist(), pj.tolist())))
    kidx = {k: t for t, k in enumerate(keys)}
    wp_idx = np.array([kidx[(a, b)] for a, b in zip(pi.tolist(), pj.tolist())])
    wp_lat = [round(grid.lat0 + a * rg["weather_dlat"], 4) for a, _ in keys]
    wp_lon = [round(grid.lon0 + b * rg["weather_dlon"], 4) for _, b in keys]
    log.info("%d cellules forestières, %d points météo", sel.sum(), len(keys))
    # unités de calcul de l'humidité : point météo × lithologie dominante × classe de réserve utile
    mpar = params["moisture"]
    ru30_cell = np.clip(ru_prof[sel] / 3.0, mpar["ru_min_mm"], mpar["ru_max_mm"])
    ru_bin = np.where(np.isfinite(ru30_cell), np.digitize(np.nan_to_num(ru30_cell), [20, 28, 38, 50, 65]), -1)
    keys3 = list(zip(wp_idx.tolist(), lith_major.tolist(), ru_bin.tolist()))
    ukeys = sorted(set(keys3))
    uidx = {k: t for t, k in enumerate(ukeys)}
    unit_idx = np.array([uidx[k] for k in keys3])
    ru_default = mpar["ru_default_mm"]
    unit_ru = []
    for t, (a, b, c) in enumerate(ukeys):
        if not np.isnan(lith_ru[b]):
            unit_ru.append(float(lith_ru[b]))           # géologie BRGM 1/50 000 (prioritaire)
        elif c >= 0:
            unit_ru.append(float(np.nanmedian(ru30_cell[unit_idx == t])))  # sols INRAE 1/1 000 000
        else:
            unit_ru.append(float(ru_default))
    units = {"wp": [a for a, _, _ in ukeys], "lith": [b for _, b, _ in ukeys], "ru": [round(x, 1) for x in unit_ru]}
    meta["ru_source_share"] = {"brgm": round(float((lith_major > 0).mean()), 3),
                               "inrae": round(float(((lith_major == 0) & np.isfinite(ru30_cell)).mean()), 3),
                               "defaut": round(float(((lith_major == 0) & ~np.isfinite(ru30_cell)).mean()), 3)}
    log.info("Origine de la réserve utile : %s", meta["ru_source_share"])
    log.info("%d unités de calcul de l'humidité (point météo × lithologie)", len(ukeys))

    # ---- 8. Confiance statique -----------------------------------------------------------
    conf = np.full(sel.sum(), 85.0)
    conf -= np.where(lith_major > 0, 0, np.where(np.isfinite(ru30_cell), 5, 10))  # sol connu au 1/50 000, au 1/1 000 000, ou inconnu
    conf -= np.where(np.isfinite(cells_static["slope"]), 0, 5)
    conf -= np.where(cells_static["forest_frac"] < 0.15, 10, 0)
    conf -= 20 * np.clip(unk, 0, 1)                               # essence non cartographiée
    if not meta["sources"]["forest_update"]["worldcover"] or not meta["sources"]["forest_update"]["hansen"]:
        conf -= 5

    # ---- 9. Écriture ------------------------------------------------------------------------
    ii, jj = np.where(sel)  # ii : ligne sud→nord (0..2N), jj : colonne
    fr = cells_static["fractions"]
    order = np.argsort(-fr[:, 1:], axis=1)[:, :3] + 1
    topv = np.take_along_axis(fr, order, axis=1)
    dist = grid.distance_km()[sel]

    def ints(a, scale=1.0, nan=-1):
        a = np.asarray(a, dtype=float) * scale
        return np.where(np.isfinite(a), np.rint(a), nan).astype(int).tolist()

    cells = {
        "i": (ii - grid.n).tolist(), "j": (jj - grid.n).tolist(),
        "wp": wp_idx.tolist(), "com": [remap[c] for c in com_idx.tolist()],
        "dist": ints(dist), "forest": ints(cells_static["forest_frac"], 100),
        "c1": order[:, 0].tolist(), "p1": ints(topv[:, 0], 100),
        "c2": order[:, 1].tolist(), "p2": ints(topv[:, 1], 100),
        "c3": order[:, 2].tolist(), "p3": ints(topv[:, 2], 100),
        "edge": ints(cells_static["edge"], 100), "mix": ints(mix, 100),
        "ph": ints(cells_static["ph"], 10), "sand": ints(soil["sand"][sel]), "clay": ints(soil["clay"][sel]),
        "soc": ints(soil["soc"][sel]),
        "elev": ints(dem["elev"][sel]), "slope": ints(dem["slope"][sel], 10), "north": ints(dem["north_share"][sel], 100),
        "tpi": ints(dem["tpi"][sel]),
        "pub": ints(access["pub_frac"][sel], 100), "prot": ints(prot_frac[sel], 100), "protn": prot_name[sel].tolist(),
        "conf": ints(conf),
        "H": {s: ints(H[s], 100) for s in params["species"]},
        "H_v1": {s: ints(H_v1[s], 100) for s in params["species"]},
        "unit": unit_idx.tolist(), "lith": lith_major.tolist(), "ru": ints(ru30_cell), "hydro": ints(hydro, 100), "unk": ints(unk, 100),
        "forest_v1": ints(cells_v1["forest_frac"], 100),
    }
    out = {
        "version": params["version"], "generated_at": meta["generated_at"],
        "grid": {"lat0": grid.lat0, "lon0": grid.lon0, "dlat": grid.dlat, "dlon": grid.dlon, "n": grid.n, "radius_km": grid.radius_km},
        "communes": commune_names, "commune_codes": commune_codes, "protected_names": prot_names,
        "weather_points": {"lat": wp_lat, "lon": wp_lon},
        "units": units,
        "lithology": [{"key": x[0], "label": x[1], "ru_mm": x[2], "ph": x[3], "hydro": x[4]} for x in sources.LITHO],
        "cells": cells,
    }
    write_json(DATA_DIR / "static" / "cells.json", out)

    # résumé de contrôle
    for s in params["species"]:
        h = np.asarray(cells["H"][s]); h1 = np.asarray(cells["H_v1"][s])
        log.info("Habitat %-12s : V1.1 médiane %3d p90 %3d | V1 médiane %3d p90 %3d", s, np.median(h), np.percentile(h, 90), np.median(h1), np.percentile(h1, 90))
    meta["lithology_share"] = {sources.LITHO_KEYS[k]: round(float((lith_major == k).mean()), 3) for k in range(len(sources.LITHO))}
    meta["summary"] = {"cells": int(sel.sum()), "weather_points": len(keys),
                       "habitat_p50": {s: float(np.median(cells["H"][s])) for s in params["species"]},
                       "habitat_p90": {s: float(np.percentile(cells["H"][s], 90)) for s in params["species"]},
                       "habitat_v1_p50": {s: float(np.median(cells["H_v1"][s])) for s in params["species"]},
                       "units": len(units["wp"])}

    # ---- 10. GBIF -----------------------------------------------------------------------------
    if not args.skip_gbif:
        try:
            obs = sources.fetch_gbif(session, grid.bounds)
            from .common import haversine_km
            keep = [o for o in obs if o["lat"] is not None and haversine_km(grid.lat0, grid.lon0, o["lat"], o["lon"]) <= grid.radius_km]
            write_json(DATA_DIR / "static" / "gbif.json", {"generated_at": meta["generated_at"], "licence_note":
                       "Occurrences GBIF.org (licences CC0 / CC BY / CC BY-NC selon jeu de données)", "obs": keep})
            meta["sources"]["gbif"] = {"n": len(keep), "url": "https://www.gbif.org"}
            log.info("GBIF : %d observations dans le cercle", len(keep))
        except Exception as ex:
            log.warning("GBIF indisponible : %s", ex)
            meta["sources"]["gbif"] = {"error": str(ex)[:200]}
    write_json(DATA_DIR / "static" / "static_meta.json", meta, compact=False)
    log.info("Couches statiques écrites dans %s", DATA_DIR / "static")


if __name__ == "__main__":
    main()
