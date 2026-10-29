"""Actualisation quotidienne : météo → contrôles qualité → humidité → scores → fichiers publiés.

Usage : python -m pipeline.update [--kind evening|morning|manual] [--max-age-hours N]
Sorties dans $CEPERADAR_DATA :
  cache/weather.json         historique météo (non publié)
  forecast/latest.json       scores météo W (V1.1 par unité sol × météo, V1 par point) + couches + contrôles
  forecast/points/<k>.json   détail par point météo (indicateurs, humidité par unité, composantes, séries)
  runs/<date>_<kind>.json    archive des prévisions (évaluation a posteriori)
  history.json               résumé de chaque exécution
  status.json                journal technique de la dernière exécution réussie (status_failed.json sinon)
Code de sortie ≠ 0 si les données sont inexploitables : la CI ne remplace alors pas les
prévisions publiées et le site affiche l'ancienneté du dernier jeu valide.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
import traceback
from zoneinfo import ZoneInfo

import numpy as np
import requests

from . import engine, openmeteo
from .common import DATA_DIR, load_params, load_params_v1, log, nan_to_none, read_json, write_json

PARIS = ZoneInfo("Europe/Paris")
DAYS_BEFORE = 7
DAYS_AFTER = 7
# bornes physiques plausibles (valeurs hors bornes → considérées manquantes)
RANGES = {"precip": (0, 250), "tmean": (-25, 45), "tmax": (-20, 48), "tmin": (-30, 40), "et0": (0, 12),
          "tsoil": (-15, 45), "sm": (0, 0.7), "sm2": (0, 0.7), "rh": (0, 100)}


def paris_now() -> dt.datetime:
    return dt.datetime.now(PARIS)


def load_series(cache: dict, n_pts: int, bucket_cfg: dict):
    series = {}
    for k in openmeteo.MAP:
        a = np.array(cache["vars"][k], dtype=float) if k in cache["vars"] else np.full((n_pts, len(cache["dates"])), np.nan)
        a[~np.isfinite(a)] = np.nan
        series[k] = a
    series["bucket"] = engine.bucket_series(series["precip"], series["et0"], bucket_cfg["bucket_max_mm"], bucket_cfg["bucket_kc"])
    series["bucket_max"] = bucket_cfg["bucket_max_mm"]
    return series


def quality_control(series, lats, lons, run_idx):
    """Contrôles automatiques. Renvoie (rapport, points absents, points suspects)."""
    rep = {"missing_rate": {}, "out_of_range": {}, "spatial_outliers": []}
    n = len(lats)
    lo = max(0, run_idx - 40)
    for k, (a, b) in RANGES.items():
        if k not in series:
            continue
        arr = series[k]
        bad = np.isfinite(arr) & ((arr < a) | (arr > b))
        rep["out_of_range"][k] = int(bad.sum())
        arr[bad] = np.nan
        rep["missing_rate"][k] = round(float(np.isnan(arr[:, lo : run_idx + 8]).mean()), 4)
    miss = np.isnan(series["precip"][:, lo:run_idx]).mean(axis=1)
    absent = np.where(miss > 0.1)[0]
    # discontinuités spatiales : cumul 30 j très différent de celui des 6 voisins
    from scipy.spatial import cKDTree
    xy = np.c_[lats * 111.0, lons * 111.0 * np.cos(np.radians(44.8))]
    r30 = np.nansum(series["precip"][:, max(0, run_idx - 30) : run_idx], axis=1)
    _, idx = cKDTree(xy).query(xy, k=min(7, n))
    neigh = np.median(r30[idx[:, 1:]], axis=1)
    mad = np.median(np.abs(r30[idx[:, 1:]] - neigh[:, None]), axis=1) + 5.0
    suspect = np.where(np.abs(r30 - neigh) > 5 * mad)[0]
    rep["spatial_outliers"] = [{"lat": round(float(lats[k]), 3), "lon": round(float(lons[k]), 3), "rain30": round(float(r30[k]), 1),
                                "neighbours": round(float(neigh[k]), 1)} for k in suspect[:20]]
    # séries figées : un point dont la pluie est constante sur 40 jours trahit un défaut de source
    flat = [int(k) for k in range(n) if np.nanstd(series["precip"][k, lo:run_idx]) == 0 and np.nanmean(series["precip"][k, lo:run_idx]) > 0]
    rep["flat_series_points"] = len(flat)
    return rep, absent, suspect


def summarize(Hd: dict, idx: np.ndarray, W: dict, n_dates: int):
    """Indice régional et distribution des scores par espèce et date."""
    out = {}
    all_scores = None
    for s, Ws in W.items():
        rows = []
        h = np.asarray(Hd[s], dtype=float)
        for d in range(n_dates):
            w = np.asarray(Ws[d], dtype=float)
            w = np.where(w == 255, np.nan, w)
            rows.append(np.rint(h * w[idx] / 100.0))
        out[s] = rows
        all_scores = rows if all_scores is None else [np.fmax(a, b) for a, b in zip(all_scores, rows)]
    out["all"] = all_scores
    summ = {}
    for s, rows in out.items():
        summ[s] = []
        for sc in rows:
            v = sc[np.isfinite(sc)]
            if len(v) == 0:
                summ[s].append(None)
                continue
            top = np.sort(v)[-max(1, len(v) // 10):]
            summ[s].append({
                "regional": round(float(top.mean()), 1), "p50": float(np.median(v)), "p90": float(np.percentile(v, 90)),
                "max": float(v.max()), "n60": int((v >= 60).sum()), "n80": int((v >= 80).sum()),
                "share80": round(float((v >= 80).mean()), 4), "share0": round(float((v == 0).mean()), 4),
                "share_lt20": round(float((v < 20).mean()), 4), "unknown": int(len(sc) - len(v)),
                "hist10": np.histogram(v, bins=range(0, 111, 10))[0].tolist(),
            })
    return summ


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="manual", choices=["evening", "morning", "manual"])
    ap.add_argument("--max-age-hours", type=float, default=0, help="ne rien faire si une exécution de ce type a réussi depuis moins de N h")
    args = ap.parse_args(argv)

    t0 = time.time()
    params = load_params()
    params_v1 = load_params_v1()
    mp = params["moisture"]
    now = paris_now()
    status = {"started_at": now.isoformat(timespec="seconds"), "kind": args.kind, "model_version": params["version"],
              "steps": [], "warnings": [], "ok": False}

    prev = read_json(DATA_DIR / "status.json", {})
    if args.max_age_hours and prev.get("ok") and prev.get("kind") == args.kind:
        last = dt.datetime.fromisoformat(prev["finished_at"])
        if (now - last).total_seconds() < args.max_age_hours * 3600:
            log.info("Exécution %s déjà réussie à %s — rien à faire", args.kind, last)
            return 0

    static = read_json(DATA_DIR / "static" / "cells.json")
    if not static or "units" not in static:
        log.error("Couches statiques absentes ou antérieures à la V1.1 : lancer pipeline.build_static")
        return 2
    lats = np.array(static["weather_points"]["lat"])
    lons = np.array(static["weather_points"]["lon"])
    n_pts = len(lats)
    u_wp = np.array(static["units"]["wp"])
    u_ru = np.clip(np.array(static["units"]["ru"], dtype=float), mp["ru_min_mm"], mp["ru_max_mm"])
    n_u = len(u_wp)
    today = now.date()
    latest = None

    try:
        # ---- 1. Météo -----------------------------------------------------------------
        cache_path = DATA_DIR / "cache" / "weather.json"
        cache = read_json(cache_path)
        if cache and (cache.get("lat") != list(map(float, lats)) or cache.get("lon") != list(map(float, lons))):
            log.warning("Points météo modifiés : cache réinitialisé")
            cache = None
        if cache and "sm2" not in cache.get("vars", {}):
            log.warning("Cache antérieur à la V1.1 (sans humidité 9-27 cm) : réinitialisé")
            cache = None
        past_days = 92
        if cache:
            last_run = dt.date.fromisoformat(cache.get("last_run_date", "2000-01-01"))
            past_days = int(np.clip((today - last_run).days + 3, 3, 92))
            have = [dt.date.fromisoformat(x) for x in cache["dates"]]
            if not have or have[0] > today - dt.timedelta(days=60):
                past_days = 92
        budget = {"weight": 0.0, "requests": 0}
        session = requests.Session()
        dates, data, meta, used_vars = openmeteo.fetch(session, lats, lons, past_days=past_days, forecast_days=8, budget=budget)
        cache = openmeteo.merge_cache(cache, dates, data, meta, lats, lons)
        cache["last_run_date"] = today.isoformat()
        cache["updated_at"] = now.isoformat(timespec="seconds")
        write_json(cache_path, cache)
        status["steps"].append({"step": "open-meteo", "ok": True, "past_days": past_days, "requests": budget["requests"],
                                "weight": round(budget["weight"], 1), "variables": used_vars})

        # ---- 2. Séries et contrôles qualité ----------------------------------------------------
        all_dates = [dt.date.fromisoformat(x) for x in cache["dates"]]
        series = load_series(cache, n_pts, params_v1["weather"])
        if today not in all_dates:
            raise RuntimeError(f"La date du jour {today} est absente des données météo")
        run_idx = all_dates.index(today)
        qc, absent, suspect = quality_control(series, lats, lons, run_idx)
        series["bucket"] = engine.bucket_series(series["precip"], series["et0"], params_v1["weather"]["bucket_max_mm"], params_v1["weather"]["bucket_kc"])
        first_valid = int(np.argmax(np.isfinite(np.nanmean(series["precip"], axis=0))))
        qc["first_valid_day"] = all_dates[first_valid].isoformat()
        qc["history_days"] = run_idx - first_valid
        if len(absent) > 0.3 * n_pts:
            raise RuntimeError(f"{len(absent)} points météo sur {n_pts} ont > 10 % de pluie manquante")
        if qc["history_days"] < 45:
            raise RuntimeError(f"Historique météo exploitable insuffisant ({qc['history_days']} jours < 45)")
        if len(absent):
            status["warnings"].append(f"{len(absent)} points météo incomplets : mailles affichées « données absentes »")
        if len(suspect):
            status["warnings"].append(f"{len(suspect)} points météo à cumul de pluie atypique par rapport aux voisins (confiance réduite)")
        for k in ("sm", "sm2"):
            if qc["missing_rate"].get(k, 1) > 0.5:
                status["warnings"].append(f"Humidité modélisée {k} indisponible à {qc['missing_rate'][k]:.0%} : modèle d'humidité réduit au bilan hydrique")
        targets = [run_idx + k for k in range(-DAYS_BEFORE, DAYS_AFTER + 1) if first_valid + 40 <= run_idx + k < len(all_dates)]
        target_dates = [all_dates[t].isoformat() for t in targets]

        # ---- 3. Humidité du sol V1.1 (modèle C hybride) ---------------------------------------------
        envs = []
        layers_sm = []
        for k in ("sm", "sm2"):
            a = series[k]
            if np.isfinite(a).mean() > 0.2:
                envs.append((float(np.nanpercentile(a, mp["model_env_lo_pct"])), float(np.nanpercentile(a, mp["model_env_hi_pct"]))))
                layers_sm.append(a)
        rew_b = engine.rew_from_model(layers_sm, envs) if layers_sm else np.full((n_pts, len(all_dates)), np.nan)
        init = rew_b[u_wp, first_valid]
        rew_a = engine.rew_bucket(series["precip"][u_wp], series["et0"][u_wp], u_ru, mp, init=init)
        rew_c, dis = engine.moisture_hybrid(rew_a, rew_b[u_wp], mp)
        qc["model_moisture_envelopes"] = [[round(a, 3), round(b, 3)] for a, b in envs]

        # ---- 4. Scores V1.1 (par unité) et V1 (par point) --------------------------------------
        su = {k: (v[u_wp] if isinstance(v, np.ndarray) else v) for k, v in series.items()}
        su["rew"] = rew_c
        su["moisture_params"] = mp
        W_out, W_v1, comps = {}, {}, {}
        conf_sp = {}
        for s in engine.SPECIES_ORDER:
            W_out[s], W_v1[s], comps[s], conf_sp[s] = [], [], [], []
            for k, t in enumerate(targets):
                doy = all_dates[t].timetuple().tm_yday
                c = engine.components_for_date(su, t, doy, params["species"][s], params["weather"])
                w = c["W"].copy()
                w[np.isin(u_wp, absent)] = np.nan
                W_out[s].append(engine.to_u8(w))
                comps[s].append(c)
                c1 = engine.components_for_date(series, t, doy, params_v1["species"][s], params_v1["weather"])
                w1 = c1["W"].copy()
                w1[absent] = np.nan
                W_v1[s].append(engine.to_u8(w1))
                conf_sp[s].append(engine.weather_confidence(engine.forecast_share(params["species"][s], t, run_idx), t - run_idx))
        # confiance par unité et par date : échéance × accord des sources d'humidité × contrôle spatial
        uconf = []
        for k, t in enumerate(targets):
            base = conf_sp["edulis"][k]
            d = dis[:, t - 1]
            f = np.where(np.isfinite(d) & (d > mp["disagree"]), 0.65, 1.0)
            f = f * np.where(np.isin(u_wp, suspect), 0.8, 1.0)
            f = f * np.where(np.isfinite(rew_b[u_wp, t - 1]), 1.0, 0.85)  # une seule source d'humidité
            v = np.rint(100 * base * f)
            v[np.isin(u_wp, absent)] = 0
            uconf.append(v.astype(int).tolist())
        conf = {s: [round(100 * c) for c in conf_sp[s]] for s in engine.SPECIES_ORDER}

        cells = static["cells"]
        unit_idx = np.array(cells["unit"])
        wp_idx = np.array(cells["wp"])
        summ = summarize(cells["H"], unit_idx, W_out, len(targets))
        summ_v1 = summarize(cells["H_v1"], wp_idx, W_v1, len(targets))
        tomorrow = (today + dt.timedelta(days=1)).isoformat()
        if tomorrow in target_dates:
            k1 = target_dates.index(tomorrow)
            s1 = summ["all"][k1]
            if s1 and s1["share80"] > 0.5:
                status["warnings"].append("Plus de la moitié des mailles ≥ 80 : distribution suspecte")
            if s1 and s1["share0"] > 0.3:
                status["warnings"].append(f"{s1['share0']:.0%} des mailles à 0 pour demain : vérifier les données")
            hist = read_json(DATA_DIR / "history.json", {"runs": []})
            prev_runs = [r for r in hist["runs"] if r.get("summary", {}).get("all", {}).get(tomorrow)]
            if prev_runs and s1 and prev_runs[-1].get("model_version") == params["version"]:
                old = prev_runs[-1]["summary"]["all"][tomorrow]["regional"]
                if abs(s1["regional"] - old) > 25:
                    status["warnings"].append(f"Variation forte de l'indice régional pour demain ({old} → {s1['regional']})")

        # ---- 5. Couches cartographiques par date -------------------------------------------------
        ind = [engine.indicators_for_date(series, t) for t in targets]
        layers = {key: [nan_to_none(ind[k].get(key, np.full(n_pts, np.nan)), 1) for k in range(len(targets))]
                  for key in ("rain7", "rain14", "rain30", "tmean7", "tsoil7", "dry_days")}
        ulayers = {"rew": [nan_to_none(100 * rew_c[:, t - 1], 0) for t in targets]}

        latest = {
            "generated_at": now.isoformat(timespec="seconds"), "today": today.isoformat(), "kind": args.kind,
            "model_version": params["version"], "dates": target_dates,
            "lead": [t - run_idx for t in targets], "W": W_out, "W_v1": W_v1, "conf": conf, "uconf": uconf,
            "bad_points": absent.tolist(), "suspect_points": suspect.tolist(),
            "layers": layers, "ulayers": ulayers, "summary": summ, "summary_v1": summ_v1, "qc": qc,
            "weather_source": {
                "name": "Open-Meteo — Forecast API (modèles « best match » : Météo-France AROME/ARPEGE, DWD ICON, ECMWF…)",
                "licence": "CC BY 4.0", "url": "https://open-meteo.com",
                "point_spacing_km": "≈ 6,5 × 6,5 km (échantillonnage CèpeRadar)",
                "past": "jours passés = prévisions archivées à courte échéance", "variables": used_vars,
            },
        }
        write_json(DATA_DIR / "forecast" / "latest.json", latest)

        # ---- 6. Détail par point (fiche zone) -----------------------------------------------------
        lo = max(0, run_idx - 37)
        hi = min(len(all_dates), run_idx + 8)
        series_dates = [d.isoformat() for d in all_dates[lo:hi]]
        units_of = {}
        for u, p in enumerate(u_wp.tolist()):
            units_of.setdefault(p, []).append(u)
        pdir = DATA_DIR / "forecast" / "points"
        pdir.mkdir(parents=True, exist_ok=True)
        for old in pdir.glob("*.json"):
            old.unlink()
        rnd = lambda v, d=3: None if not np.isfinite(v) else round(float(v), d)
        for p in range(n_pts):
            bydate = []
            for k, t in enumerate(targets):
                bydate.append({key: rnd(v[p], 2) for key, v in ind[k].items()})
            units = {}
            for u in units_of.get(p, []):
                units[str(u)] = {
                    "lith": int(static["units"]["lith"][u]), "ru": float(u_ru[u]),
                    "rew_a": nan_to_none(100 * rew_a[u, lo:hi], 0), "rew_b": nan_to_none(100 * rew_b[p, lo:hi], 0),
                    "rew": nan_to_none(100 * rew_c[u, lo:hi], 0),
                    "comp": [{s: {key: rnd(comps[s][k][key][u]) for key in
                                  ("W", "R", "M", "T", "S", "frost", "heat", "bonus", "eff_rain", "trigger", "t20", "t7", "ts7", "m")}
                              for s in engine.SPECIES_ORDER} for k in range(len(targets))],
                    "dis": [rnd(dis[u, t - 1], 2) for t in targets],
                }
            write_json(pdir / f"{p}.json", {
                "generated_at": latest["generated_at"], "dates": target_dates, "series_dates": series_dates,
                "today": today.isoformat(), "lat": float(lats[p]), "lon": float(lons[p]),
                "model_lat": (meta[p] or {}).get("lat") if meta else None, "model_lon": (meta[p] or {}).get("lon") if meta else None,
                "model_elev": (meta[p] or {}).get("elev") if meta else None, "suspect": bool(p in set(suspect.tolist())),
                "s": {
                    "precip": nan_to_none(series["precip"][p, lo:hi], 1), "tmin": nan_to_none(series["tmin"][p, lo:hi], 1),
                    "tmax": nan_to_none(series["tmax"][p, lo:hi], 1), "tsoil": nan_to_none(series["tsoil"][p, lo:hi], 1),
                    "sm": nan_to_none(series["sm"][p, lo:hi], 3), "sm2": nan_to_none(series["sm2"][p, lo:hi], 3),
                    "rh": nan_to_none(series["rh"][p, lo:hi], 0),
                },
                "d": bydate, "units": units,
            })

        # ---- 7. Archives et historique ---------------------------------------------------------
        fut = [k for k, t in enumerate(targets) if t >= run_idx]
        write_json(DATA_DIR / "runs" / f"{today.isoformat()}_{args.kind}.json", {
            "generated_at": latest["generated_at"], "model_version": params["version"],
            "dates": [target_dates[k] for k in fut], "W": {s: [W_out[s][k] for k in fut] for s in W_out},
        })
        for f in sorted((DATA_DIR / "runs").glob("*.json")):
            try:
                if dt.date.fromisoformat(f.name[:10]) < today - dt.timedelta(days=60):
                    f.unlink()
            except ValueError:
                pass
        hist = read_json(DATA_DIR / "history.json", {"runs": []})
        hist["runs"] = [r for r in hist["runs"] if not (r["date"] == today.isoformat() and r["kind"] == args.kind)]
        slim = lambda x: None if x is None else {k: v for k, v in x.items() if k != "hist10"}
        hist["runs"].append({"date": today.isoformat(), "kind": args.kind, "at": latest["generated_at"], "model_version": params["version"],
                             "summary": {s: {target_dates[k]: slim(summ[s][k]) for k in fut} for s in summ},
                             "summary_v1": {"all": {target_dates[k]: slim(summ_v1["all"][k]) for k in fut}}})
        hist["runs"] = hist["runs"][-240:]
        write_json(DATA_DIR / "history.json", hist)

        status["ok"] = True
        status["qc"] = qc
        status["steps"].append({"step": "scores", "ok": True, "points": n_pts, "units": n_u, "absent_points": len(absent),
                                "suspect_points": len(suspect), "dates": target_dates})
    except Exception as ex:
        status["error"] = f"{type(ex).__name__}: {ex}"
        status["trace"] = traceback.format_exc()[-2000:]
        log.error("Échec de l'actualisation : %s", ex)
    finally:
        status["finished_at"] = paris_now().isoformat(timespec="seconds")
        status["duration_s"] = round(time.time() - t0, 1)
        write_json(DATA_DIR / ("status.json" if status["ok"] else "status_failed.json"), status, compact=False)
    if status["ok"]:
        log.info("Terminé en %.0f s. Indice régional « tous cèpes » V1.1 : %s | V1 : %s", status["duration_s"],
                 {d: (x or {}).get("regional") for d, x in zip(target_dates, latest["summary"]["all"])},
                 {d: (x or {}).get("regional") for d, x in zip(target_dates, latest["summary_v1"]["all"])})
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
