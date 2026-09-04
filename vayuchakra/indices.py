"""Derived stability indices — the quantities the problem statement asks us to track.

Three things are computed here, and each answers a specific line of the PS.

**Inversion strength** ("Features that explicitly track atmospheric inversion
strength"). A temperature inversion is air that gets *warmer* with height. It puts a
lid on the city: emissions released under it cannot escape upward, so concentration
climbs even when emissions are flat. Delhi's worst winter episodes are inversion
episodes.

**Mixing depth and ventilation coefficient** ("meteorology (temperature, wind, PBL
height)"). Ventilation coefficient is mixing depth times the wind speed through that
depth — the volume flux available to carry pollution away per unit time. It is the
standard operational dispersion metric and the single most legible number we produce.

**Stability class**, which the plume model needs in order to decide how fast a stubble
plume spreads as it travels.

Every function is vectorised over a DataFrame: the grid is ~1,100 cells by ~96 hours,
and a per-row Python loop would cost minutes on every run.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C

#: Pressure levels we may use, with their nominal pressure in hPa. 1000 hPa is absent
#: deliberately: over Delhi (ground ~225 m ASL) that surface sits ~180 m BELOW the
#: terrain, so Open-Meteo reports a downward extrapolation that reads several degrees
#: too warm at night — which would manufacture inversions that do not exist.
LEVELS: tuple[tuple[str, float], ...] = (("950", 950.0), ("925", 925.0), ("850", 850.0))

P0 = 1000.0         # hPa, reference pressure for potential temperature
KAPPA = 0.2857      # R_dry / cp
URBAN_ALPHA = 0.25  # fallback wind-profile exponent when the 100 m wind is unusable


def potential_temperature(t_celsius, pressure_hpa):
    """Theta — the temperature a parcel would have if brought adiabatically to 1000 hPa.

    Comparing raw temperature across heights conflates real stability with the
    adiabatic cooling any rising parcel undergoes. Theta removes that, so a positive
    d(theta)/dz is genuine static stability rather than an artefact of altitude.
    """
    t = np.asarray(t_celsius, dtype=float) + 273.15
    p = np.asarray(pressure_hpa, dtype=float)
    return t * (P0 / p) ** KAPPA


def add_profile(df: pd.DataFrame) -> pd.DataFrame:
    """Attach height-above-ground and potential temperature for each usable level."""
    out = df.copy()
    elev = pd.to_numeric(out.get("elevation"), errors="coerce").fillna(0.0)
    sp = pd.to_numeric(out.get("surface_pressure"), errors="coerce")

    out["theta_sfc"] = potential_temperature(out["temperature_2m"], sp.fillna(P0))
    for name, p_hpa in LEVELS:
        gh = pd.to_numeric(out.get(f"geopotential_height_{name}hPa"), errors="coerce")
        t = pd.to_numeric(out.get(f"temperature_{name}hPa"), errors="coerce")
        agl = gh - elev
        usable = agl > 10.0  # a level within 10 m of the ground carries no information
        out[f"z_{name}"] = agl.where(usable)
        out[f"t_{name}"] = t.where(usable)
        out[f"theta_{name}"] = pd.Series(
            potential_temperature(t, p_hpa), index=out.index
        ).where(usable)
    return out


#: A shallow nocturnal boundary layer is the surface signature of a radiative
#: inversion. Used only on the archive path, where pressure levels do not exist.
SURFACE_INVERSION_PBL_M = 250.0
SURFACE_NIGHT_SW = 20.0     # W m-2; below this the sun is not driving mixing


def has_profile(df: pd.DataFrame) -> bool:
    """True when pressure-level temperatures are actually populated.

    Measured 2026-09-04: the Open-Meteo **forecast** API serves pressure levels, but
    the **ERA5 archive** never does - `temperature_925hPa` came back 0/24 non-null on
    every archive date tested, while `boundary_layer_height` came back 24/24. So the
    hindcast path has a boundary layer height but no vertical temperature profile, and
    the inversion diagnosis has to be derived differently there.
    """
    col = df.get("temperature_950hPa")
    if col is None:
        return False
    return bool(pd.to_numeric(col, errors="coerce").notna().mean() > 0.5)


def inversion_from_surface(df: pd.DataFrame) -> pd.DataFrame:
    """Inversion diagnosis without a vertical profile — the hindcast path.

    We cannot measure a temperature excess in kelvin without temperatures aloft, so
    ``inversion_strength_k`` is left NaN rather than filled with a fabricated number.
    What we can say is *whether* a lid is present: a boundary layer that has collapsed
    below ~250 m while the sun is down is the surface signature of a radiative
    inversion, and the boundary layer height itself is then the lid.

    Leaving the kelvin figure missing is deliberate. A model trained where that feature
    is absent simply must not use it, and NaN enforces that; a zero would quietly teach
    it that every hindcast hour had no inversion.
    """
    out = df.copy()
    pbl = pd.to_numeric(out["boundary_layer_height"], errors="coerce")
    sw = pd.to_numeric(out.get("shortwave_radiation"), errors="coerce").fillna(0.0)

    out["inversion_strength_k"] = np.nan
    out["lapse_k_per_100m"] = np.nan
    out["theta_grad_k_per_100m"] = np.nan
    out["theta_sfc"] = potential_temperature(
        out["temperature_2m"], pd.to_numeric(out.get("surface_pressure"), errors="coerce").fillna(P0))

    is_inv = (pbl < SURFACE_INVERSION_PBL_M) & (sw < SURFACE_NIGHT_SW)
    out["is_inversion"] = is_inv.fillna(False).astype("int8")
    out["inversion_lid_m"] = pbl.where(is_inv)
    out["inversion_method"] = "surface"
    for name, _ in LEVELS:
        for pre in ("z", "t", "theta"):
            out[f"{pre}_{name}"] = np.nan
    return out


def inversion(df: pd.DataFrame) -> pd.DataFrame:
    """Inversion strength, lid height and the surface stability gradient.

    Dispatches on what the data actually contains: the full profile calculation where
    pressure levels exist (the forecast path), the surface proxy where they do not
    (the ERA5 hindcast path). ``inversion_method`` records which was used on every row
    so no downstream consumer can confuse the two.

    ``inversion_strength_k`` is the temperature EXCESS of the lowest usable level over
    the 2 m reading, in kelvin, floored at zero. Positive means a lid.

    ``inversion_lid_m`` is the height at which the inversion ends: we walk upward and
    stop at the first level where temperature resumes falling. With no inversion it is
    NaN rather than zero, because "no lid" and "a lid at ground level" are opposite
    conditions and must never average together.
    """
    if not has_profile(df):
        return inversion_from_surface(df)

    out = add_profile(df)
    out["inversion_method"] = "profile"
    t2 = pd.to_numeric(out["temperature_2m"], errors="coerce")
    z_low, t_low, th_low = out["z_950"], out["t_950"], out["theta_950"]

    out["inversion_strength_k"] = (t_low - t2).clip(lower=0.0)
    out["is_inversion"] = (out["inversion_strength_k"] > 0.1).fillna(False).astype("int8")

    # Bulk lapse rate, K per 100 m. Negative means temperature rising with height.
    dz = z_low - 2.0
    out["lapse_k_per_100m"] = np.where(dz > 0, (t2 - t_low) / dz * 100.0, np.nan)

    # Static stability from potential temperature, K per 100 m. Positive = stable.
    out["theta_grad_k_per_100m"] = np.where(
        dz > 0, (th_low - out["theta_sfc"]) / dz * 100.0, np.nan)

    # Lid height: the first level at which temperature stops increasing.
    lid = pd.Series(np.nan, index=out.index, dtype="float64")
    prev_t = t2
    prev_z = pd.Series(2.0, index=out.index, dtype="float64")
    rising = pd.Series(True, index=out.index)
    for name, _ in LEVELS:
        t_l, z_l = out[f"t_{name}"], out[f"z_{name}"]
        still = (rising & (t_l > prev_t)).fillna(False)
        stops = (rising & (t_l <= prev_t) & lid.isna() & (prev_z > 2.0)).fillna(False)
        lid = lid.mask(stops, prev_z)
        rising = still
        prev_t = t_l.fillna(prev_t)
        prev_z = z_l.fillna(prev_z)
    # Still rising at the top of the profile: the lid is at least the topmost level.
    lid = lid.mask(rising & lid.isna(), out["z_850"])
    out["inversion_lid_m"] = lid.where(out["is_inversion"] == 1)
    return out


def layer_mean_wind(df: pd.DataFrame, depth_m) -> pd.Series:
    """Mean wind speed through a layer of the given depth, m/s.

    Wind increases with height, so the 10 m reading alone understates the flux a 600 m
    deep mixed layer actually carries. We fit a power law u(z) = u10 (z/10)**alpha per
    hour from the measured 10 m and 100 m winds — no assumed exponent where data
    exists — and integrate it over the layer.
    """
    u10 = pd.to_numeric(df["wind_speed_10m"], errors="coerce").clip(lower=0.05)
    u100 = pd.to_numeric(df["wind_speed_100m"], errors="coerce")
    with np.errstate(divide="ignore", invalid="ignore"):
        alpha = np.log(u100 / u10) / np.log(10.0)
    alpha = pd.Series(alpha, index=df.index).replace([np.inf, -np.inf], np.nan)
    alpha = alpha.clip(0.05, 0.60).fillna(URBAN_ALPHA)
    h = pd.Series(np.asarray(depth_m, dtype=float), index=df.index).clip(lower=C.MIN_PBL_M)
    return u10 * (h / 10.0) ** alpha / (1.0 + alpha)


def dispersion(df: pd.DataFrame) -> pd.DataFrame:
    """Effective mixing depth, ventilation coefficient and the stagnation flag."""
    out = df.copy()
    pbl = pd.to_numeric(out["boundary_layer_height"], errors="coerce").clip(lower=C.MIN_PBL_M)

    # Pollution mixes through the SHALLOWER of the modelled boundary layer and the
    # inversion lid. Where a lid sits below the nominal PBL top the lid wins — that is
    # precisely the trapping mechanism the problem statement calls out.
    lid = pd.to_numeric(out.get("inversion_lid_m"), errors="coerce")
    depth = np.fmin(pbl, lid.fillna(np.inf))
    # np.fmin(NaN, inf) is inf, so a missing PBL used to yield an INFINITE mixing depth
    # that propagated as inf into the ventilation coefficient and broke every downstream
    # fit. Infinity is not a depth: turn it back into the missing value it really is,
    # and cap at a physically possible maximum.
    depth = pd.Series(depth, index=out.index).replace([np.inf, -np.inf], np.nan)
    out["mixing_depth_m"] = depth.clip(lower=C.MIN_PBL_M, upper=C.MAX_PBL_M)

    out["layer_wind_ms"] = layer_mean_wind(out, out["mixing_depth_m"])
    out["ventilation_coeff"] = out["mixing_depth_m"] * out["layer_wind_ms"]

    vc = out["ventilation_coeff"]
    out["dispersion_class"] = np.select(
        [vc < C.VC_SEVERE, vc < C.VC_POOR], ["severe", "poor"], default="fair")
    out["is_stagnant"] = (vc < C.VC_SEVERE).astype("int8")
    return out


def stagnation_runs(df: pd.DataFrame) -> pd.DataFrame:
    """Stagnation on two timescales, because they mean different things.

    The hourly flag is nearly always true at night: the boundary layer collapses after
    sunset everywhere, every day, in every season. Measured over Delhi in September it
    fired on 89% of hours, which makes it almost useless as a predictor and inflates
    "consecutive stagnant hours" to multi-day runs that are really just a run of
    ordinary nights.

    What actually characterises a pollution EPISODE is when the daytime fails to clear
    out what the night accumulated. So the episode indicator uses a 24-hour rolling
    mean ventilation coefficient, which averages over the diurnal cycle and only trips
    when dispersion is poor around the clock. Both are kept: the hourly flag drives the
    instantaneous dilution term, the episode flag drives the multi-day accumulation.
    """
    out = df.sort_values(["cell_id", "time"]).copy()
    grp = out["cell_id"]

    # --- hourly ---
    stag = out["is_stagnant"].fillna(0).astype(int)
    block = (stag != stag.groupby(grp).shift(fill_value=0)).groupby(grp).cumsum()
    out["stagnation_hours"] = (stag.groupby([grp, block]).cumsum() * stag).astype("int32")

    # --- daily / episode ---
    # The published VC thresholds (6000 "poor", 3000 "severe") are defined on the
    # AFTERNOON ventilation - mixing height at its daily maximum times the transport
    # wind. Applying them to a 24-hour mean compares against the wrong quantity: the
    # mean is dragged down by nights that are stagnant everywhere, every day, which is
    # why a naive 24h-mean test flagged 96% of hours as an episode.
    #
    # The physically meaningful question is whether the day EVER clears out. So the
    # episode test is on the rolling 24-hour MAXIMUM: if even the best-ventilated hour
    # of the last day could not disperse, pollution accumulates across days.
    roll = out.groupby("cell_id")["ventilation_coeff"]
    out["vc_24h_mean"] = roll.transform(lambda s: s.rolling(24, min_periods=6).mean())
    out["vc_24h_max"] = roll.transform(lambda s: s.rolling(24, min_periods=6).max())
    out["is_episode"] = (out["vc_24h_max"] < C.VC_POOR).fillna(False).astype("int8")
    epi = out["is_episode"].astype(int)
    eblock = (epi != epi.groupby(grp).shift(fill_value=0)).groupby(grp).cumsum()
    out["episode_hours"] = (epi.groupby([grp, eblock]).cumsum() * epi).astype("int32")
    return out


def pasquill(df: pd.DataFrame) -> pd.Series:
    """Pasquill–Gifford stability class, A (very unstable) to F (very stable).

    The classic Turner scheme: strong daytime insolation with light wind gives the
    convective classes; clear calm nights give the stable ones. The plume model uses
    this to choose how fast a puff spreads sideways as it travels.
    """
    u = pd.to_numeric(df["wind_speed_10m"], errors="coerce").fillna(2.0)
    sw = pd.to_numeric(df["shortwave_radiation"], errors="coerce").fillna(0.0)
    cloud = pd.to_numeric(df.get("cloud_cover"), errors="coerce").fillna(50.0)
    day = sw > 20.0

    cls = pd.Series("D", index=df.index, dtype=object)  # neutral default
    strong = sw >= 600
    moder = (sw >= 300) & (sw < 600)
    slight = (sw >= 20) & (sw < 300)

    cls = cls.mask(day & strong & (u < 2), "A")
    cls = cls.mask(day & strong & (u >= 2) & (u < 5), "B")
    cls = cls.mask(day & strong & (u >= 5), "C")
    cls = cls.mask(day & moder & (u < 5), "B")
    cls = cls.mask(day & moder & (u >= 5), "C")
    cls = cls.mask(day & slight & (u < 2), "B")
    cls = cls.mask(day & slight & (u >= 2) & (u < 5), "C")
    cls = cls.mask(day & slight & (u >= 5), "D")

    # Night: cloud cover decides how fast the surface radiates its heat away.
    clear = (~day) & (cloud < 40)
    cloudy = (~day) & (cloud >= 40)
    cls = cls.mask(clear & (u < 3), "F")
    cls = cls.mask(clear & (u >= 3) & (u < 5), "E")
    cls = cls.mask(cloudy & (u < 2), "F")
    cls = cls.mask(cloudy & (u >= 2) & (u < 3), "E")
    return cls


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Full pipeline: profile -> inversion -> dispersion -> stagnation -> stability."""
    if df.empty:
        return df
    out = inversion(df)
    out = dispersion(out)
    out = stagnation_runs(out)
    out["stability_class"] = pasquill(out)
    return out
