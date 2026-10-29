"""Client Open-Meteo (Forecast API) avec découpage par lots, respect des quotas gratuits
et cache incrémental de l'historique (seuls les derniers jours sont re-téléchargés).

Pondération Open-Meteo : poids ≈ n_lieux × (n_jours/14) × (n_variables/10).
Quota gratuit non commercial : 600/min, 5 000/h, 10 000/jour.
"""
from __future__ import annotations

import datetime as dt
import math
import re
import time

import numpy as np

from .common import http_get, log

API = "https://api.open-meteo.com/v1/forecast"
DAILY = [
    "precipitation_sum", "temperature_2m_mean", "temperature_2m_max", "temperature_2m_min",
    "et0_fao_evapotranspiration", "sunshine_duration", "shortwave_radiation_sum",
    "relative_humidity_2m_mean", "dew_point_2m_mean", "precipitation_hours",
]
HOURLY = ["soil_temperature_6cm", "soil_moisture_3_to_9cm", "soil_moisture_9_to_27cm"]
# nom interne ← variable Open-Meteo
MAP = {
    "precip": "precipitation_sum", "tmean": "temperature_2m_mean", "tmax": "temperature_2m_max",
    "tmin": "temperature_2m_min", "et0": "et0_fao_evapotranspiration", "sun": "sunshine_duration",
    "rad": "shortwave_radiation_sum", "rh": "relative_humidity_2m_mean", "dew": "dew_point_2m_mean",
    "phours": "precipitation_hours", "tsoil": "soil_temperature_6cm", "sm": "soil_moisture_3_to_9cm",
    "sm2": "soil_moisture_9_to_27cm",
}
REQUIRED = ["precip", "tmean", "tmax", "tmin", "et0"]


def _weight(n_loc, n_days, n_vars):
    return n_loc * max(1.0, n_days / 14.0) * max(1.0, n_vars / 10.0)


def fetch(session, lats, lons, past_days: int, forecast_days: int = 8, budget: dict | None = None):
    """Renvoie (dates, données {var: (n_pts, n_jours)}, méta par point)."""
    daily = list(DAILY)
    hourly = list(HOURLY)
    n_days = past_days + forecast_days
    per_loc = _weight(1, n_days, len(daily) + len(hourly))
    chunk = max(1, min(150, int(380 // per_loc)))
    n = len(lats)
    results: list[dict | None] = [None] * n
    budget = budget if budget is not None else {"weight": 0.0, "requests": 0}
    i = 0
    while i < n:
        sl = slice(i, min(n, i + chunk))
        params = {
            "latitude": ",".join(f"{x:.4f}" for x in lats[sl]),
            "longitude": ",".join(f"{x:.4f}" for x in lons[sl]),
            "daily": ",".join(daily), "hourly": ",".join(hourly),
            "timezone": "Europe/Paris", "past_days": past_days, "forecast_days": forecast_days,
        }
        try:
            data = http_get(session, API, params, timeout=180, retries=5, backoff=10)
        except RuntimeError as ex:
            msg = str(ex)
            bad = [v for v in daily + hourly if re.search(rf"\b{re.escape(v)}\b", msg)]
            if "HTTP 400" in msg and bad:
                log.warning("Variables refusées par Open-Meteo, retirées : %s", bad)
                daily = [v for v in daily if v not in bad]
                hourly = [v for v in hourly if v not in bad]
                continue
            raise
        if isinstance(data, dict):
            data = [data]
        for k, d in enumerate(data):
            results[sl.start + k] = d
        w = _weight(sl.stop - sl.start, n_days, len(daily) + len(hourly))
        budget["weight"] += w
        budget["requests"] += 1
        log.info("Open-Meteo : points %d–%d / %d (poids %.0f, cumul %.0f)", sl.start, sl.stop - 1, n, w, budget["weight"])
        i = sl.stop
        if i < n:
            # reste sous 600/min et, pour les gros téléchargements, sous ~4 000/h
            planned = per_loc * n
            pace = 60.0 * w / 550.0 if planned < 4500 else 3600.0 * w / 4200.0
            time.sleep(min(400.0, 2.0 + pace))

    # --- assemblage ---------------------------------------------------------------------
    first = next(r for r in results if r)
    dates = [dt.date.fromisoformat(x) for x in first["daily"]["time"]]
    out = {k: np.full((n, len(dates)), np.nan) for k in MAP}
    meta = []
    for p, r in enumerate(results):
        if not r:
            meta.append(None)
            continue
        meta.append({"lat": r.get("latitude"), "lon": r.get("longitude"), "elev": r.get("elevation")})
        dly = r.get("daily", {})
        for key, var in MAP.items():
            if var in dly:
                out[key][p] = np.array([np.nan if v is None else v for v in dly[var]], dtype=float)
        hr = r.get("hourly", {})
        if hr.get("time"):
            days = [t[:10] for t in hr["time"]]
            dindex = {d.isoformat(): k for k, d in enumerate(dates)}
            inv = np.array([dindex.get(d, -1) for d in days])
            okd = inv >= 0
            for key, var in (("tsoil", "soil_temperature_6cm"), ("sm", "soil_moisture_3_to_9cm"), ("sm2", "soil_moisture_9_to_27cm")):
                if var not in hr:
                    continue
                vals = np.array([np.nan if v is None else v for v in hr[var]], dtype=float)
                fin = okd & np.isfinite(vals)
                cnt = np.bincount(inv[fin], minlength=len(dates))
                tot = np.bincount(inv[fin], weights=vals[fin], minlength=len(dates))
                with np.errstate(invalid="ignore", divide="ignore"):
                    out[key][p] = np.where(cnt >= 18, tot / np.maximum(cnt, 1), np.nan)
    return dates, out, meta, {"daily": daily, "hourly": hourly}


def merge_cache(cache: dict | None, dates, data, meta, lats, lons, keep_days=130):
    """Fusionne un nouveau téléchargement dans le cache (les nouvelles valeurs priment,
    sauf valeurs manquantes qui ne remplacent jamais une valeur connue)."""
    n = len(lats)
    if cache:
        old_dates = [dt.date.fromisoformat(x) for x in cache["dates"]]
    else:
        old_dates = []
    all_dates = sorted(set(old_dates) | set(dates))
    all_dates = all_dates[-keep_days:]
    pos = {d: k for k, d in enumerate(all_dates)}
    merged = {}
    for key in MAP:
        arr = np.full((n, len(all_dates)), np.nan)
        if cache and key in cache["vars"]:
            old = np.array(cache["vars"][key], dtype=float)
            for k, d in enumerate(old_dates):
                if d in pos:
                    arr[:, pos[d]] = old[:, k]
        new = data[key]
        for k, d in enumerate(dates):
            if d in pos:
                col = new[:, k]
                m = np.isfinite(col)
                arr[m, pos[d]] = col[m]
        merged[key] = arr
    return {
        "dates": [d.isoformat() for d in all_dates],
        "lat": list(map(float, lats)), "lon": list(map(float, lons)),
        "vars": {k: [[None if not math.isfinite(v) else round(float(v), 3) for v in row] for row in a] for k, a in merged.items()},
        "meta": meta if meta else (cache or {}).get("meta"),
    }
