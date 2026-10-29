"""Moteur météorologique de CèpeRadar.

Toutes les fonctions sont vectorisées sur les points météo : chaque série a la forme
(n_points, n_jours). Le score météo W d'une date cible D n'utilise QUE les données des
jours strictement antérieurs à D (un cèpe présent le matin de D s'est développé avant).

Composantes (toutes entre 0 et 1) :
  R  — apport d'eau : pluie efficace sur une fenêtre de délai (noyau trapézoïdal) +
       « déclencheur » = épisode pluvieux marqué survenu 1 à 3 semaines avant.
  M  — humidité actuelle du sol, estimée par un bilan hydrique simple
       (réservoir de 50 mm alimenté par la pluie, vidé par l'ETP Open-Meteo).
  T  — adéquation thermique (moyennes 20 j et 7 j de l'air, 7 j du sol à 6 cm).
  S  — saisonnalité propre à l'espèce.
W = R^a · M^b · T^c · (plancher + (1-plancher)·S) · gel · chaleur · (1 + bonus coup de froid)
"""
from __future__ import annotations

import datetime as dt

import numpy as np

from .common import piecewise, trapezoid

SPECIES_ORDER = ["edulis", "pinophilus", "aereus", "reticulatus"]


# ---------------------------------------------------------------------------
# Bilan hydrique
# ---------------------------------------------------------------------------
def bucket_series(precip: np.ndarray, et0: np.ndarray, bmax: float, kc: float) -> np.ndarray:
    """Réservoir sol (mm) jour par jour. Démarre à mi-capacité ; ~30 j suffisent à l'oublier.

    Les NaN de pluie/ETP sont propagés comme « inconnu » (le réservoir devient NaN
    jusqu'à la fin), afin de ne jamais inventer une humidité.
    """
    n_pts, n_days = precip.shape
    b = np.full(n_pts, bmax / 2.0)
    out = np.empty((n_pts, n_days))
    for t in range(n_days):
        miss = ~(np.isfinite(precip[:, t]) & np.isfinite(et0[:, t]))
        nb = np.clip(b + np.nan_to_num(precip[:, t]) - kc * np.nan_to_num(et0[:, t]), 0.0, bmax)
        # jour inconnu : le réservoir n'est pas mis à jour (pas d'invention) et la valeur
        # du jour est marquée inconnue
        b = np.where(miss, b, nb)
        out[:, t] = np.where(miss, np.nan, b)
    return out


def _window_mean(a: np.ndarray, t: int, n: int) -> np.ndarray:
    lo = max(0, t - n)
    if t - n < 0:
        return np.full(a.shape[0], np.nan)
    return a[:, lo:t].mean(axis=1)


def _window_sum(a: np.ndarray, t: int, n: int) -> np.ndarray:
    if t - n < 0:
        return np.full(a.shape[0], np.nan)
    return a[:, t - n : t].sum(axis=1)


def lag_kernel(window, max_lag=40):
    """Poids par délai d (jours avant la date cible), trapèze [a, b, c, d]."""
    a, b, c, d = window
    lags = np.arange(1, max_lag + 1)
    return lags, trapezoid(lags, a, b, c, d)


