"""Tests techniques et scientifiques du moteur CèpeRadar.

Les séries météo ci-dessous sont SYNTHÉTIQUES et servent uniquement à vérifier le
comportement du modèle ; elles ne sont jamais publiées.
"""
import datetime as dt

import numpy as np
import pytest

from pipeline import engine, habitat
from pipeline.common import Grid, haversine_km, load_params
from pipeline.sources import classify_bdforet

P = load_params()


def make_series(n_days=120, rain=None, tmean=13.0, amp=8.0, et0=1.2):
    precip = np.zeros((1, n_days))
    for day, mm in (rain or {}).items():
        precip[0, day] = mm
    tm = np.full((1, n_days), float(tmean))
    s = {
        "precip": precip, "tmean": tm, "tmax": tm + amp / 2, "tmin": tm - amp / 2,
        "et0": np.full((1, n_days), et0), "tsoil": tm + 0.5,
    }
    s["bucket"] = engine.bucket_series(s["precip"], s["et0"], P["weather"]["bucket_max_mm"], P["weather"]["bucket_kc"])
    s["bucket_max"] = P["weather"]["bucket_max_mm"]
    return s


def W(series, t, doy, sp="edulis"):
    return float(engine.components_for_date(series, t, doy, P["species"][sp], P["weather"])["W"][0])


OCT15 = dt.date(2026, 10, 15).timetuple().tm_yday
JUL20 = dt.date(2026, 7, 20).timetuple().tm_yday
APR10 = dt.date(2026, 4, 10).timetuple().tm_yday


# ---------------------------------------------------------------------------- grille
def test_grid_radius_is_geodesic():
    g = Grid.from_params(P)
    m = g.in_circle_mask()
    d = g.distance_km()
    assert d[m].max() <= 100.0 + 1e-9
    assert d[~m].min() > 100.0
    # les coins du carré englobant sont exclus (≈ 141 km)
    assert not m[0, 0] and not m[-1, -1]
    # repères : Lacanau ≈ 45 km, Hourtin ≈ 55 km, Belin-Béliet ≈ 45 km du centre
    assert 40 < haversine_km(g.lat0, g.lon0, 45.000, -1.195) < 55
    assert 35 < haversine_km(g.lat0, g.lon0, 44.500, -0.789) < 50


def test_cell_size_about_1km():
    g = Grid.from_params(P)
    dy = haversine_km(g.lat0, g.lon0, g.lat0 + g.dlat, g.lon0)
    dx = haversine_km(g.lat0, g.lon0, g.lat0, g.lon0 + g.dlon)
    assert 0.95 < dy < 1.05 and 0.95 < dx < 1.05


# ---------------------------------------------------------------------------- météo
def test_long_drought_kills_score():
    s = make_series(rain={})  # aucune pluie pendant 120 j
    assert W(s, 110, OCT15) < 0.05


def test_rain_then_dry_spell_decreases_score():
    rain = {70: 20, 71: 25, 72: 15, 85: 10, 86: 12}
    s = make_series(rain=rain)
    favorable = W(s, 97, OCT15)  # ~12 j après la dernière pluie
    s_dry = make_series(rain={10: 20, 11: 25, 12: 15})  # même pluie mais il y a 3 mois
    assert favorable > 0.4
    assert W(s_dry, 97, OCT15) < 0.15
    assert favorable > 3 * W(s_dry, 97, OCT15)


def test_rain_yesterday_is_not_a_flush_tomorrow():
    """Une grosse pluie la veille n'implique pas une poussée immédiate."""
    base = {40: 8, 50: 6}  # peu de pluie avant
    yesterday = make_series(rain={**base, 99: 40})
    two_weeks = make_series(rain={**base, 86: 40})
    assert W(two_weeks, 100, OCT15) > W(yesterday, 100, OCT15) + 0.1


def test_temporal_response_rises_then_falls():
    s = make_series(rain={60: 30, 61: 20, 62: 15})
    curve = [W(s, 62 + lag, OCT15) for lag in range(1, 45)]
    peak = int(np.argmax(curve)) + 1
    assert 5 <= peak <= 25, peak
    assert curve[0] < curve[peak - 1] and curve[-1] < curve[peak - 1]


def test_seasonality():
    rain = {70: 20, 71: 25, 72: 15, 85: 12}
    s = make_series(rain=rain, tmean=13)
    assert W(s, 97, OCT15, "edulis") > 3 * W(s, 97, APR10, "edulis")


def test_species_respond_differently():
    rain = {70: 20, 71: 25, 72: 15, 85: 12}
    warm = make_series(rain=rain, tmean=20, et0=2.0)
    cool = make_series(rain=rain, tmean=12)
    mild = make_series(rain=rain, tmean=15.5)
    # été chaud et humide : cèpes d'été / bronzés > cèpe de Bordeaux / des pins
    assert W(warm, 97, JUL20, "aereus") > W(warm, 97, JUL20, "edulis")
    assert W(warm, 97, JUL20, "reticulatus") > W(warm, 97, JUL20, "pinophilus")
    # automne frais : l'inverse
    assert W(cool, 97, OCT15, "edulis") > W(cool, 97, OCT15, "aereus")
    vals = {sp: round(W(mild, 97, OCT15, sp), 3) for sp in engine.SPECIES_ORDER}
    assert len(set(vals.values())) == 4, vals


