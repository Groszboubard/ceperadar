"""Outils communs : paramètres, grille spatiale, HTTP robuste, journalisation."""
from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
PARAMS_PATH = ROOT / "model" / "params.json"
# Le répertoire de données (branche `data` extraite par la CI, ou dossier local)
DATA_DIR = Path(os.environ.get("CEPERADAR_DATA", ROOT / "data"))

log = logging.getLogger("ceperadar")
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

USER_AGENT = "CepeRadar/1.0 (usage personnel non commercial; https://github.com/Groszboubard/ceperadar)"


def load_params() -> dict:
    with open(PARAMS_PATH, encoding="utf-8") as f:
        return json.load(f)


def haversine_km(lat1, lon1, lat2, lon2):
    """Distance géodésique (sphère de rayon moyen 6371,0088 km) — écart < 0,5 % avec l'ellipsoïde."""
    r = 6371.0088
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


@dataclass
class Grid:
    """Grille régulière en degrés (~1 km × 1 km) centrée sur Bordeaux.

    La cellule (i, j) avec i, j ∈ [-N, N] a pour centre
    lat = lat0 + i·dlat ; lon = lon0 + j·dlon. Identifiant = (i+N)·(2N+1) + (j+N).
    """

    lat0: float
    lon0: float
    dlat: float
    dlon: float
    n: int
    radius_km: float

    @classmethod
    def from_params(cls, p: dict) -> "Grid":
        r = p["region"]
        return cls(r["center_lat"], r["center_lon"], r["cell_dlat"], r["cell_dlon"], r["half_cells"], r["radius_km"])

    @property
    def size(self) -> int:
        return 2 * self.n + 1

    @property
    def bounds(self):
        """(west, south, east, north) de l'emprise complète de la grille."""
        return (
            self.lon0 - (self.n + 0.5) * self.dlon,
            self.lat0 - (self.n + 0.5) * self.dlat,
            self.lon0 + (self.n + 0.5) * self.dlon,
            self.lat0 + (self.n + 0.5) * self.dlat,
        )

    def centers(self):
        idx = np.arange(-self.n, self.n + 1)
        lat = self.lat0 + idx * self.dlat  # lignes du sud au nord
        lon = self.lon0 + idx * self.dlon
        lon2, lat2 = np.meshgrid(lon, lat)
        return lat2, lon2

    def in_circle_mask(self) -> np.ndarray:
        lat, lon = self.centers()
        return haversine_km(self.lat0, self.lon0, lat, lon) <= self.radius_km

    def distance_km(self) -> np.ndarray:
        lat, lon = self.centers()
        return haversine_km(self.lat0, self.lon0, lat, lon)


def http_get(session, url, params=None, *, timeout=120, retries=4, backoff=8.0, expect_json=True, ok_codes=(200,)):
    """GET avec nouvelles tentatives exponentielles. Lève la dernière erreur si tout échoue."""
    last = None
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=timeout, headers={"User-Agent": USER_AGENT})
            if r.status_code in ok_codes:
                return r.json() if expect_json else r
            if r.status_code in (400, 404):
                # Erreur client : inutile de réessayer à l'identique
                raise RuntimeError(f"HTTP {r.status_code} {url} : {r.text[:400]}")
            last = RuntimeError(f"HTTP {r.status_code} {url} : {r.text[:200]}")
            wait = backoff * (2**attempt)
            if r.status_code == 429:
                wait = max(wait, 65)
        except RuntimeError:
            raise
        except Exception as e:  # réseau
            last = e
            wait = backoff * (2**attempt)
        log.warning("Tentative %d/%d échouée (%s) — nouvel essai dans %.0f s", attempt + 1, retries, last, wait)
        time.sleep(wait)
    raise last  # type: ignore[misc]


def write_json(path: Path, obj, *, compact=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        if compact:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        else:
            json.dump(obj, f, ensure_ascii=False, indent=1, allow_nan=False)
    tmp.replace(path)


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def nan_to_none(a, digits=1):
    """Convertit un tableau numpy en liste JSON (NaN → null) arrondie."""
    out = []
    for v in np.asarray(a, dtype=float).ravel():
        out.append(None if not math.isfinite(v) else round(float(v), digits))
    return out


def piecewise(x, points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return np.interp(x, xs, ys)


def trapezoid(x, a, b, c, d):
    """Fonction trapèze : 0 sous a, 1 entre b et c, 0 au-delà de d (linéaire entre)."""
    x = np.asarray(x, dtype=float)
    up = np.clip((x - a) / max(b - a, 1e-9), 0, 1)
    down = np.clip((d - x) / max(d - c, 1e-9), 0, 1)
    return np.minimum(up, down)
