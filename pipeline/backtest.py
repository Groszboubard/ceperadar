"""Validation historique V1 / V1.1 (exécutée en CI, mensuellement ou à la demande).

Observations : GBIF (déjà téléchargé par build_static) + iNaturalist (API publique),
dédoublonnées. Filtres : date au jour près ≥ 2015 ; précision ≤ 5 km (test temporel) ou ≤ 1 km
et coordonnées non floutées (test spatial).

Météo : réanalyse ERA5 (Open-Meteo Historical Weather API) aux mailles 0,25° qui concentrent
le plus d'observations, avec l'humidité du sol ERA5 (0-7 et 7-28 cm) pour le modèle hybride.
Le MÊME moteur que la production calcule W (V1 et V1.1) chaque jour depuis 2015.

Tests (AUC = probabilité qu'une observation soit mieux classée qu'un témoin ; 0,5 = hasard) :
  temporel   date observée vs autres jours de l'année / vs ±30 jours (effet saison retiré),
             comparé à un modèle « saison seule » ; séparé années humides / sèches
  spatial    maille observée vs mailles forestières (habitat V1, V1.1, couverture seule)
  sensibilité  variation de l'AUC temporelle quand on déplace les paramètres V1.1
  biais      jours de semaine, distance à Bordeaux
Les paramètres V1.1 n'ont PAS été réglés sur ces observations : toutes servent de test.
Un résultat sur moins de 30 observations est marqué « non concluant ».
"""
from __future__ import annotations

import copy
import datetime as dt
import sys
import time
from collections import Counter

import numpy as np
import requests

from . import engine
from .common import DATA_DIR, Grid, haversine_km, http_get, load_params, load_params_v1, log, read_json, write_json

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
DAILY = ["precipitation_sum", "temperature_2m_mean", "temperature_2m_max", "temperature_2m_min", "et0_fao_evapotranspiration"]
HOURLY = ["soil_moisture_0_to_7cm", "soil_moisture_7_to_28cm"]
REGIONAL = [("Médoc", 45.15, -0.95), ("Landes girondines", 44.50, -0.80), ("Entre-deux-Mers", 44.75, -0.25)]
INAT_TAXA = {"edulis": "Boletus edulis", "pinophilus": "Boletus pinophilus", "aereus": "Boletus aereus", "reticulatus": "Boletus reticulatus"}
N_MIN = 30


def fetch_inat(session, lat0, lon0, radius_km):
    out = []
    for sp, name in INAT_TAXA.items():
        page = 1
        while page <= 20:
            try:
                d = http_get(session, "https://api.inaturalist.org/v1/observations", {
                    "taxon_name": name, "lat": lat0, "lng": lon0, "radius": int(radius_km), "per_page": 200, "page": page,
                    "order_by": "id", "order": "asc"}, timeout=60, retries=3, backoff=5)
            except Exception as ex:
                log.warning("iNaturalist %s page %d : %s", name, page, ex)
                break
            res = d.get("results", [])
            for r in res:
                loc = r.get("location")
                if not loc or not r.get("observed_on"):
                    continue
                la, lo = map(float, loc.split(","))
                taxon = (r.get("taxon") or {}).get("name", "")
                if not taxon.startswith(name):  # identification communautaire différente
                    continue
                out.append({"sp": sp, "lat": la, "lon": lo, "date": r["observed_on"], "unc": r.get("positional_accuracy"),
                            "obscured": bool(r.get("obscured")) or r.get("geoprivacy") in ("obscured", "private"),
                            "grade": r.get("quality_grade"), "src": "iNaturalist", "id": r.get("id")})
            if len(res) < 200:
                break
            page += 1
            time.sleep(1.2)  # politesse envers l'API iNaturalist (≤ 1 requête/s)
        log.info("iNaturalist %s : %d observations cumulées", name, len(out))
    return out


def merge_obs(gbif, inat, today):
    obs = []
    seen = set()
    for o in inat:
        try:
            d = dt.date.fromisoformat(o["date"][:10])
        except ValueError:
            continue
        key = (o["sp"], d, round(o["lat"], 2), round(o["lon"], 2))
        seen.add(key)
        obs.append({**o, "d": d})
    for o in gbif:
        if not (o.get("y") and o.get("m") and o.get("d")) or o.get("lat") is None:
            continue
        try:
            d = dt.date(o["y"], o["m"], o["d"])
        except ValueError:
            continue
        key = (o["sp"], d, round(o["lat"], 2), round(o["lon"], 2))
        if key in seen:
            continue
        seen.add(key)
        obs.append({"sp": o["sp"], "lat": o["lat"], "lon": o["lon"], "date": d.isoformat(), "d": d, "unc": o.get("unc"),
                    "obscured": False, "grade": "research" if o.get("basis") == "HUMAN_OBSERVATION" else o.get("basis"),
                    "src": "GBIF"})
    return [o for o in obs if dt.date(2015, 1, 1) <= o["d"] <= today]