def test_frost_penalty():
    rain = {70: 20, 71: 25, 72: 15, 85: 12}
    s = make_series(rain=rain, tmean=8)
    ok = W(s, 97, OCT15)
    s["tmin"][0, 94:97] = -4
    assert W(s, 97, OCT15) < 0.5 * ok


def test_missing_data_is_not_invented():
    s = make_series(rain={70: 30})
    s["precip"][0, 80:90] = np.nan
    s["bucket"] = engine.bucket_series(s["precip"], s["et0"], 50, 0.8)
    c = engine.components_for_date(s, 95, OCT15, P["species"]["edulis"], P["weather"])
    assert not np.isfinite(c["W"][0])
    assert np.isnan(s["bucket"][0, 85])


def test_to_u8_marks_unknown():
    assert engine.to_u8(np.array([0.5, np.nan, 1.2])) == [50, 255, 100]


def test_forecast_confidence_decreases_with_lead():
    sp = P["species"]["edulis"]
    run = 100
    shares = [engine.forecast_share(sp, run + k, run) for k in range(0, 8)]
    confs = [engine.weather_confidence(sh, k) for k, sh in enumerate(shares)]
    assert all(a >= b for a, b in zip(confs, confs[1:]))
    assert engine.forecast_share(sp, run - 3, run) == 0.0
    assert confs[1] > 0.7 and confs[7] < confs[1]


# ---------------------------------------------------------------------------- habitat
def cells_with(**fracs):
    n = len(P["forest_classes"])
    keys = {c["key"]: c["id"] for c in P["forest_classes"]}
    rows = []
    for name, f in fracs.items():
        row = np.zeros(n)
        for k, v in f.items():
            row[keys[k]] = v
        rows.append(row)
    fr = np.array(rows)
    m = len(rows)
    return {
        "fractions": fr, "forest_frac": fr[:, 1:].sum(axis=1) - fr[:, [14, 15]].sum(axis=1),
        "edge": np.full(m, 0.05), "ph": np.full(m, 5.0), "slope": np.zeros(m), "north_share": np.zeros(m), "tpi": np.zeros(m),
    }, list(fracs)


def test_unsuitable_habitats_not_valued():
    st, names = cells_with(
        poplar={"peupleraie": 0.9}, mixed={"mixte_feuillus": 0.9}, oak={"chene_decidu": 0.9},
        pine={"pin_maritime": 0.9}, lande={"lande": 0.9}, scrap={"pin_maritime": 0.02},
    )
    H = habitat.habitat_scores(st, P)
    idx = {n: k for k, n in enumerate(names)}
    for sp in H:
        assert H[sp][idx["poplar"]] < 0.1
        assert H[sp][idx["scrap"]] == 0.0  # sous le seuil de couverture forestière
        assert H[sp][idx["lande"]] < 0.2
    assert H["edulis"][idx["mixed"]] > 0.8
    assert H["aereus"][idx["oak"]] > 3 * H["aereus"][idx["pine"]]
    assert H["pinophilus"][idx["pine"]] > H["pinophilus"][idx["oak"]]
    # une pinède pure n'obtient pas automatiquement le maximum
    assert H["edulis"][idx["pine"]] < H["edulis"][idx["mixed"]] - 0.2


def test_ph_out_of_range_reduces_but_unknown_is_neutral():
    st, _ = cells_with(a={"chene_decidu": 0.9}, b={"chene_decidu": 0.9}, c={"chene_decidu": 0.9})
    st["ph"] = np.array([5.0, 8.5, np.nan])
    H = habitat.habitat_scores(st, P)["edulis"]
    assert H[1] < H[0] and abs(H[2] - H[0]) < 1e-9


def test_combined_score_requires_both():
    """Météo parfaite + habitat incompatible ⇒ score faible ; et inversement."""
    good_h, bad_h, good_w, bad_w = 0.9, 0.1, 0.9, 0.1
    assert round(100 * good_h * bad_w) < 20
    assert round(100 * bad_h * good_w) < 20
    assert round(100 * good_h * good_w) >= 80


# ---------------------------------------------------------------------------- BD Forêt
@pytest.mark.parametrize("props,expected", [
    ({"tfv": "Forêt fermée de pin maritime pur", "essence": "Pin maritime"}, 1),
    ({"tfv": "Forêt fermée de chênes décidus purs", "essence": "Chênes décidus"}, 4),
    ({"tfv": "Forêt fermée de chênes sempervirents purs"}, 5),
    ({"tfv": "Forêt fermée de châtaignier pur"}, 7),
    ({"tfv": "Forêt fermée de hêtre pur"}, 6),
    ({"tfv": "Forêt fermée à mélange de feuillus prépondérants et conifères", "essence": "Mixte"}, 9),
    ({"tfv": "Forêt fermée à mélange de conifères prépondérants et feuillus", "essence": "Mixte"}, 10),
    ({"tfv": "Peupleraie", "essence": "Peuplier"}, 11),
    ({"tfv": "Lande ligneuse"}, 15),
    ({"tfv": "Forêt ouverte de conifères purs", "essence": "Conifères"}, 16),
    ({"tfv": "Forêt fermée sans couvert arboré", "code_tfv": "FF0"}, 14),
    ({"TFV": "Forêt fermée de pins mélangés", "ESSENCE": "Pins mélangés"}, 2),
    ({"tfv": "Formation herbacée"}, 0),
])
def test_bdforet_classification(props, expected):
    assert classify_bdforet(props) == expected


