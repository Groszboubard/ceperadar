"""Favorabilité de l'habitat (composante permanente) par espèce et par cellule de 1 km.

H = qualité du peuplement (affinités hôte pondérées par les surfaces)
    × couverture forestière × (1 + bonus lisières + bonus mosaïque) × sol × topographie
Tous les facteurs sont bornés pour qu'aucun ne domine ; voir docs/MODELE.md.
"""
from __future__ import annotations

import numpy as np

HOST_CLASSES = list(range(1, 17))


def host_quality(fractions: np.ndarray, affinity: list[float]) -> np.ndarray:
    """fractions : (n_cells, n_classes) parts de surface de la cellule ; renvoie 0-1."""
    aff = np.asarray(affinity, dtype=float)
    cols = list(range(1, fractions.shape[1]))
    forest = fractions[:, cols].sum(axis=1)
    weighted = (fractions[:, cols] * aff[cols]).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        q = np.where(forest > 0, weighted / forest, 0.0)
    return q


def coverage_factor(forest_frac: np.ndarray, hp: dict) -> np.ndarray:
    return hp["coverage_floor"] + (1 - hp["coverage_floor"]) * np.clip(forest_frac / hp["coverage_full"], 0, 1)


def mix_index(fractions: np.ndarray) -> np.ndarray:
    """Indice de diversité de Simpson des essences hôtes (0 = pur, ~0,8 = très mélangé).

    Regroupe feuillus hôtes et conifères ; une mosaïque pin × chêne est typiquement
    favorable aux cèpes dans le massif landais (lisières de chênes en bordure de pinède).
    """
    groups = np.stack([
        fractions[:, [1, 2, 3, 16]].sum(axis=1),          # conifères
        fractions[:, [4, 5]].sum(axis=1),                  # chênes
        fractions[:, [6, 7]].sum(axis=1),                  # hêtre / châtaignier
        fractions[:, [8, 12, 13]].sum(axis=1),             # autres feuillus
        fractions[:, [9, 10]].sum(axis=1),                 # mixtes déjà mélangés
    ], axis=1)
    tot = groups.sum(axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        p = np.where(tot > 0, groups / tot, 0)
    simpson = 1 - (p**2).sum(axis=1)
    # les classes « mixtes » sont par nature mélangées
    mixed_share = np.where(tot[:, 0] > 0, groups[:, 4] / np.maximum(tot[:, 0], 1e-9), 0)
    return np.clip(np.maximum(simpson, 0.6 * mixed_share), 0, 1)


def ph_factor(ph: np.ndarray, rng: list[float], hp: dict) -> np.ndarray:
    """1 dans la plage favorable, décroît jusqu'à `ph_outside_factor` à ±tolérance ; 1 si inconnu."""
    lo, hi = rng
    tol = hp["ph_tolerance"]
    dist = np.where(ph < lo, lo - ph, np.where(ph > hi, ph - hi, 0.0))
    f = 1 - (1 - hp["ph_outside_factor"]) * np.clip(dist / tol, 0, 1)
    return np.where(np.isfinite(ph), f, 1.0)


def topo_factor(slope_deg: np.ndarray, north_share: np.ndarray, tpi_m: np.ndarray, species: str, hp: dict) -> np.ndarray:
    """Effet volontairement faible (±4 % max) : relief modeste autour de Bordeaux.

    - espèces estivales (aereus, reticulatus) : versants nord et fonds légèrement plus frais/humides → léger +
    - toutes : position basse (TPI < 0) = humidité accumulée → léger + ; crêtes sableuses → léger −
    Inactif sur terrain plat (pente < 2°) pour l'orientation.
    """
    m = hp["topo_max_effect"]
    eff = np.zeros_like(slope_deg, dtype=float)
    sloped = np.clip((np.nan_to_num(slope_deg) - 2.0) / 4.0, 0, 1)
    if species in ("aereus", "reticulatus"):
        eff += m * 0.5 * sloped * (np.nan_to_num(north_share) - 0.5) * 2
    eff += m * 0.5 * np.clip(-np.nan_to_num(tpi_m) / 10.0, -1, 1)
    return 1 + np.clip(eff, -m, m)


def habitat_scores(static: dict, params: dict) -> dict[str, np.ndarray]:
    hp = params["habitat"]
    fr = static["fractions"]
    forest = static["forest_frac"]
    edge = static["edge"]
    mix = mix_index(fr)
    cov = coverage_factor(forest, hp)
    struct = 1 + hp["edge_bonus"] * np.clip(edge / hp["edge_full"], 0, 1) + hp["mix_bonus"] * mix
    out = {}
    for s, sp in params["species"].items():
        q = host_quality(fr, sp["affinity"])
        h = q * cov * struct
        h *= ph_factor(static["ph"], sp["ph"], hp)
        h *= topo_factor(static["slope"], static["north_share"], static["tpi"], s, hp)
        if "hydro" in static and "hydro_penalty" in hp:
            # sols engorgés (tourbes, alluvions) : asphyxie du mycélium (V1.1)
            h *= 1 - hp["hydro_penalty"] * np.clip(np.nan_to_num(static["hydro"]), 0, 1)
        h = np.where(forest >= params["region"]["min_forest_fraction"], h, 0.0)
        out[s] = np.clip(h, 0, 1)
    return out
