"""CPCB National Air Quality Index.

We predict **concentrations** and compute the index from them here, rather than
predicting the index directly. Two reasons, and both matter for defending the work:

* AQI is a max-of-sub-indices over piecewise-linear breakpoints — a discontinuous,
  non-monotone-in-any-single-pollutant function. Asking a regressor to learn that
  lookup table *on top of* the atmospheric physics wastes capacity on arithmetic we
  can simply do exactly.
* Computing it here makes it auditable. Any reviewer can check these breakpoints
  against the published CPCB table; nobody can check a number that emerged from a
  tree ensemble.

THE AVERAGING WINDOWS ARE PART OF THE STANDARD
-----------------------------------------------
CPCB's index is not defined on a spot reading. PM2.5, PM10, NO2 and SO2 use a
**24-hour mean**; O3 and CO use the **maximum 8-hour rolling mean** in the day. An
index computed from instantaneous values is a different quantity that happens to share
a name, and it reads far higher than the published figure during an evening peak. The
sibling project found exactly this: hourly-basis AQI at Anand Vihar read 351 against a
correct 194.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

#: CPCB sub-index breakpoints: pollutant -> [(C_low, C_high, I_low, I_high), ...].
#: Concentrations in ug/m3 except CO, which is mg/m3.
BREAKPOINTS: dict[str, list[tuple[float, float, float, float]]] = {
    "pm25": [(0, 30, 0, 50), (30, 60, 51, 100), (60, 90, 101, 200),
             (90, 120, 201, 300), (120, 250, 301, 400), (250, 380, 401, 500)],
    "pm10": [(0, 50, 0, 50), (50, 100, 51, 100), (100, 250, 101, 200),
             (250, 350, 201, 300), (350, 430, 301, 400), (430, 510, 401, 500)],
    "no2":  [(0, 40, 0, 50), (40, 80, 51, 100), (80, 180, 101, 200),
             (180, 280, 201, 300), (280, 400, 301, 400), (400, 520, 401, 500)],
    "o3":   [(0, 50, 0, 50), (50, 100, 51, 100), (100, 168, 101, 200),
             (168, 208, 201, 300), (208, 748, 301, 400), (748, 1000, 401, 500)],
    "so2":  [(0, 40, 0, 50), (40, 80, 51, 100), (80, 380, 101, 200),
             (380, 800, 201, 300), (800, 1600, 301, 400), (1600, 2400, 401, 500)],
    "co":   [(0, 1, 0, 50), (1, 2, 51, 100), (2, 10, 101, 200),
             (10, 17, 201, 300), (17, 34, 301, 400), (34, 50, 401, 500)],
}

#: Averaging window per pollutant, in hours, as the standard defines them.
AVERAGING_HOURS = {"pm25": 24, "pm10": 24, "no2": 24, "so2": 24, "o3": 8, "co": 8}

#: The published band names and ranges.
BANDS: tuple[tuple[str, float, float], ...] = (
    ("Good", 0, 50), ("Satisfactory", 51, 100), ("Moderate", 101, 200),
    ("Poor", 201, 300), ("Very Poor", 301, 400), ("Severe", 401, 10_000),
)

#: CPCB requires at least three pollutants, one of which must be PM2.5 or PM10.
MIN_POLLUTANTS = 3


def sub_index(concentration, pollutant: str):
    """Piecewise-linear sub-index for one pollutant. Vectorised; NaN passes through."""
    bp = BREAKPOINTS.get(pollutant)
    if bp is None:
        return np.full(np.shape(concentration), np.nan)
    c = np.asarray(concentration, dtype="float64")
    out = np.full(c.shape, np.nan)
    for c_lo, c_hi, i_lo, i_hi in bp:
        # Adjacent bands share an endpoint (0-30 then 30-60), so a concentration
        # landing exactly on one matches both. The FIRST match must win: CPCB's table
        # puts PM2.5 of 30 at index 50, the top of the lower band, not 51 at the
        # bottom of the next. Only filling where still unset enforces that.
        m = (c >= c_lo) & (c <= c_hi) & np.isfinite(c) & np.isnan(out)
        if m.any():
            out[m] = i_lo + (i_hi - i_lo) * (c[m] - c_lo) / (c_hi - c_lo)
    # Above the top breakpoint the index is capped at 500 rather than extrapolated:
    # the scale simply does not define values beyond it.
    top_c, top_i = bp[-1][1], bp[-1][3]
    out = np.where(np.isfinite(c) & (c > top_c), top_i, out)
    return out


def band_for(aqi) -> np.ndarray:
    """Band name for an index value.

    Selected on the LOWER bound only. The published ranges are contiguous over
    integers (0-50, then 51-100), so a fractional value between an upper bound and the
    next lower bound - 50.4, 100.5, 200.7 - matches no band at all under a naive
    two-sided test and falls through to whatever the code does last. In the sibling
    project that fall-through returned **Severe**, and four genuinely clean wards were
    published as Severe because their index landed on a fraction.
    """
    a = np.asarray(aqi, dtype="float64")
    out = np.full(a.shape, "Unknown", dtype=object)
    for name, lo, _hi in BANDS:
        out = np.where(np.isfinite(a) & (a >= lo), name, out)
    return out


def aqi_from_concentrations(conc: dict) -> tuple[np.ndarray, np.ndarray]:
    """Index and driving pollutant from a dict of pollutant -> concentration array.

    Returns NaN where fewer than three pollutants are available or neither particulate
    is present, rather than quietly computing an index from whatever happened to be
    measured. A "PM2.5-only AQI" is not the CPCB index and must not be labelled as one.
    """
    usable = {p: np.asarray(v, dtype="float64") for p, v in conc.items() if p in BREAKPOINTS}
    if not usable:
        return np.array([]), np.array([])

    n = max(np.size(v) for v in usable.values())
    subs, names = [], []
    for p, v in usable.items():
        s = sub_index(np.broadcast_to(v, (n,)) if np.size(v) != n else v, p)
        subs.append(s)
        names.append(p)
    stack = np.vstack(subs)

    valid_count = np.sum(np.isfinite(stack), axis=0)
    has_pm = np.zeros(n, dtype=bool)
    for p in ("pm25", "pm10"):
        if p in names:
            has_pm |= np.isfinite(stack[names.index(p)])
    ok = (valid_count >= MIN_POLLUTANTS) & has_pm

    # An all-NaN column is normal (a cell-hour with no usable pollutant) and nanmax
    # warns about it. Filling with -inf first makes the intent explicit and keeps the
    # log clean, since the `ok` mask below discards those rows anyway.
    filled = np.where(np.isfinite(stack), stack, -np.inf)
    with np.errstate(invalid="ignore"):
        idx = np.max(filled, axis=0)
        driver_i = np.argmax(filled, axis=0)
    idx = np.where(np.isneginf(idx), np.nan, idx)
    driver = np.array([names[i] for i in driver_i], dtype=object)

    return np.where(ok, idx, np.nan), np.where(ok, driver, None)


def rolling_for_index(df: pd.DataFrame, group: str | list[str] = "cell_id",
                      time_col: str = "time") -> pd.DataFrame:
    """Apply each pollutant's CPCB averaging window across a time series.

    PM2.5/PM10/NO2/SO2 become 24-hour means; O3 and CO become the maximum 8-hour
    rolling mean over the trailing day, which is what "8-hourly max" means in the
    standard. Requires at least two-thirds of the window present, so a station that
    reported twice in a day does not produce a confident-looking daily figure.

    ``group`` accepts a list because a forecast frame stacks several horizons: rows are
    keyed by (cell, horizon, time), and grouping on the cell alone interleaves three
    different forecasts into one series. Every rolling mean would then average across
    horizons, and the resulting AQI would be a blend of the 24-, 48- and 72-hour
    predictions rather than any of them. When a `horizon_h` column is present it is
    added to the key automatically, because forgetting to pass it is silent.
    """
    keys = [group] if isinstance(group, str) else list(group)
    if "horizon_h" in df.columns and "horizon_h" not in keys:
        keys.append("horizon_h")
    keys = [k for k in keys if k in df.columns]
    if not keys:
        return df.copy()

    out = df.sort_values(keys + [time_col]).copy()
    for pollutant, hours in AVERAGING_HOURS.items():
        if pollutant not in out.columns:
            continue
        min_p = max(2, int(hours * 2 / 3))
        rolled = out.groupby(keys)[pollutant].transform(
            lambda s: s.rolling(hours, min_periods=min_p).mean())
        if hours == 8:
            # The standard asks for the day's MAXIMUM 8-hour mean, not the latest one.
            out[f"{pollutant}_cpcb"] = rolled.groupby(
                [out[k] for k in keys]).transform(
                    lambda s: s.rolling(24, min_periods=8).max())
        else:
            out[f"{pollutant}_cpcb"] = rolled
    return out


def compute(df: pd.DataFrame, suffix: str = "_cpcb") -> pd.DataFrame:
    """Attach `aqi`, `aqi_driver` and `aqi_band` using the windowed concentrations."""
    out = df.copy()
    conc = {p: out[f"{p}{suffix}"] for p in BREAKPOINTS if f"{p}{suffix}" in out.columns}
    if not conc:
        conc = {p: out[p] for p in BREAKPOINTS if p in out.columns}
    if not conc:
        out["aqi"], out["aqi_driver"], out["aqi_band"] = np.nan, None, "Unknown"
        return out
    idx, driver = aqi_from_concentrations(conc)
    out["aqi"] = idx
    out["aqi_driver"] = driver
    out["aqi_band"] = band_for(idx)
    return out