def test_rasterization_orientation_and_fractions():
    from shapely.geometry import box
    from pipeline import sources
    g = Grid.from_params(P)
    # carré de 2 × 2 mailles au nord-est du centre (mailles i=10..11, j=5..6)
    lat_c, lon_c = g.lat0 + 10.5 * g.dlat, g.lon0 + 5.5 * g.dlon
    poly = box(lon_c - g.dlon, lat_c - g.dlat, lon_c + g.dlon, lat_c + g.dlat)
    r = sources.rasterize_classes([(poly, 4)], g, 10)
    fr = sources.block_fractions(r, g, 10, len(P["forest_classes"]))
    n = g.n
    assert fr[n + 10, n + 5, 4] > 0.95 and fr[n + 11, n + 6, 4] > 0.95
    assert fr[n - 10, n + 5, 4] == 0  # pas d'inversion nord/sud
    assert abs(fr[:, :, 4].sum() - 4) < 0.1
    e = sources.edge_density(r, g, 10)
    assert e[n + 10, n + 5] > 0 and e[n, n] == 0


# ---------------------------------------------------------------------------- V1.1 humidité
def test_rew_bucket_keeps_residual_moisture_and_never_invents():
    mp = P["moisture"]
    n = 60
    precip = np.zeros((2, n)); precip[:, 5] = 30
    et0 = np.full((2, n), 2.0)
    r = engine.rew_bucket(precip, et0, np.array([22.0, 55.0]), mp, init=np.array([0.5, 0.5]))
    # décroissance asymptotique : jamais exactement zéro après 50 jours secs
    assert 0 < r[0, -1] < 0.1 and r[1, -1] > r[0, -1]
    precip[0, 30:35] = np.nan
    r2 = engine.rew_bucket(precip, et0, np.array([22.0, 55.0]), mp)
    assert np.isnan(r2[0, 32]) and np.isfinite(r2[0, 40])


def test_model_moisture_normalisation_and_hybrid():
    mp = P["moisture"]
    sm = np.array([[0.05, 0.15, 0.30, np.nan]])
    b = engine.rew_from_model([sm], [(0.05, 0.30)])
    assert np.allclose(b[0, :3], [0, 0.4, 1]) and np.isnan(b[0, 3])
    a = np.array([[0.1, 0.5, 0.9, 0.5]])
    c, dis = engine.moisture_hybrid(a, b, mp)
    assert abs(c[0, 1] - (0.6 * 0.5 + 0.4 * 0.4)) < 1e-9 and c[0, 3] == 0.5 and np.isnan(dis[0, 3])


def test_v11_moisture_does_not_zero_out_moderate_conditions():
    """Un sol à réserve modérée (REW 0,3) ne doit plus annuler le score, une vraie sécheresse oui."""
    s = make_series(rain={70: 20, 71: 25, 72: 15, 85: 12})
    s["moisture_params"] = P["moisture"]
    s["rew"] = np.full_like(s["precip"], 0.3)
    w_mod = W(s, 97, OCT15)
    s["rew"] = np.full_like(s["precip"], 0.02)
    w_dry = W(s, 97, OCT15)
    assert w_mod > 0.4 and w_dry < 0.05


def test_effective_classes():
    from pipeline import sources
    base = np.array([[14, 14, 1, 1, 0, 0, 4]], dtype=np.uint8)
    wc = np.array([[10, 30, 10, 10, 10, 40, 10]], dtype=np.uint8)
    ly = np.array([[0, 0, 23, 17, 0, 0, 0]], dtype=np.uint8)  # 2023 = coupe récente ; 2017 = jeune peuplement
    eff = sources.effective_classes(base, wc, ly, P["habitat"])
    assert eff.tolist() == [[17, 14, 14, 17, 18, 0, 4]]


@pytest.mark.parametrize("txt,key", [
    ("Sables éoliens des Landes (Formation du Sable des Landes)", "sable_landes"),
    ("Dunes littorales actuelles", "dune"),
    ("Calcaire à Astéries, Oligocène", "calcaire"),
    ("Alluvions fluviatiles récentes : argiles, vases", "argile_alluvions"),
    ("Graves et galets des hautes terrasses", "graves"),
    ("Tourbes et dépôts de marais", "tourbe"),
    ("Molasses de l'Agenais", "limon"),
])
def test_litho_classification(txt, key):
    from pipeline import sources
    assert sources.LITHO_KEYS[sources.classify_litho(txt)] == key
