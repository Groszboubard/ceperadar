"""Validation historique (backtesting) et références climatiques.

1. Récupère des réanalyses ERA5 (Open-Meteo Historical Weather API) 2015 → aujourd'hui
   aux points météo qui concentrent le plus d'observations GBIF de cèpes, et à 3 points
   régionaux fixes (références de pluie « 2015-2024 » pour l'écart aux normales).
2. Recalcule le score météo W de chaque jour avec EXACTEMENT le moteur de production.
3. Tests :
   - temporel : la date d'une observation est-elle mieux classée que les autres jours
     de la même année (même point) ? et que les jours à ±30 j (effet saison retiré) ?
     Comparaison avec un modèle « saison seule ».
   - spatial : la cellule d'une observation a-t-elle un habitat H mieux classé que
     l'ensemble des cellules forestières ? Comparaison avec « couverture forestière seule ».
   Métrique : probabilité moyenne qu'une observation surclasse un témoin (AUC ; 0,5 = hasard).
Biais connus : observations opportunistes (proximité routes/villes, week-ends, sorties
naturalistes), dates de saisie ≠ date de pousse, réanalyse à ~25 km.
"""
from __future__ import annotations

import datetime as dt
import sys
import time
from collections import Counter

import numpy as np
import requests

from . import engine
from .common import DATA_DIR, Grid, http_get, load_params, log, read_json, write_json

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
VARS = ["precipitation_sum", "temperature_2m_mean", "temperature_2m_max", "temperature_2m_min", "et0_fao_evapotranspiration"]
REGIONAL = [("Médoc", 45.15, -0.95), ("Landes girondines", 44.50, -0.80), ("Entre-deux-Mers", 44.75, -0.25)]


def fetch_archive(session, lat, lon, start, end):
    d = http_get(session, ARCHIVE, {"latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "start_date": start.isoformat(),
                                     "end_date": end.isoformat(), "daily": ",".join(VARS), "timezone": "Europe/Paris"},
                 timeout=240, retries=5, backoff=20)
    dates = [dt.date.fromisoformat(x) for x in d["daily"]["time"]]
    get = lambda v: np.array([np.nan if x is None else x for x in d["daily"][v]], dtype=float)[None, :]
    series = {"precip": get("precipitation_sum"), "tmean": get("temperature_2m_mean"), "tmax": get("temperature_2m_max"),
              "tmin": get("temperature_2m_min"), "et0": get("et0_fao_evapotranspiration")}
    return dates, series


def auc_rank(value, reference):
    ref = np.asarray(reference, dtype=float)
    ref = ref[np.isfinite(ref)]
    if not np.isfinite(value) or len(ref) == 0:
        return np.nan
    return float(((ref < value).sum() + 0.5 * (ref == value).sum()) / len(ref))


def summarize(vals):
    v = np.array([x for x in vals if np.isfinite(x)])
    if len(v) == 0:
        return {"n": 0}
    # intervalle bootstrap 90 %
    rng = np.random.default_rng(0)
    boots = [rng.choice(v, len(v)).mean() for _ in range(500)]
    return {"n": int(len(v)), "auc": round(float(v.mean()), 3), "ci90": [round(float(np.percentile(boots, 5)), 3), round(float(np.percentile(boots, 95)), 3)]}


