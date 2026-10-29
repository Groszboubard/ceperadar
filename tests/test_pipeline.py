"""Test d'intégration hors ligne de pipeline.update : Open-Meteo est simulé (données
SYNTHÉTIQUES, écrites dans un dossier temporaire, jamais publiées)."""
import datetime as dt
import json

import numpy as np

from pipeline import openmeteo, update
from pipeline.common import load_params


def fake_fetch(session, lats, lons, past_days, forecast_days=8, budget=None):
    today = update.paris_now().date()
    dates = [today - dt.timedelta(days=past_days) + dt.timedelta(days=k) for k in range(past_days + forecast_days)]
    n, m = len(lats), len(dates)
    rng = np.random.default_rng(1)
    data = {k: np.full((n, m), np.nan) for k in openmeteo.MAP}
    data["precip"] = np.where(rng.random((n, m)) < 0.3, rng.gamma(2, 5, (n, m)), 0.0)
    data["tmean"] = np.full((n, m), 13.0)
    data["tmax"] = data["tmean"] + 5
    data["tmin"] = data["tmean"] - 5
    data["et0"] = np.full((n, m), 1.2)
    data["tsoil"] = np.full((n, m), 13.5)
    data["sm"] = np.full((n, m), 0.25)
    data["sm2"] = np.full((n, m), 0.28)
    data["precip"][1, :] = np.nan  # un point défaillant
    if budget is not None:
        budget["weight"] += 1
        budget["requests"] += 1
    return dates, data, [{"lat": a, "lon": b, "elev": 10} for a, b in zip(lats, lons)], {"daily": [], "hourly": []}


def test_update_end_to_end(tmp_path, monkeypatch):
    P = load_params()
    static = {
        "weather_points": {"lat": [44.8, 44.9, 45.0, 44.7], "lon": [-0.6, -0.7, -0.8, -0.5]},
        "units": {"wp": [0, 1, 2, 3], "lith": [1, 0, 7, 0], "ru": [22, 35, 45, 35]},
        "cells": {"wp": [0, 0, 1, 2], "unit": [0, 0, 1, 2], "H": {s: [80, 40, 60, 10] for s in P["species"]},
                  "H_v1": {s: [70, 40, 50, 10] for s in P["species"]}},
    }
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "cells.json").write_text(json.dumps(static))
    monkeypatch.setattr(update, "DATA_DIR", tmp_path)
    monkeypatch.setattr(openmeteo, "fetch", fake_fetch)
    assert update.main(["--kind", "evening"]) == 0
    latest = json.loads((tmp_path / "forecast" / "latest.json").read_text())
    assert len(latest["dates"]) == 15 and latest["today"] in latest["dates"]
    assert latest["bad_points"] == [1]
    assert all(v == 255 for d in latest["W"]["edulis"] for k, v in enumerate(d) if k == 1)  # unité du point absent
    assert all(v == 255 for d in latest["W_v1"]["edulis"] for k, v in enumerate(d) if k == 1)
    assert len(latest["uconf"][0]) == 4 and latest["uconf"][0][1] == 0
    assert "qc" in latest and latest["summary_v1"]["all"]
    assert (tmp_path / "forecast" / "points" / "2.json").exists()
    st = json.loads((tmp_path / "status.json").read_text())
    assert st["ok"]
    # deuxième exécution : téléchargement incrémental (cache réutilisé)
    calls = []
    monkeypatch.setattr(openmeteo, "fetch", lambda *a, **k: calls.append(k["past_days"]) or fake_fetch(*a, **k))
    assert update.main(["--kind", "morning"]) == 0
    assert calls == [3]
    # garde anti-doublon
    assert update.main(["--kind", "morning", "--max-age-hours", "6"]) == 0
    assert calls == [3]
