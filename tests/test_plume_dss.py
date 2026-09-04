"""Plume transport and DSS workbook tests. Offline: no network, no keys."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from vayuchakra import dss, grid, plume


# ─── Emission and injection ──────────────────────────────────────────────────
def test_emission_factor_is_the_published_product():
    # GFAS dry matter 0.368 kg/MJ x 6.26 g PM2.5 per kg straw = 2.30 g/s per MW.
    assert plume.PM25_G_PER_S_PER_MW == pytest.approx(0.368 * 6.26, rel=1e-6)
    assert 2.0 < plume.PM25_G_PER_S_PER_MW < 2.6


def test_injection_height_grows_with_fire_power_but_stays_in_the_boundary_layer():
    h = plume.injection_height_m([1, 5, 20, 100])
    assert (np.diff(h) > 0).all()
    # Stubble fires are small: hundreds of metres, not the km a crown fire reaches.
    # Staying inside the boundary layer is exactly why they matter to Delhi.
    assert h[0] >= 100 and h[-1] < 1500


def test_sigma_grows_and_is_regional_at_long_range():
    near = plume.sigma_y_m([1.0], [10.0])[0]
    far = plume.sigma_y_m([15.0], [300.0])[0]
    assert far > near
    # Pasquill-Gifford alone would give a few hundred metres at 300 km, which is far
    # too narrow for a regional smoke plume.
    assert 10_000 < far < 80_000


# ─── Concentration ───────────────────────────────────────────────────────────
def _one_puff(mass_kg, sigma_km, depth_m, puff_h=400.0, lid=None, offset_km=0.0):
    cell = grid.Cell(0, 28.61, 77.21, "DEL", 0.0, "delhi")
    travel = sigma_km / plume.REGIONAL_SPREAD["D"]
    p = plume.PuffState(
        lat=np.array([28.61 + offset_km / 111.32]), lon=np.array([77.21]),
        mass_g=np.array([mass_kg * 1000.0]), height_m=np.array([puff_h]),
        age_h=np.array([0.1]), travel_km=np.array([travel]))
    wp = {"mixing_depth_m": np.array([depth_m]),
          "lid_m": np.array([lid if lid else np.nan])}
    wc = {"mixing_depth_m": np.array([depth_m])}
    return plume._contribution(p, [cell], wp, wc)[0]


def test_concentration_is_in_micrograms_not_grams():
    """Regression: the missing 1e6 made a real 0.66 ug/m3 print as 0.00."""
    c = _one_puff(1000, 20, 300)
    assert 0.1 < c < 10.0


def test_a_burn_night_reaches_episode_magnitudes():
    # 3,000 fires x 165 kg/h over 6 h under a 300 m layer.
    c = _one_puff(3000 * 165 * 6, 40, 300)
    assert 100 < c < 2000


def test_shallower_layer_concentrates_the_same_smoke():
    shallow = _one_puff(1000, 20, 300)
    deep = _one_puff(1000, 20, 1500)
    assert shallow > deep


def test_inversion_gate_decouples_smoke_above_the_lid():
    """The PS requirement: a plume above the lid must not reach the surface."""
    below = _one_puff(1000, 20, 300, puff_h=200, lid=400)
    at_lid = _one_puff(1000, 20, 300, puff_h=450, lid=400)
    above = _one_puff(1000, 20, 300, puff_h=700, lid=400)
    assert below > at_lid > above
    assert above == pytest.approx(0.0, abs=1e-9)


def test_concentration_falls_off_with_distance():
    near = _one_puff(1000, 20, 300, offset_km=0)
    mid = _one_puff(1000, 20, 300, offset_km=20)
    far = _one_puff(1000, 20, 300, offset_km=80)
    assert near > mid > far


def test_no_puffs_gives_no_contribution():
    cell = grid.Cell(0, 28.61, 77.21, "DEL", 0.0, "delhi")
    empty = plume.PuffState(*(np.array([], dtype="float64") for _ in range(6)))
    out = plume._contribution(empty, [cell],
                              {"mixing_depth_m": np.array([]), "lid_m": np.array([])},
                              {"mixing_depth_m": np.array([300.0])})
    assert out[0] == 0.0


# ─── Advection and removal ───────────────────────────────────────────────────
def test_advection_moves_with_the_wind():
    p = plume.PuffState(np.array([30.0]), np.array([75.0]), np.array([1e6]),
                        np.array([400.0]), np.array([0.0]), np.array([0.0]))
    east = plume._step(p, {"u": np.array([5.0]), "v": np.array([0.0]),
                           "precip": np.array([0.0])})
    assert east.lon[0] > 75.0
    assert east.lat[0] == pytest.approx(30.0, abs=1e-6)
    assert east.travel_km[0] > 10


def test_rain_scavenges_mass():
    p = plume.PuffState(np.array([30.0]), np.array([75.0]), np.array([1e6]),
                        np.array([400.0]), np.array([0.0]), np.array([0.0]))
    dry = plume._step(p, {"u": np.array([0.0]), "v": np.array([0.0]),
                          "precip": np.array([0.0])})
    wet = plume._step(p, {"u": np.array([0.0]), "v": np.array([0.0]),
                          "precip": np.array([10.0])})
    assert wet.mass_g[0] < dry.mass_g[0] < 1e6      # decay applies even when dry


def test_spent_puffs_are_dropped():
    p = plume.PuffState(np.array([30.0, 30.0]), np.array([75.0, 75.0]),
                        np.array([1e6, 1.0]), np.array([400.0, 400.0]),
                        np.array([0.0, 0.0]), np.array([0.0, 0.0]))
    assert len(p.compress()) == 1


def test_confidence_parsing_across_both_satellite_conventions():
    assert plume._parse_confidence("h") == "high"        # VIIRS
    assert plume._parse_confidence("90") == "high"       # MODIS 0-100
    assert plume._parse_confidence("10") == "low"
    assert plume._parse_confidence("") == "nominal"


def test_run_with_no_fires_returns_empty():
    cells = [grid.Cell(0, 28.61, 77.21, "DEL", 0.0, "delhi")]
    assert plume.run([], pd.DataFrame(), cells).empty


def test_summarise_is_honest_when_nothing_is_burning():
    s = plume.summarise([])
    assert s["available"] is True and s["n_fires"] == 0


# ─── DSS workbook ────────────────────────────────────────────────────────────
requires_dss = pytest.mark.skipif(not dss.available(), reason="DSS workbook not present")


@requires_dss
def test_forecast_archive_covers_the_2021_season():
    f = dss.forecast_archive()
    assert len(f) > 3000
    assert f["time"].min().year == 2021 and f["time"].max().year == 2022
    assert f["dss_day1"].notna().sum() > 3000


@requires_dss
def test_valid_time_reshape_adds_the_lead():
    """Getting this backwards would shift every DSS number by one to five days."""
    v = dss.forecast_as_valid_time()
    assert set(v["lead_hours"].unique()) <= {24, 48, 72, 96, 120}
    row = v.iloc[0]
    assert (row["valid_time"] - row["issue_time"]) == pd.Timedelta(hours=row["lead_hours"])


@requires_dss
def test_apportionment_shares_sum_to_one():
    ap = dss.apportionment()
    shares = ap.mean_shares()
    assert abs(sum(shares.values()) - 1.0) < 0.02
    assert "stubble_burning" in shares


@requires_dss
def test_scenario_levels_are_read_the_right_way_round():
    """`_80` is emissions AT 80% - a 20% CUT. Reading it backwards inverts policy."""
    assert dss.SCENARIO_LEVELS["80"] == 0.20
    assert dss.SCENARIO_LEVELS["60"] == 0.40
    s = dss.scenario_summary()
    tra = s[(s["target"] == "TRA") & (s["target_kind"] == "delhi_sector")]
    if len(tra) == 2:
        deeper = tra[tra["reduction"] == 0.4]["mean_ugm3"].iloc[0]
        shallower = tra[tra["reduction"] == 0.2]["mean_ugm3"].iloc[0]
        assert deeper > shallower       # a bigger cut must remove more