def fetch_era5(session, lat, lon, start, end, daily=DAILY, hourly=HOURLY):
    p = {"latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "start_date": start.isoformat(), "end_date": end.isoformat(),
         "daily": ",".join(daily), "timezone": "Europe/Paris"}
    if hourly:
        p["hourly"] = ",".join(hourly)
    d = http_get(session, ARCHIVE, p, timeout=300, retries=5, backoff=30)
    dates = [dt.date.fromisoformat(x) for x in d["daily"]["time"]]
    arr = lambda v: np.array([np.nan if x is None else x for x in d["daily"][v]], dtype=float)[None, :]
    s = {"precip": arr("precipitation_sum"), "tmean": arr("temperature_2m_mean"), "tmax": arr("temperature_2m_max"),
         "tmin": arr("temperature_2m_min"), "et0": arr("et0_fao_evapotranspiration")}
    if hourly and "hourly" in d:
        days = [t[:10] for t in d["hourly"]["time"]]
        pos = {x.isoformat(): k for k, x in enumerate(dates)}
        inv = np.array([pos.get(x, -1) for x in days])
        for key, var in (("sm", "soil_moisture_0_to_7cm"), ("sm2", "soil_moisture_7_to_28cm")):
            v = np.array([np.nan if x is None else x for x in d["hourly"].get(var, [])], dtype=float)
            if len(v) != len(inv):
                continue
            ok = (inv >= 0) & np.isfinite(v)
            cnt = np.bincount(inv[ok], minlength=len(dates))
            tot = np.bincount(inv[ok], weights=v[ok], minlength=len(dates))
            with np.errstate(invalid="ignore", divide="ignore"):
                s[key] = np.where(cnt >= 18, tot / np.maximum(cnt, 1), np.nan)[None, :]
    return dates, s


def auc_rank(value, reference):
    ref = np.asarray(reference, dtype=float)
    ref = ref[np.isfinite(ref)]
    if not np.isfinite(value) or len(ref) == 0:
        return np.nan
    return float(((ref < value).sum() + 0.5 * (ref == value).sum()) / len(ref))


def summarize(vals):
    v = np.array([x for x in vals if np.isfinite(x)])
    if len(v) == 0:
        return {"n": 0, "conclusive": False}
    rng = np.random.default_rng(0)
    boots = [rng.choice(v, len(v)).mean() for _ in range(1000)]
    lo, hi = float(np.percentile(boots, 5)), float(np.percentile(boots, 95))
    return {"n": int(len(v)), "auc": round(float(v.mean()), 3), "ci90": [round(lo, 3), round(hi, 3)],
            "conclusive": bool(len(v) >= N_MIN and (lo > 0.5 or hi < 0.5))}


def w_series(s, dates, sp_key, params, ru=None):
    """W quotidien (et S) à un point, avec le moteur de production (V1 si params sans 'moisture')."""
    s = dict(s)
    if "moisture" in params:
        mp = params["moisture"]
        envs, layers = [], []
        for k in ("sm", "sm2"):
            if k in s and np.isfinite(s[k]).mean() > 0.2:
                envs.append((np.nanpercentile(s[k], mp["model_env_lo_pct"]), np.nanpercentile(s[k], mp["model_env_hi_pct"])))
                layers.append(s[k])
        b = engine.rew_from_model(layers, envs) if layers else np.full_like(s["precip"], np.nan)
        a = engine.rew_bucket(s["precip"], s["et0"], np.array([ru or mp["ru_default_mm"]]), mp, init=b[:, 0])
        s["rew"], _ = engine.moisture_hybrid(a, b, mp)
        s["moisture_params"] = mp
    else:
        s["bucket"] = engine.bucket_series(s["precip"], s["et0"], params["weather"]["bucket_max_mm"], params["weather"]["bucket_kc"])
    s["bucket_max"] = params["weather"].get("bucket_max_mm", 50)
    sp = params["species"][sp_key]
    w = np.full(len(dates), np.nan)
    ss = np.full(len(dates), np.nan)
    for t in range(60, len(dates)):
        c = engine.components_for_date(s, t, dates[t].timetuple().tm_yday, sp, params["weather"])
        w[t], ss[t] = c["W"][0], c["S"][0]
    return w, ss