# ---------------------------------------------------------------------------
# Composantes
# ---------------------------------------------------------------------------
def components_for_date(series: dict, t: int, doy: int, sp: dict, wp: dict) -> dict:
    """Calcule les composantes du score météo pour la date d'indice t, pour une espèce."""
    P = series["precip"]
    n_pts = P.shape[0]

    # --- R : pluie efficace (cumul pondéré par le délai) + déclencheur -----------------
    lags, k = lag_kernel(sp["rain_window"])
    valid = t - lags >= 0
    lags, k = lags[valid], k[valid]
    rain_lagged = P[:, t - lags]  # (n_pts, n_lags)
    eff = (rain_lagged * k).sum(axis=1)  # mm « efficaces » (≈ cumul dans la fenêtre principale)
    r_cumul = 1.0 - np.exp(-eff / wp["rain_e0_mm"])

    # épisode = somme glissante sur 3 jours se terminant au jour t-lag
    tl, tk = lag_kernel(sp["trigger_window"])
    ok = t - tl - 2 >= 0
    tl, tk = tl[ok], tk[ok]
    s3 = P[:, t - tl] + P[:, t - tl - 1] + P[:, t - tl - 2]
    trig = np.max(np.minimum(1.0, s3 / wp["trigger_full_mm"]) * tk, axis=1) if len(tl) else np.zeros(n_pts)
    R = wp["w_rain_cumul"] * r_cumul + wp["w_rain_trigger"] * trig

    # --- M : humidité du sol (bilan hydrique) -------------------------------------------
    B = series["bucket"] / wp["bucket_max_mm"]
    m_now = B[:, t - 1] if t >= 1 else np.full(n_pts, np.nan)
    m_5 = _window_mean(B, t, 5)
    m = 0.6 * m_now + 0.4 * m_5
    M = np.clip((m - wp["moisture_low"]) / (wp["moisture_high"] - wp["moisture_low"]), 0, 1)
    M = M * M * (3 - 2 * M)  # lissage (smoothstep)

    # --- T : température -----------------------------------------------------------------
    t20 = _window_mean(series["tmean"], t, 20)
    t7 = _window_mean(series["tmean"], t, 7)
    ts7 = _window_mean(series["tsoil"], t, 7) if "tsoil" in series else np.full(n_pts, np.nan)
    f20 = trapezoid(t20, *sp["temp_air20"])
    f7 = trapezoid(t7, *sp["temp_air7"])
    fs = trapezoid(ts7, *sp["temp_soil7"])
    # si la température du sol manque, on renormalise sur l'air seul (pas d'invention)
    with np.errstate(invalid="ignore", divide="ignore"):
        T = np.where(
            np.isfinite(ts7),
            np.power(f20, 0.5) * np.power(f7, 0.25) * np.power(fs, 0.25),
            np.power(f20, 0.667) * np.power(f7, 0.333),
        )

    # --- Saison, gel, chaleur, coup de froid ---------------------------------------------
    S = float(piecewise(doy, sp["season"]))
    tmin3 = np.min(series["tmin"][:, max(0, t - 3) : t], axis=1) if t >= 3 else np.full(n_pts, np.nan)
    frost = np.where(tmin3 <= wp["frost_hard_c"], wp["frost_hard_factor"], np.where(tmin3 <= 0.0, wp["frost_soft_factor"], 1.0))
    frost = np.where(np.isfinite(tmin3), frost, np.nan)
    hot_days = (series["tmax"][:, max(0, t - 7) : t] >= wp["heat_tmax_c"]).sum(axis=1) if t >= 7 else np.zeros(n_pts)
    heat = np.maximum(wp["heat_min_factor"], 1.0 - wp["heat_penalty_per_day"] * hot_days)
    prev = _window_mean(series["tmean"][:, :], t - 7, 14)  # jours t-21 .. t-8
    drop = prev - t7
    bonus = np.zeros(n_pts)
    if sp.get("cold_drop_bonus", 0) > 0 and doy >= 230:
        bonus = sp["cold_drop_bonus"] * np.clip(np.nan_to_num(drop) / 3.0, 0, 1) * (T > 0.3)

    with np.errstate(invalid="ignore"):
        core = np.power(np.clip(R, 0, 1), wp["exp_rain"]) * np.power(M, wp["exp_moist"]) * np.power(T, wp["exp_temp"])
        season_factor = wp["season_floor"] + (1 - wp["season_floor"]) * S
        W = np.clip(core * season_factor * frost * heat * (1 + bonus), 0, 1)

    return {
        "W": W, "R": R, "M": M, "T": T, "S": np.full(n_pts, S), "frost": frost, "heat": heat,
        "bonus": bonus, "eff_rain": eff, "trigger": trig, "t20": t20, "t7": t7, "ts7": ts7,
    }


