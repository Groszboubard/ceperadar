"""Actualisation quotidienne : météo → scores → fichiers publiés.

Usage : python -m pipeline.update [--kind evening|morning|manual] [--force]
Sorties dans $CEPERADAR_DATA :
  cache/weather.json         historique météo (non publié)
  forecast/latest.json       scores météo W par espèce/date/point + couches synthétiques
  forecast/points/<k>.json   détail par point météo (indicateurs, composantes, séries)
  runs/<date>_<kind>.json    archive des prévisions (évaluation a posteriori)
  history.json               résumé de chaque exécution
  status.json                journal technique de la dernière exécution
Code de sortie ≠ 0 si les données sont inexploitables : la CI ne publie alors rien et le
site continue d'afficher le dernier jeu valide (avec son ancienneté).
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
from .common import DATA_DIR, load_params, log, nan_to_none, read_json, write_json

PARIS = ZoneInfo("Europe/Paris")
DAYS_BEFORE = 7
DAYS_AFTER = 7


def paris_now() -> dt.datetime:
    return dt.datetime.now(PARIS)


def load_series(cache: dict, n_pts: int, bucket_cfg: dict):
    series = {}
    for k in openmeteo.MAP:
        a = np.array(cache["vars"][k], dtype=float) if k in cache["vars"] else np.full((n_pts, len(cache["dates"])), np.nan)
        a[~np.isfinite(a)] = np.nan
        series[k] = a
    # ETP manquante ponctuelle : interpolation temporelle courte seulement (≤ 2 jours)
    series["bucket"] = engine.bucket_series(series["precip"], series["et0"], bucket_cfg["bucket_max_mm"], bucket_cfg["bucket_kc"])
    series["bucket_max"] = bucket_cfg["bucket_max_mm"]
    return series


def summarize(H: dict, wp_idx: np.ndarray, W: dict, n_dates: int):
    """Indice régional et nombre de cellules favorables, par espèce et date (contrôles + historique)."""
    out = {}
    all_scores = None
    for s, Ws in W.items():
        rows = []
        h = np.asarray(H[s], dtype=float)
        for d in range(n_dates):
            w = np.asarray(Ws[d], dtype=float)
            w = np.where(w == 255, np.nan, w)
            sc = np.rint(h * w[wp_idx] / 100.0)
            rows.append(sc)
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
                "share80": round(float((v >= 80).mean()), 4),
            })
    return summ


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="manual", choices=["evening", "morning", "manual"])
    ap.add_argument("--max-age-hours", type=float, default=0, help="ne rien faire si une exécution de ce type a réussi depuis moins de N h")
    args = ap.parse_args(argv)

    t0 = time.time()
    params = load_params()
    now = paris_now()
    status = {"started_at": now.isoformat(timespec="seconds"), "kind": args.kind, "steps": [], "warnings": [], "ok": False}

    prev = read_json(DATA_DIR / "status.json", {})
    if args.max_age_hours and prev.get("ok") and prev.get("kind") == args.kind:
        last = dt.datetime.fromisoformat(prev["finished_at"])
        if (now - last).total_seconds() < args.max_age_hours * 3600:
            log.info("Exécution %s déjà réussie à %s — rien à faire", args.kind, last)
            print("::notice::already-done")
            return 0

    static = read_json(DATA_DIR / "static" / "cells.json")
    if not static:
        log.error("Couches statiques absentes : lancer d'abord pipeline.build_static")
        return 2
    lats = np.array(static["weather_points"]["lat"])
    lons = np.array(static["weather_points"]["lon"])
    n_pts = len(lats)
    today = now.date()

    try:
        # ---- 1. Météo -----------------------------------------------------------------
        cache_path = DATA_DIR / "cache" / "weather.json"
        cache = read_json(cache_path)
        if cache and (cache.get("lat") != list(map(float, lats)) or cache.get("lon") != list(map(float, lons))):
            log.warning("Points météo modifiés : cache réinitialisé")
            cache = None
        if cache:
            last_run = dt.date.fromisoformat(cache.get("last_run_date", "2000-01-01"))
            past_days = int(np.clip((today - last_run).days + 3, 3, 92))
            have = [dt.date.fromisoformat(x) for x in cache["dates"]]
            if not have or have[0] > today - dt.timedelta(days=60):
                past_days = 92
        else:
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

        # ---- 2. Séries et contrôles ---------------------------------------------------------
        all_dates = [dt.date.fromisoformat(x) for x in cache["dates"]]
        series = load_series(cache, n_pts, params["weather"])
        if today not in all_dates:
            raise RuntimeError(f"La date du jour {today} est absente des données météo")
        run_idx = all_dates.index(today)
        targets = [run_idx + k for k in range(-DAYS_BEFORE, DAYS_AFTER + 1) if 0 <= run_idx + k < len(all_dates)]
        targets = [t for t in targets if t >= 40]  # il faut ≥ 40 jours d'historique pour les fenêtres
        if not targets:
            raise RuntimeError("Historique météo insuffisant (< 40 jours)")
        miss = np.isnan(series["precip"][:, max(0, run_idx - 40) : run_idx]).mean(axis=1)
        bad_pts = np.where(miss > 0.1)[0]
        if len(bad_pts) > 0.3 * n_pts:
            raise RuntimeError(f"{len(bad_pts)} points météo sur {n_pts} ont > 10 % de pluie manquante")
        if len(bad_pts):
            status["warnings"].append(f"{len(bad_pts)} points météo incomplets (scores marqués inconnus)")

        # ---- 3. Scores ------------------------------------------------------------------
        res = engine.compute_all(series, all_dates, targets, run_idx, params)
        target_dates = [all_dates[t].isoformat() for t in targets]
        W_out = {}
        for s in engine.SPECIES_ORDER:
            W_out[s] = []
            for k in range(len(targets)):
                w = np.array(res["W"][s][k], dtype=float)
                w[bad_pts] = np.nan
                W_out[s].append(engine.to_u8(w))
        conf = {s: [round(100 * c) for c in res["conf"][s]] for s in engine.SPECIES_ORDER}

        wp_idx = np.array(static["cells"]["wp"])
        H = static["cells"]["H"]
        summ = summarize(H, wp_idx, W_out, len(targets))
        k1 = target_dates.index((today + dt.timedelta(days=1)).isoformat()) if (today + dt.timedelta(days=1)).isoformat() in target_dates else None
        if k1 is not None and summ["all"][k1] and summ["all"][k1]["share80"] > 0.5:
            status["warnings"].append("Plus de la moitié des cellules ≥ 80 : distribution suspecte, à vérifier")

        # ---- 4. Couches synthétiques par date (affichage carte) -------------------------------
        ind = res["indicators"]
        layers = {}
        for key in ("rain7", "rain14", "rain30", "bucket_pct", "tmean7", "tsoil7", "dry_days"):
            layers[key] = [nan_to_none(ind[k].get(key, np.full(n_pts, np.nan)), 1) for k in range(len(targets))]

        latest = {
            "generated_at": now.isoformat(timespec="seconds"), "today": today.isoformat(), "kind": args.kind,
            "model_version": params["version"], "dates": target_dates,
            "lead": [t - run_idx for t in targets], "W": W_out, "conf": conf, "bad_points": bad_pts.tolist(),
            "layers": layers, "summary": summ,
            "weather_source": {
                "name": "Open-Meteo — Forecast API (modèles « best match » : Météo-France AROME/ARPEGE, DWD ICON, ECMWF…)",
                "licence": "CC BY 4.0", "url": "https://open-meteo.com",
                "point_spacing_km": "≈ 9 × 9 km (échantillonnage CèpeRadar)", "past": "jours passés = prévisions archivées à courte échéance",
                "variables": used_vars,
            },
        }
        write_json(DATA_DIR / "forecast" / "latest.json", latest)

        # ---- 5. Détail par point (fiche zone) -----------------------------------------------------
        lo = max(0, run_idx - 37)
        hi = min(len(all_dates), run_idx + 8)
        series_dates = [d.isoformat() for d in all_dates[lo:hi]]
        points = []
        for p in range(n_pts):
            bydate = []
            for k, t in enumerate(targets):
                item = {key: (None if not np.isfinite(v[p]) else round(float(v[p]), 2)) for key, v in ind[k].items()}
                comp = {}
                for s in engine.SPECIES_ORDER:
                    c = res["components"][s][k]
                    comp[s] = {key: (None if not np.isfinite(c[key][p]) else round(float(c[key][p]), 3))
                               for key in ("R", "M", "T", "S", "frost", "heat", "bonus", "eff_rain", "trigger", "t20", "t7", "ts7")}
                item["comp"] = comp
                bydate.append(item)
            m = (meta[p] or {}) if meta else {}
            points.append({
                "model_lat": m.get("lat"), "model_lon": m.get("lon"), "model_elev": m.get("elev"),
                "s": {
                    "precip": nan_to_none(series["precip"][p, lo:hi], 1), "tmin": nan_to_none(series["tmin"][p, lo:hi], 1),
                    "tmax": nan_to_none(series["tmax"][p, lo:hi], 1), "tsoil": nan_to_none(series["tsoil"][p, lo:hi], 1),
                    "bucket": nan_to_none(100 * series["bucket"][p, lo:hi] / series["bucket_max"], 0),
                    "sm": nan_to_none(series["sm"][p, lo:hi], 3), "rh": nan_to_none(series["rh"][p, lo:hi], 0),
                },
                "d": bydate,
            })
        pdir = DATA_DIR / "forecast" / "points"
        for old in pdir.glob("*.json"):
            old.unlink()
        for p, pt in enumerate(points):
            pt.update({"generated_at": latest["generated_at"], "dates": target_dates, "series_dates": series_dates,
                       "today": today.isoformat(), "lat": float(lats[p]), "lon": float(lons[p])})
            write_json(pdir / f"{p}.json", pt)

        # ---- 6. Archives et historique ---------------------------------------------------------
        fut = [k for k, t in enumerate(targets) if t >= run_idx]
        write_json(DATA_DIR / "runs" / f"{today.isoformat()}_{args.kind}.json", {
            "generated_at": latest["generated_at"], "dates": [target_dates[k] for k in fut],
            "W": {s: [W_out[s][k] for k in fut] for s in W_out},
        })
        # purge des archives > 60 jours
        for f in sorted((DATA_DIR / "runs").glob("*.json")):
            try:
                if dt.date.fromisoformat(f.name[:10]) < today - dt.timedelta(days=60):
                    f.unlink()
            except ValueError:
                pass
        hist = read_json(DATA_DIR / "history.json", {"runs": []})
        hist["runs"] = [r for r in hist["runs"] if not (r["date"] == today.isoformat() and r["kind"] == args.kind)]
        hist["runs"].append({"date": today.isoformat(), "kind": args.kind, "at": latest["generated_at"],
                             "summary": {s: {target_dates[k]: summ[s][k] for k in fut} for s in summ}})
        hist["runs"] = hist["runs"][-240:]
        write_json(DATA_DIR / "history.json", hist)

        status["ok"] = True
        status["steps"].append({"step": "scores", "ok": True, "points": n_pts, "bad_points": len(bad_pts), "dates": target_dates})
    except Exception as ex:
        status["error"] = f"{type(ex).__name__}: {ex}"
        status["trace"] = traceback.format_exc()[-2000:]
        log.error("Échec de l'actualisation : %s", ex)
    finally:
        status["finished_at"] = paris_now().isoformat(timespec="seconds")
        status["duration_s"] = round(time.time() - t0, 1)
        # le statut d'échec est écrit à part pour ne pas écraser le dernier succès
        write_json(DATA_DIR / ("status.json" if status["ok"] else "status_failed.json"), status, compact=False)
    if status["ok"]:
        s1 = latest["summary"]["all"]
        log.info("Terminé en %.0f s. Résumé « tous cèpes » : %s", status["duration_s"],
                 {d: (x or {}).get("regional") for d, x in zip(target_dates, s1)})
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
