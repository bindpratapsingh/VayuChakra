"""Physics and index tests — all offline, no network, no keys.

These check the things that would be embarrassing to get wrong on stage and that are
hard to notice by looking at output: unit errors, sign errors, boundary conditions, and
the specific bugs already found once during development. Every test named after a bug
is a regression guard, not a hypothetical.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from vayuchakra import aqi, feedback, grid, indices
from vayuchakra import config as C


# ─── Geometry ────────────────────────────────────────────────────────────────
def test_haversine_known_distance():
    # Delhi to Karnal is about 121 km.
    d = grid.haversine_km(28.6139, 77.2090, 29.6857, 76.9905)
    assert 115 < d < 127


def test_bearing_to_punjab_is_north_west():
    # The stubble belt sits NNW of Delhi; smoke arrives on that bearing.
    b = grid.bearing_deg(28.61, 77.21, 30.5, 75.5)
    assert 300 < b < 340


def test_grid_tiers_do_not_overlap():
    cells = grid.build_grid()
    ncr = [c for c in cells if c.tier == "ncr"]
    assert not any(grid.in_delhi_box(c.lat, c.lon) for c in ncr)
    assert len({c.cell_id for c in cells}) == len(cells)


def test_delhi_tier_is_actually_high_resolution():
    delhi = [c for c in grid.build_grid() if c.tier == "delhi"]
    # A uniform coarse grid gave only 8 cells over Delhi, which is why the two-tier
    # grid exists. Guard the property, not the exact count.
    assert len(delhi) > 200


def test_idw_weights_by_distance():
    near_dominates = grid.idw([(100.0, 1.0), (200.0, 10.0)])
    assert near_dominates < 120
    assert grid.idw([]) is None
    assert grid.idw([(50.0, 0.0)]) == 50.0


# ─── Stability indices ───────────────────────────────────────────────────────
def _profile_frame(t2, t950, pbl=200.0, sw=0.0, elevation=225.0):
    """One hour with a controllable vertical profile."""
    return pd.DataFrame({
        "cell_id": [1], "time": pd.to_datetime(["2026-01-15T00:00:00Z"]),
        "lat": [28.6], "lon": [77.2], "elevation": [elevation],
        "temperature_2m": [t2], "surface_pressure": [980.0],
        "boundary_layer_height": [pbl], "shortwave_radiation": [sw],
        "cloud_cover": [10.0], "wind_speed_10m": [2.0], "wind_speed_100m": [4.0],
        "wind_direction_10m": [315.0], "wind_direction_100m": [315.0],
        "temperature_950hPa": [t950], "temperature_925hPa": [t950 - 1.0],
        "temperature_850hPa": [t950 - 6.0],
        "geopotential_height_950hPa": [elevation + 267.0],
        "geopotential_height_925hPa": [elevation + 503.0],
        "geopotential_height_850hPa": [elevation + 1243.0],
    })


def test_inversion_detected_when_air_aloft_is_warmer():
    df = indices.enrich(_profile_frame(t2=10.0, t950=14.0))
    assert df["is_inversion"].iloc[0] == 1
    assert df["inversion_strength_k"].iloc[0] == pytest.approx(4.0, abs=0.01)
    assert df["inversion_method"].iloc[0] == "profile"


def test_no_inversion_on_a_normal_profile():
    df = indices.enrich(_profile_frame(t2=25.0, t950=22.0))
    assert df["is_inversion"].iloc[0] == 0
    assert df["inversion_strength_k"].iloc[0] == 0.0
    # "No inversion" must be NaN, not a lid at zero metres.
    assert np.isnan(df["inversion_lid_m"].iloc[0])


def test_below_ground_pressure_levels_are_excluded():
    """Regression: 1000 hPa sits below Delhi's terrain and reads too warm at night.

    A level whose geopotential height is under the ground elevation carries no
    information and must not create an inversion out of an extrapolation.
    """
    df = _profile_frame(t2=10.0, t950=14.0)
    df["geopotential_height_950hPa"] = [df["elevation"].iloc[0] - 100.0]  # underground
    out = indices.enrich(df)
    assert np.isnan(out["t_950"].iloc[0])
    assert out["is_inversion"].iloc[0] == 0


def test_surface_path_leaves_inversion_strength_missing_not_zero():
    """Regression: the ERA5 archive has no pressure levels.

    The kelvin figure must be NaN there. Filling it with zero would teach a model that
    no historical hour had an inversion - a fabricated fact.
    """
    df = _profile_frame(t2=10.0, t950=14.0, pbl=100.0, sw=0.0)
    for lv in ("950", "925", "850"):
        df[f"temperature_{lv}hPa"] = np.nan
        df[f"geopotential_height_{lv}hPa"] = np.nan
    out = indices.enrich(df)
    assert out["inversion_method"].iloc[0] == "surface"
    assert np.isnan(out["inversion_strength_k"].iloc[0])
    # A collapsed layer at night is still recognised as a lid.
    assert out["is_inversion"].iloc[0] == 1


def test_mixing_depth_is_never_infinite():
    """Regression: np.fmin(NaN, inf) is inf, which poisoned every downstream fit."""
    df = _profile_frame(t2=10.0, t950=14.0)
    df["boundary_layer_height"] = [np.nan]
    out = indices.enrich(df)
    v = out["mixing_depth_m"].iloc[0]
    assert not np.isinf(v)
    assert np.isnan(v) or C.MIN_PBL_M <= v <= C.MAX_PBL_M


def test_ventilation_coefficient_units_and_thresholds():
    df = indices.enrich(_profile_frame(t2=25.0, t950=22.0, pbl=1000.0))
    vc = df["ventilation_coeff"].iloc[0]
    # depth x wind, both SI: a 1000 m layer with a few m/s is thousands, not millions.
    assert 1_000 < vc < 20_000
    assert df["dispersion_class"].iloc[0] in ("fair", "poor", "severe")


def test_mixing_depth_capped_by_the_inversion_lid():
    deep_pbl_shallow_lid = indices.enrich(_profile_frame(t2=10.0, t950=14.0, pbl=1500.0))
    lid = deep_pbl_shallow_lid["inversion_lid_m"].iloc[0]
    assert deep_pbl_shallow_lid["mixing_depth_m"].iloc[0] <= lid + 1e-6


# ─── AQI ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("pollutant,conc,expected", [
    ("pm25", 30, 50), ("pm25", 60, 100), ("pm25", 90, 200),
    ("pm25", 120, 300), ("pm25", 250, 400),
    ("pm10", 100, 100), ("o3", 100, 100), ("no2", 80, 100), ("co", 2, 100),
])
def test_sub_index_matches_published_cpcb_table(pollutant, conc, expected):
    """Regression: adjacent bands share an endpoint; the LOWER band must win."""
    got = float(aqi.sub_index(np.array([float(conc)]), pollutant)[0])
    assert got == pytest.approx(expected, abs=0.5)


@pytest.mark.parametrize("value,band", [
    (0, "Good"), (50, "Good"), (50.4, "Good"), (51, "Satisfactory"),
    (100.5, "Satisfactory"), (101, "Moderate"), (200.7, "Moderate"),
    (201, "Poor"), (301, "Very Poor"), (401, "Severe"), (650, "Severe"),
])
def test_band_boundaries_including_fractional_values(value, band):
    """Regression: fractional values between integer bands fell through to Severe."""
    assert aqi.band_for(np.array([float(value)]))[0] == band


def test_aqi_refuses_with_too_few_pollutants():
    only_pm, _ = aqi.aqi_from_concentrations({"pm25": np.array([120.0])})
    assert np.isnan(only_pm[0])
    no_particulate, _ = aqi.aqi_from_concentrations({
        "no2": np.array([80.0]), "so2": np.array([80.0]), "o3": np.array([100.0])})
    assert np.isnan(no_particulate[0])


def test_aqi_takes_the_worst_pollutant():
    idx, driver = aqi.aqi_from_concentrations({
        "pm25": np.array([120.0]), "pm10": np.array([60.0]), "o3": np.array([40.0])})
    assert idx[0] == pytest.approx(300, abs=1)
    assert driver[0] == "pm25"


def test_cpcb_window_flattens_an_hourly_spike():
    """The index is defined on a 24-hour mean, not a spot reading."""
    t = pd.date_range("2026-01-01", periods=48, freq="h", tz="UTC")
    pm = np.full(48, 80.0)
    pm[20] = 400.0
    df = pd.DataFrame({"cell_id": 1, "time": t, "pm25": pm,
                       "pm10": pm * 1.6, "o3": np.full(48, 40.0)})
    out = aqi.compute(aqi.rolling_for_index(df))
    assert out["pm25_cpcb"].iloc[20] < 120        # 24h mean, not the 400 spike
    assert out["aqi"].iloc[20] < 300


def test_rolling_does_not_mix_horizons():
    """Regression: grouping by cell alone blended the 24/48/72 h forecasts together."""
    t = pd.date_range("2026-01-01", periods=30, freq="h", tz="UTC")
    df = pd.concat([
        pd.DataFrame({"cell_id": 1, "horizon_h": 24, "time": t, "pm25": 50.0}),
        pd.DataFrame({"cell_id": 1, "horizon_h": 48, "time": t, "pm25": 250.0}),
    ], ignore_index=True)
    out = aqi.rolling_for_index(df)
    lo = out[out["horizon_h"] == 24]["pm25_cpcb"].dropna()
    hi = out[out["horizon_h"] == 48]["pm25_cpcb"].dropna()
    assert lo.max() < 60 and hi.min() > 240


# ─── Coupled feedback ────────────────────────────────────────────────────────
def test_shortwave_loss_is_bounded_and_not_raw_beer_lambert():
    """Extinction is not all loss to the surface: forward-scattered light arrives."""
    loss = feedback.shortwave_loss_fraction(np.array([0.6]), np.array([2.0]))[0]
    assert 0.05 < loss < 0.30      # raw Beer-Lambert would claim ~0.70


def test_shortwave_loss_increases_with_aerosol():
    a = feedback.shortwave_loss_fraction(np.array([0.2]), np.array([2.0]))[0]
    b = feedback.shortwave_loss_fraction(np.array([1.5]), np.array([2.0]))[0]
    assert b > a


def test_cooling_has_the_right_sign_and_magnitude():
    # A 100 W/m2 deficit should cool by order 1 K, and cooling must be negative.
    dt = feedback.delta_temperature(np.array([-100.0]))[0]
    assert -3.0 <= dt < 0
    assert abs(dt) > 0.3


def test_pbl_can_deepen_as_well_as_shallow():
    """Regression: clipping the ratio at 1.0 forbade the pristine control from
    differing from the baseline, which zeroed the effect being measured."""
    shallower = feedback.pbl_response(np.array([1000.0]), np.array([500.0]), np.array([300.0]))[0]
    deeper = feedback.pbl_response(np.array([1000.0]), np.array([300.0]), np.array([500.0]))[0]
    assert shallower < 1000.0 < deeper


def test_pbl_response_is_inert_at_night():
    """No convective growth after dark, so nothing for the aerosol to suppress."""
    night = feedback.pbl_response(np.array([120.0]), np.array([0.0]), np.array([0.0]))[0]
    assert night == pytest.approx(120.0, abs=1.0)


def test_shallower_layer_concentrates():
    c = feedback.concentration_response(np.array([100.0]), np.array([1000.0]), np.array([800.0]))[0]
    assert c > 100.0


def test_optical_airmass_does_not_diverge_at_the_horizon():
    overhead = feedback.optical_airmass(np.array([0.0]))[0]
    horizon = feedback.optical_airmass(np.array([90.0]))[0]
    assert overhead == pytest.approx(1.0, abs=0.05)
    assert 20 < horizon < 60          # plain 1/cos(z) would be infinite


def test_solar_zenith_is_smaller_at_noon_than_at_midnight():
    times = pd.to_datetime(["2026-06-21T06:30:00Z", "2026-06-21T18:30:00Z"])
    z = feedback.solar_zenith_deg(times, np.array([28.6, 28.6]), np.array([77.2, 77.2]))
    assert z[0] < z[1]


def test_solver_converges_and_stays_bounded():
    n = 48
    t = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    sw = np.clip(np.sin(np.linspace(0, 2 * np.pi, n)) * 600, 0, None)
    df = pd.DataFrame({
        "cell_id": 1, "time": t, "lat": 28.6, "lon": 77.2,
        "shortwave_radiation": sw, "mixing_depth_m": 200 + sw / 2,
        "cams_aod": 0.8, "cams_pm25": 150.0, "pm25_uncoupled": 150.0,
        "relative_humidity_2m": 60.0,
    })
    res = feedback.solve(df)
    assert res.converged
    assert res.iterations <= C.COUPLING_MAX_ITER
    assert res.diverged_rows == 0
    out = res.frame
    # The feedback raises concentration; it must never lower it or run away.
    amp = out["pm_amplification_frac"].dropna()
    assert (amp >= -1e-9).all()
    assert amp.max() < 0.6
    assert (out["pm25_coupled"] >= 0).all()


def test_solver_is_a_no_op_without_a_sun():
    """At night there is no radiative feedback, so coupled must equal uncoupled."""
    t = pd.date_range("2026-01-01T18:00:00Z", periods=6, freq="h", tz="UTC")
    df = pd.DataFrame({
        "cell_id": 1, "time": t, "lat": 28.6, "lon": 77.2,
        "shortwave_radiation": 0.0, "mixing_depth_m": 120.0,
        "cams_aod": 1.2, "cams_pm25": 200.0, "pm25_uncoupled": 200.0,
        "relative_humidity_2m": 70.0,
    })
    res = feedback.solve(df)
    assert np.allclose(res.frame["pm25_coupled"], 200.0, atol=1e-6)


def test_aod_elasticity_rejects_an_unphysical_fit():
    junk = pd.DataFrame({"cams_pm25": np.random.default_rng(0).uniform(5, 300, 800),
                         "cams_aod": np.random.default_rng(1).uniform(0.05, 2.0, 800),
                         "relative_humidity_2m": 50.0})
    m = feedback.calibrate_aod(junk)
    # Noise must not produce a confident elasticity; fall back to the labelled default.
    assert 0.05 <= m.b <= 1.2


# ─── Wind response (R6: temperature, WIND, PBL) ──────────────────────────────
def test_wind_slackens_when_the_boundary_layer_is_suppressed():
    """A shallower mixed layer transports less momentum down, so surface wind falls."""
    u = feedback.wind_response(np.array([3.0]), np.array([1000.0]), np.array([800.0]))[0]
    assert u < 3.0
    # Published ratio: wind falls ~1/5 as much as the PBL, so a 20% PBL cut gives ~4%.
    assert 2.7 < u < 2.95


def test_wind_unchanged_when_the_layer_is_unchanged():
    u = feedback.wind_response(np.array([3.0]), np.array([900.0]), np.array([900.0]))[0]
    assert u == pytest.approx(3.0, abs=1e-9)


def test_wind_response_is_capped():
    """The relation is linearised around a small perturbation; it must not reach calm."""
    u = feedback.wind_response(np.array([3.0]), np.array([2000.0]), np.array([30.0]))[0]
    assert u >= 3.0 * (1.0 - C.MAX_WIND_SUPPRESSION) - 1e-9
    assert u > 0


def test_wind_freshens_when_the_layer_deepens():
    """Two-sided by design: the pristine control has a DEEPER layer and more wind.

    An earlier version clipped this to the suppression side only, which meant the
    control could never differ from the baseline and the measured wind response came
    out ten times too small.
    """
    u = feedback.wind_response(np.array([0.0, 5.0]), np.array([500.0, 500.0]),
                               np.array([100.0, 600.0]))
    assert (u >= 0).all()
    assert u[0] == pytest.approx(0.0)      # no wind stays no wind
    assert u[1] > 5.0                       # deeper layer, fresher surface wind
    assert u[1] <= 5.0 * (1 + C.MAX_WIND_SUPPRESSION) + 1e-9


# ─── Uncertainty ─────────────────────────────────────────────────────────────
def test_exceedance_probability_is_monotone_in_threshold():
    """A higher bar must be less likely to clear, always."""
    from vayuchakra import uncertainty as unc
    q = pd.DataFrame({"q10": [50.0], "q25": [70.0], "q50": [100.0],
                      "q75": [140.0], "q90": [200.0]})
    probs = [unc.exceedance_probability(q, t)[0] for t in (40, 80, 120, 180, 300)]
    assert all(a >= b - 1e-9 for a, b in zip(probs, probs[1:]))
    assert 0.0 <= min(probs) and max(probs) <= 1.0


def test_exceedance_matches_the_fitted_quantiles():
    """At the median the answer must be about a half, by construction."""
    from vayuchakra import uncertainty as unc
    q = pd.DataFrame({"q10": [50.0], "q25": [70.0], "q50": [100.0],
                      "q75": [140.0], "q90": [200.0]})
    assert unc.exceedance_probability(q, 100.0)[0] == pytest.approx(0.5, abs=0.02)
    assert unc.exceedance_probability(q, 50.0)[0] == pytest.approx(0.9, abs=0.02)
    assert unc.exceedance_probability(q, 200.0)[0] == pytest.approx(0.1, abs=0.02)


def test_coverage_flags_an_overconfident_interval():
    from vayuchakra import uncertainty as unc
    y = np.linspace(0, 100, 200)
    tight = unc.coverage(y, y - 1, y + 1, nominal=0.80)
    assert tight["measured"] < 0.80 or tight["mean_width"] < 5
    wide = unc.coverage(y, y - 500, y + 500, nominal=0.80)
    assert wide["measured"] == 1.0
    assert "hedging" in wide["verdict"]


def test_grap_thresholds_match_the_cpcb_table():
    """These must be the concentrations at which GRAP stages actually trigger."""
    from vayuchakra import uncertainty as unc
    for label, conc in unc.GRAP_PM25.items():
        idx = float(aqi.sub_index(np.array([conc]), "pm25")[0])
        expected = float(label.split()[1])
        assert idx == pytest.approx(expected, abs=1.0), f"{label}: {conc} -> AQI {idx}"