def temporal_tests(obs_here, dates, W, S):
    idx = {d: k for k, d in enumerate(dates)}
    years = np.array([d.year for d in dates])
    ords = np.array([d.toordinal() for d in dates])
    rows = []
    for o in obs_here:
        t = idx.get(o["d"])
        if t is None or not np.isfinite(W[o["sp"]][t]):
            continue
        w, ss = W[o["sp"]], S[o["sp"]]
        same = years == o["d"].year
        near = same & (np.abs(ords - ords[t]) <= 30) & (np.arange(len(dates)) != t)
        rows.append({"sp": o["sp"], "year": o["d"].year, "src": o["src"], "grade": o.get("grade"),
                     "year_auc": auc_rank(w[t], w[same]), "window_auc": auc_rank(w[t], w[near]),
                     "season_auc": auc_rank(ss[t], ss[same]), "W": float(w[t])})
    return rows


def main():
    params = load_params()
    params_v1 = load_params_v1()
    grid = Grid.from_params(params)
    static = read_json(DATA_DIR / "static" / "cells.json")
    gb = read_json(DATA_DIR / "static" / "gbif.json", {"obs": []})
    if not static:
        log.error("cells.json manquant")
        return 2
    session = requests.Session()
    today = dt.date.today()
    end = today - dt.timedelta(days=7)
    start = dt.date(2015, 1, 1)

    inat = fetch_inat(session, grid.lat0, grid.lon0, grid.radius_km)
    obs = merge_obs(gb["obs"], inat, end)
    obs = [o for o in obs if haversine_km(grid.lat0, grid.lon0, o["lat"], o["lon"]) <= grid.radius_km]
    write_json(DATA_DIR / "static" / "observations.json", {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               "note": "Observations publiques GBIF + iNaturalist (dates et positions uniquement)",
               "obs": [{k: (v.isoformat() if isinstance(v, dt.date) else v) for k, v in o.items() if k != "d"} for o in obs]})
    t_obs = [o for o in obs if o.get("unc") is None or o["unc"] <= 5000]
    log.info("Observations : %d au total (%d iNaturalist), %d utilisables pour le test temporel", len(obs), len(inat), len(t_obs))

    result = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "period": [start.isoformat(), end.isoformat()],
              "n_obs_total": len(obs), "n_obs_by_source": dict(Counter(o["src"] for o in obs)),
              "n_obs_by_species": dict(Counter(o["sp"] for o in obs)), "n_min": N_MIN,
              "anchors": [], "temporal": {}, "spatial": {}, "sensitivity": {}, "bias": {}, "notes": []}

    # ---- références régionales (pluie 30 j, 2015-2024) -----------------------------------------
    normals = {"period": "2015-2024 (ERA5, Open-Meteo)", "points": []}
    for name, la, lo in REGIONAL:
        try:
            dates, s = fetch_era5(session, la, lo, dt.date(2015, 1, 1), dt.date(2024, 12, 31), daily=["precipitation_sum"], hourly=None)
            p = s["precip"][0]
            r30 = np.convolve(np.nan_to_num(p), np.ones(30), mode="full")[: len(p)]
            doy = np.array([d.timetuple().tm_yday for d in dates])
            clim = [round(float(np.mean(r30[(doy == k) & (np.arange(len(p)) >= 29)])), 1) for k in range(1, 367)]
            normals["points"].append({"name": name, "lat": la, "lon": lo, "rain30_by_doy": clim})
            time.sleep(70)
        except Exception as ex:
            log.warning("Normales %s indisponibles : %s", name, ex)
    write_json(DATA_DIR / "static" / "normals.json", normals)

    # ---- ancres ERA5 (mailles 0,25°) -------------------------------------------------------------
    for o in t_obs:
        o["pk"] = (round(o["lat"] * 4) / 4, round(o["lon"] * 4) / 4)
    counts = Counter(o["pk"] for o in t_obs)
    anchors = [k for k, _ in counts.most_common(15)]
    # RU de l'ancre : lithologie dominante des mailles CèpeRadar à moins de 15 km
    g = static["grid"]
    clat = g["lat0"] + np.array(static["cells"]["i"]) * g["dlat"]
    clon = g["lon0"] + np.array(static["cells"]["j"]) * g["dlon"]
    lith = np.array(static["cells"]["lith"])
    lith_ru = [x["ru_mm"] for x in static["lithology"]]

    rows_v1, rows_v11 = [], []
    sens_specs = {
        "fenetre_pluie_-5j": ("rain_window", -5), "fenetre_pluie_+5j": ("rain_window", +5),
        "ru_22mm": ("ru", 22), "ru_55mm": ("ru", 55), "kc_0.5": ("kc_forest", 0.5), "kc_0.8": ("kc_forest", 0.8),
        "seuils_M_0.10-0.60": ("m", (0.10, 0.60)), "modele_humidite_seul": ("weights", (0.0, 1.0)), "bilan_hydrique_seul": ("weights", (1.0, 0.0)),
    }
    sens_rows = {k: [] for k in sens_specs}
    wet_dry = []
    for k_anchor, pk in enumerate(anchors):
        la, lo = pk
        near = haversine_km(la, lo, clat, clon) < 15
        lk = Counter(lith[near].tolist()).most_common(1)[0][0] if near.any() else 0
        ru = lith_ru[lk] or params["moisture"]["ru_default_mm"]
        try:
            dates, s = fetch_era5(session, la, lo, start - dt.timedelta(days=90), end)
        except Exception as ex:
            log.warning("ERA5 indisponible pour %s : %s", pk, ex)
            continue
        here = [o for o in t_obs if o["pk"] == pk]
        sps = sorted(set(o["sp"] for o in here))
        W1, S1, W2, S2 = {}, {}, {}, {}
        for sp in sps:
            W1[sp], S1[sp] = w_series(s, dates, sp, params_v1)
            W2[sp], S2[sp] = w_series(s, dates, sp, params, ru=ru)
        r1 = temporal_tests(here, dates, W1, S1)
        r2 = temporal_tests(here, dates, W2, S2)
        rows_v1 += r1
        rows_v11 += r2
        # années humides / sèches (pluie sep.-nov. à l'ancre vs médiane des années)
        yrs = sorted(set(d.year for d in dates if d >= start))
        aut = {y: float(np.nansum([s["precip"][0, k] for k, d in enumerate(dates) if d.year == y and d.month in (9, 10, 11)])) for y in yrs}
        med = np.median(list(aut.values()))
        for r in r2:
            wet_dry.append({"wet": aut.get(r["year"], med) >= med, "auc": r["year_auc"]})
        # sensibilité (cèpe de Bordeaux uniquement, espèce la mieux observée)
        if "edulis" in sps:
            ed = [o for o in here if o["sp"] == "edulis"]
            for name, (kind, val) in sens_specs.items():
                p2 = copy.deepcopy(params)
                ru2 = ru
                if kind == "rain_window":
                    p2["species"]["edulis"]["rain_window"] = [max(1, x + val) for x in p2["species"]["edulis"]["rain_window"]]
                    p2["species"]["edulis"]["trigger_window"] = [max(1, x + val) for x in p2["species"]["edulis"]["trigger_window"]]
                elif kind == "ru":
                    ru2 = val
                elif kind == "kc_forest":
                    p2["moisture"]["kc_forest"] = val
                elif kind == "m":
                    p2["moisture"]["m_low"], p2["moisture"]["m_high"] = val
                elif kind == "weights":
                    p2["moisture"]["weight_bucket"], p2["moisture"]["weight_model"] = val
                Wx, Sx = w_series(s, dates, "edulis", p2, ru=ru2)
                sens_rows[name] += temporal_tests(ed, dates, {"edulis": Wx}, {"edulis": Sx})
        result["anchors"].append({"lat": la, "lon": lo, "n_obs": len(r2), "ru_mm": ru, "lithology": static["lithology"][lk]["key"]})
        log.info("Ancre %s (%d/%d) : %d observations évaluées", pk, k_anchor + 1, len(anchors), len(r2))
        time.sleep(280)  # ≤ ~4 000 appels pondérés / heure

    def block(rows, key_filter=None):
        sel = [r for r in rows if key_filter is None or key_filter(r)]
        return {
            "model_vs_year": summarize([r["year_auc"] for r in sel]),
            "season_only_vs_year": summarize([r["season_auc"] for r in sel]),
            "model_vs_pm30days": summarize([r["window_auc"] for r in sel]),
            "median_W_at_obs": round(float(np.nanmedian([r["W"] for r in sel])) * 100, 1) if sel else None,
        }

    for sp_key in ["all"] + engine.SPECIES_ORDER:
        f = None if sp_key == "all" else (lambda r, k=sp_key: r["sp"] == k)
        result["temporal"][sp_key] = {"v1": block(rows_v1, f), "v11": block(rows_v11, f)}
    result["temporal"]["research_grade_only"] = {"v1": block(rows_v1, lambda r: r["grade"] == "research"),
                                                 "v11": block(rows_v11, lambda r: r["grade"] == "research")}
    result["temporal"]["odd_years"] = {"v11": block(rows_v11, lambda r: r["year"] % 2 == 1)}
    result["temporal"]["even_years"] = {"v11": block(rows_v11, lambda r: r["year"] % 2 == 0)}
    result["temporal"]["wet_autumns"] = summarize([r["auc"] for r in wet_dry if r["wet"]])
    result["temporal"]["dry_autumns"] = summarize([r["auc"] for r in wet_dry if not r["wet"]])
    base = summarize([r["year_auc"] for r in rows_v11 if r["sp"] == "edulis"])
    result["sensitivity"] = {"reference_v11_edulis": base,
                             **{k: summarize([r["year_auc"] for r in v]) for k, v in sens_rows.items()}}

    # ---- test spatial ---------------------------------------------------------------------
    c = static["cells"]
    cell_index = {(i, j): k for k, (i, j) in enumerate(zip(c["i"], c["j"]))}
    forest = np.array(c["forest"], dtype=float)
    sp_v1 = {s: [] for s in ["all"] + engine.SPECIES_ORDER}
    sp_v11 = {s: [] for s in ["all"] + engine.SPECIES_ORDER}
    base_cov = []
    outside = 0
    s_obs = [o for o in obs if not o.get("obscured") and o.get("unc") is not None and o["unc"] <= 1000]
    for o in s_obs:
        i = int(round((o["lat"] - grid.lat0) / grid.dlat))
        j = int(round((o["lon"] - grid.lon0) / grid.dlon))
        k = cell_index.get((i, j))
        if k is None:
            outside += 1
            continue
        for store, key in ((sp_v1, "H_v1"), (sp_v11, "H")):
            h = np.array(c[key][o["sp"]], dtype=float)
            a = auc_rank(h[k], h)
            store[o["sp"]].append(a)
            store["all"].append(a)
        base_cov.append(auc_rank(forest[k], forest))
    for s_ in sp_v1:
        result["spatial"][s_] = {"v1": summarize(sp_v1[s_]), "v11": summarize(sp_v11[s_])}
    result["spatial"]["baseline_forest_cover"] = summarize(base_cov)
    result["spatial"]["obs_outside_forest_cells"] = outside
    result["spatial"]["n_precise_obs"] = len(s_obs)

    # ---- biais de déclaration ------------------------------------------------------------------
    wd = Counter(o["d"].weekday() for o in obs)
    d_obs = [haversine_km(grid.lat0, grid.lon0, o["lat"], o["lon"]) for o in obs]
    d_cells = np.array(c["dist"], dtype=float)
    result["bias"] = {
        "weekend_share": round((wd[5] + wd[6]) / max(1, len(obs)), 3), "weekend_expected": round(2 / 7, 3),
        "median_dist_obs_km": round(float(np.median(d_obs)), 1) if d_obs else None,
        "median_dist_forest_km": round(float(np.median(d_cells)), 1),
        "by_month": dict(sorted(Counter(o["d"].month for o in obs).items())),
    }
    result["notes"] = [
        "AUC = probabilité qu'une observation soit mieux classée qu'un témoin tiré au hasard ; 0,5 = hasard.",
        f"Un résultat est « concluant » seulement avec au moins {N_MIN} observations et un intervalle à 90 % qui exclut 0,5.",
        "Les paramètres de la V1.1 n'ont pas été ajustés sur ces observations : elles constituent un jeu de test.",
        "Observations opportunistes : biais vers les lieux accessibles, les week-ends et les années de forte fréquentation ; une absence de donnée ne signifie pas une absence de cèpes.",
        "ERA5 (~25 km) est moins fin que les données de production ; l'humidité du sol ERA5 (0-7 / 7-28 cm) remplace celle d'Open-Meteo (3-9 / 9-27 cm).",
        "Ces chiffres ne mesurent PAS une précision prédictive ; ils indiquent si le classement va dans le bon sens.",
    ]
    write_json(DATA_DIR / "static" / "backtest.json", result, compact=False)
    log.info("Temporel V1 / V1.1 : %s / %s", result["temporal"]["all"]["v1"]["model_vs_year"], result["temporal"]["all"]["v11"]["model_vs_year"])
    log.info("Spatial V1 / V1.1 : %s / %s", result["spatial"]["all"]["v1"], result["spatial"]["all"]["v11"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