def main():
    params = load_params()
    grid = Grid.from_params(params)
    static = read_json(DATA_DIR / "static" / "cells.json")
    gb = read_json(DATA_DIR / "static" / "gbif.json")
    if not static or not gb:
        log.error("cells.json ou gbif.json manquant")
        return 2
    rg = params["region"]
    today = dt.date.today()
    end = today - dt.timedelta(days=7)
    start = dt.date(2015, 1, 1)

    obs = []
    for o in gb["obs"]:
        if not (o.get("y") and o.get("m") and o.get("d")):
            continue
        if o["y"] < 2015 or (o.get("unc") is not None and o["unc"] > 5000):
            continue
        try:
            d = dt.date(o["y"], o["m"], o["d"])
        except ValueError:
            continue
        if d > end:
            continue
        pi = int(round((o["lat"] - grid.lat0) / rg["weather_dlat"]))
        pj = int(round((o["lon"] - grid.lon0) / rg["weather_dlon"]))
        obs.append({**o, "date_obj": d, "pk": (pi, pj)})
    log.info("Backtest : %d observations GBIF datées (≥ 2015, incertitude ≤ 5 km)", len(obs))

    counts = Counter(o["pk"] for o in obs)
    anchors = [k for k, c in counts.most_common(10) if c >= 3]
    session = requests.Session()
    result = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "period": [start.isoformat(), end.isoformat()],
              "n_obs_total": len(obs), "anchors": [], "temporal": {}, "spatial": {}, "notes": []}

    # ---- références régionales (normales récentes) ------------------------------------------
    normals = {"period": "2015-2024 (ERA5, Open-Meteo)", "points": []}
    for name, la, lo in REGIONAL:
        try:
            dates, s = fetch_archive(session, la, lo, dt.date(2015, 1, 1), dt.date(2024, 12, 31))
            p = s["precip"][0]
            r30 = np.convolve(np.nan_to_num(p), np.ones(30), mode="full")[: len(p)]
            doy = np.array([d.timetuple().tm_yday for d in dates])
            clim = [round(float(np.mean(r30[(doy == k) & (np.arange(len(p)) >= 29)])), 1) for k in range(1, 367)]
            normals["points"].append({"name": name, "lat": la, "lon": lo, "rain30_by_doy": clim})
            time.sleep(40)
        except Exception as ex:
            log.warning("Normales %s indisponibles : %s", name, ex)
    write_json(DATA_DIR / "static" / "normals.json", normals)

    # ---- tests temporels ----------------------------------------------------------------
    per_obs = []
    for pk in anchors:
        la = grid.lat0 + pk[0] * rg["weather_dlat"]
        lo = grid.lon0 + pk[1] * rg["weather_dlon"]
        try:
            dates, s = fetch_archive(session, la, lo, start - dt.timedelta(days=60), end)
        except Exception as ex:
            log.warning("ERA5 indisponible pour %s : %s", pk, ex)
            continue
        s["bucket"] = engine.bucket_series(s["precip"], s["et0"], params["weather"]["bucket_max_mm"], params["weather"]["bucket_kc"])
        s["bucket_max"] = params["weather"]["bucket_max_mm"]
        idx = {d: k for k, d in enumerate(dates)}
        Wd = {}
        Sd = {}
        for sp_key in engine.SPECIES_ORDER:
            sp = params["species"][sp_key]
            w = np.full(len(dates), np.nan)
            ss = np.full(len(dates), np.nan)
            for t in range(45, len(dates)):
                c = engine.components_for_date(s, t, dates[t].timetuple().tm_yday, sp, params["weather"])
                w[t] = c["W"][0]
                ss[t] = c["S"][0]
            Wd[sp_key], Sd[sp_key] = w, ss
        years = np.array([d.year for d in dates])
        ords = np.array([d.toordinal() for d in dates])
        n_here = 0
        for o in obs:
            if o["pk"] != pk or o["date_obj"] not in idx:
                continue
            t = idx[o["date_obj"]]
            w, ss = Wd[o["sp"]], Sd[o["sp"]]
            same_year = years == o["date_obj"].year
            near = same_year & (np.abs(ords - ords[t]) <= 30) & (np.arange(len(dates)) != t)
            per_obs.append({"sp": o["sp"], "year_auc": auc_rank(w[t], w[same_year]), "window_auc": auc_rank(w[t], w[near]),
                            "season_auc": auc_rank(ss[t], ss[same_year]), "W": w[t]})
            n_here += 1
        result["anchors"].append({"lat": round(la, 3), "lon": round(lo, 3), "n_obs": n_here})
        log.info("Ancre %s : %d observations évaluées", pk, n_here)
        time.sleep(40)

    for sp_key in ["all"] + engine.SPECIES_ORDER:
        sel = [r for r in per_obs if sp_key == "all" or r["sp"] == sp_key]
        result["temporal"][sp_key] = {
            "model_vs_year": summarize([r["year_auc"] for r in sel]),
            "season_only_vs_year": summarize([r["season_auc"] for r in sel]),
            "model_vs_pm30days": summarize([r["window_auc"] for r in sel]),
            "median_W_at_obs": round(float(np.nanmedian([r["W"] for r in sel])) * 100, 1) if sel else None,
        }

    # ---- test spatial -------------------------------------------------------------------
    c = static["cells"]
    cell_index = {(i, j): k for k, (i, j) in enumerate(zip(c["i"], c["j"]))}
    forest = np.array(c["forest"], dtype=float)
    spatial = {s: [] for s in ["all"] + engine.SPECIES_ORDER}
    base = []
    n_outside = 0
    for o in gb["obs"]:
        if o.get("unc") is not None and o["unc"] > 1000:
            continue
        i = int(round((o["lat"] - grid.lat0) / grid.dlat))
        j = int(round((o["lon"] - grid.lon0) / grid.dlon))
        k = cell_index.get((i, j))
        if k is None:
            n_outside += 1
            continue
        h = np.array(c["H"][o["sp"]], dtype=float)
        a = auc_rank(h[k], h)
        spatial[o["sp"]].append(a)
        spatial["all"].append(a)
        base.append(auc_rank(forest[k], forest))
    for s, v in spatial.items():
        result["spatial"][s] = summarize(v)
    result["spatial"]["baseline_forest_cover"] = summarize(base)
    result["spatial"]["obs_outside_forest_cells"] = n_outside
    result["notes"] = [
        "AUC = probabilité qu'une observation soit mieux classée qu'un témoin tiré au hasard ; 0,5 = pas mieux que le hasard.",
        "Les observations GBIF sont opportunistes : fortement biaisées vers les lieux accessibles et fréquentés.",
        "Une absence d'observation ne signifie pas une absence de cèpes.",
        "Réanalyse ERA5 (~25 km) : moins fine que les données de production, la comparaison est donc prudente.",
        "Ces chiffres ne constituent PAS une précision prédictive ; ils indiquent seulement si le classement va dans le bon sens.",
    ]
    write_json(DATA_DIR / "static" / "backtest.json", result, compact=False)
    log.info("Backtest temporel : %s", {k: v["model_vs_year"] for k, v in result["temporal"].items()})
    log.info("Backtest spatial : %s", {k: v for k, v in result["spatial"].items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