def indicators_for_date(series: dict, t: int) -> dict:
    """Variables descriptives affichées dans la fiche d'une zone (fenêtres se terminant la veille)."""
    P = series["precip"]
    n_pts, n_days = P.shape
    out = {}
    for n in (1, 3, 5, 7, 10, 14, 21, 30):
        out[f"rain{n}"] = _window_sum(P, t, n)
    # jours consécutifs sans pluie (< 1 mm) jusqu'à la veille
    dry = np.zeros(n_pts)
    alive = np.ones(n_pts, dtype=bool)
    for d in range(1, min(t, 60) + 1):
        is_dry = P[:, t - d] < 1.0
        alive &= is_dry
        dry += alive
    out["dry_days"] = np.where(np.isfinite(P[:, t - 1]), dry, np.nan) if t >= 1 else np.full(n_pts, np.nan)
    out["max_day_14"] = np.max(P[:, max(0, t - 14) : t], axis=1) if t >= 14 else np.full(n_pts, np.nan)
    out["rain_next24"] = P[:, t] if t < n_days else np.full(n_pts, np.nan)
    out["rain_next72"] = P[:, t : t + 3].sum(axis=1) if t + 3 <= n_days else np.full(n_pts, np.nan)
    for n in (3, 7, 14, 21):
        out[f"tmean{n}"] = _window_mean(series["tmean"], t, n)
    out["tmin7"] = np.min(series["tmin"][:, t - 7 : t], axis=1) if t >= 7 else np.full(n_pts, np.nan)
    out["tmax7"] = np.max(series["tmax"][:, t - 7 : t], axis=1) if t >= 7 else np.full(n_pts, np.nan)
    out["amp7"] = _window_mean(series["tmax"] - series["tmin"], t, 7)
    out["cold_nights7"] = (series["tmin"][:, t - 7 : t] <= 8.0).sum(axis=1).astype(float) if t >= 7 else np.full(n_pts, np.nan)
    out["frost_nights7"] = (series["tmin"][:, t - 7 : t] <= 0.0).sum(axis=1).astype(float) if t >= 7 else np.full(n_pts, np.nan)
    out["hot_days7"] = (series["tmax"][:, t - 7 : t] >= 30.0).sum(axis=1).astype(float) if t >= 7 else np.full(n_pts, np.nan)
    if "tsoil" in series:
        out["tsoil7"] = _window_mean(series["tsoil"], t, 7)
        out["tsoil1"] = series["tsoil"][:, t - 1] if t >= 1 else np.full(n_pts, np.nan)
    if "sm" in series:
        out["sm_model"] = series["sm"][:, t - 1] if t >= 1 else np.full(n_pts, np.nan)
        out["sm_model_trend7"] = (series["sm"][:, t - 1] - series["sm"][:, t - 8]) if t >= 8 else np.full(n_pts, np.nan)
    out["bucket_pct"] = 100.0 * series["bucket"][:, t - 1] / series["bucket_max"] if t >= 1 else np.full(n_pts, np.nan)
    out["et0_7"] = _window_sum(series["et0"], t, 7)
    out["balance14"] = _window_sum(P - series["et0"], t, 14)
    out["balance30"] = _window_sum(P - series["et0"], t, 30)
    if "rh" in series:
        out["rh7"] = _window_mean(series["rh"], t, 7)
    if "dew" in series:
        out["dew7"] = _window_mean(series["dew"], t, 7)
    if "sun" in series:
        out["sun7_h"] = _window_mean(series["sun"], t, 7) / 3600.0
    if "rad" in series:
        out["rad7"] = _window_mean(series["rad"], t, 7)
    return out


def forecast_share(sp: dict, t: int, run_idx: int) -> float:
    """Part (0-1) des données d'entrée de la date t qui proviennent de prévisions.

    run_idx = indice du jour de calcul : ce jour est compté à 50 % (journée partiellement
    observée), les suivants à 100 %.
    """
    def fc(day):
        if day < run_idx:
            return 0.0
        return 0.5 if day == run_idx else 1.0

    lags, k = lag_kernel(sp["rain_window"])
    rain_part = sum(kk * fc(t - l) for l, kk in zip(lags, k)) / max(k.sum(), 1e-9)
    temp_part = np.mean([fc(t - l) for l in range(1, 8)])
    return float(0.6 * rain_part + 0.4 * temp_part)


def weather_confidence(share: float, lead_days: int) -> float:
    """Confiance météo (0-1) : baisse avec la part de prévision et l'échéance."""
    return float(np.clip(1.0 - 0.6 * share - 0.05 * max(0, lead_days - 1), 0.05, 0.95))


def compute_all(series: dict, dates: list[dt.date], target_idx: list[int], run_idx: int, params: dict) -> dict:
    """Calcule W (0-100, entier ; 255 = inconnu) par espèce, date cible et point."""
    wp = params["weather"]
    res = {"W": {}, "components": {}, "conf": {}, "indicators": []}
    for s in SPECIES_ORDER:
        sp = params["species"][s]
        res["W"][s] = []
        res["components"][s] = []
        res["conf"][s] = []
        for t in target_idx:
            doy = dates[t].timetuple().tm_yday
            c = components_for_date(series, t, doy, sp, wp)
            res["W"][s].append(c["W"])
            res["components"][s].append(c)
            share = forecast_share(sp, t, run_idx)
            res["conf"][s].append(weather_confidence(share, t - run_idx))
    for t in target_idx:
        res["indicators"].append(indicators_for_date(series, t))
    return res


def to_u8(a: np.ndarray) -> list[int]:
    """0-1 → entier 0-100 ; NaN → 255 (« inconnu »)."""
    a = np.asarray(a, dtype=float)
    out = np.where(np.isfinite(a), np.rint(np.clip(a, 0, 1) * 100), 255).astype(int)
    return out.tolist()
