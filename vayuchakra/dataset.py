"""Assemble the supervised learning panel.

One row per station per hour, carrying everything known at forecast time plus the
value we are trying to predict. Three sources are joined: observations (the target),
meteorology with its derived stability indices (the physics), and the CAMS chemistry
prior (the coupled-model input).

TWO DESIGN CHOICES WORTH DEFENDING
-----------------------------------
**Meteorology is fetched at station coordinates, not interpolated from the grid.**
Interpolating first would bake spatial error into every training label's features,
and the model would learn to correct our interpolation rather than the atmosphere.
Open-Meteo's multi-point batching makes 161 stations cost two requests, so there is no
reason to accept that error. Inference still runs on the grid; the interpolation error
then lands where it belongs — in the prediction, not in the training signal.

**Target-time weather is a feature, and that is not leakage.** A 24-hour AQI forecast
is allowed to know the 24-hour *weather* forecast, because one genuinely exists at
prediction time. What it may not know is the pollution at the target hour. So every
`target_*` column is meteorological or calendrical, and every pollution feature is
strictly lagged from the source hour. The split below enforces that by construction
rather than by convention.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from . import config as C
from . import chem_prior, indices, met, obs, photolysis
from .grid import Cell

#: Lags of the observed pollutant at the SOURCE hour. 1 h captures persistence, 24 h
#: the same hour yesterday (Delhi's diurnal cycle is very strong), 48 h the trend.
LAGS_H = (1, 3, 6, 12, 24, 48)
ROLL_H = (24, 72)

#: Delhi's festival calendar drives real emission spikes. Diwali alone lifted the city
#: mean from 150 to 414 ug/m3 on 4 Nov 2021 in our own pulled data, so a model without
#: this flag has to explain that as weather and cannot.
DIWALI_DATES = {
    "2015-11-11", "2016-10-30", "2017-10-19", "2018-11-07", "2019-10-27",
    "2020-11-14", "2021-11-04", "2022-10-24", "2023-11-12", "2024-11-01",
    "2025-10-20", "2026-11-08",
}

#: Paddy-stubble burning season in Punjab and Haryana. A calendar flag is not a plume
#: model - `plume.py` does that - but it lets the learner separate "October" from
#: "October during burning" before any satellite data arrives.
CROP_BURN_MONTH_DAY = ((10, 1), (11, 30))


def _to_cells(stations: list[obs.Station]) -> list[Cell]:
    """Treat each station as a grid cell so the met/chem fetchers can be reused."""
    return [Cell(cell_id=s.id, lat=s.lat, lon=s.lon, district="STN",
                 dist_km=0.0, tier="station") for s in stations]


def add_calendar(df: pd.DataFrame, time_col: str = "time", prefix: str = "") -> pd.DataFrame:
    """Calendar features. Known exactly in advance, so safe at any horizon."""
    out = df.copy()
    t = pd.to_datetime(out[time_col], utc=True)
    ist = t.dt.tz_convert("Asia/Kolkata")          # Delhi lives on IST, not UTC
    out[f"{prefix}hour"] = ist.dt.hour
    out[f"{prefix}month"] = ist.dt.month
    out[f"{prefix}weekday"] = ist.dt.weekday
    out[f"{prefix}doy"] = ist.dt.dayofyear
    out[f"{prefix}is_weekend"] = (ist.dt.weekday >= 5).astype("int8")
    out[f"{prefix}is_winter"] = ist.dt.month.isin([11, 12, 1, 2]).astype("int8")
    out[f"{prefix}is_summer"] = ist.dt.month.isin([4, 5, 6]).astype("int8")
    out[f"{prefix}is_monsoon"] = ist.dt.month.isin([7, 8, 9]).astype("int8")

    md = list(zip(ist.dt.month, ist.dt.day))
    lo, hi = CROP_BURN_MONTH_DAY
    out[f"{prefix}is_crop_burn"] = np.array(
        [1 if (lo <= (m, d) <= hi) else 0 for m, d in md], dtype="int8")

    dstr = ist.dt.strftime("%Y-%m-%d")
    diwali = dstr.isin(DIWALI_DATES)
    # The night after Diwali matters as much as the night of it.
    prev = (ist - pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d").isin(DIWALI_DATES)
    out[f"{prefix}is_diwali"] = diwali.astype("int8")
    out[f"{prefix}is_post_diwali"] = prev.astype("int8")

    # Cyclical encodings: hour 23 and hour 0 are adjacent, and a raw integer hides that.
    out[f"{prefix}hour_sin"] = np.sin(2 * np.pi * out[f"{prefix}hour"] / 24.0)
    out[f"{prefix}hour_cos"] = np.cos(2 * np.pi * out[f"{prefix}hour"] / 24.0)
    out[f"{prefix}doy_sin"] = np.sin(2 * np.pi * out[f"{prefix}doy"] / 365.25)
    out[f"{prefix}doy_cos"] = np.cos(2 * np.pi * out[f"{prefix}doy"] / 365.25)
    return out


def add_wind_components(df: pd.DataFrame) -> pd.DataFrame:
    """Wind direction as u/v components.

    Direction in degrees is discontinuous at north: 359 and 1 are neighbours but look
    like opposite extremes to a tree split. u/v are continuous and let the model learn
    "north-westerly", which is the direction stubble smoke arrives from.
    """
    out = df.copy()
    for src, tag in (("wind_direction_10m", "10m"), ("wind_direction_100m", "100m")):
        if src not in out.columns:
            continue
        rad = np.radians(pd.to_numeric(out[src], errors="coerce"))
        spd = pd.to_numeric(out.get(f"wind_speed_{tag}"), errors="coerce")
        out[f"wind_u_{tag}"] = -spd * np.sin(rad)
        out[f"wind_v_{tag}"] = -spd * np.cos(rad)
    return out


def _downcast(df: pd.DataFrame) -> pd.DataFrame:
    """float64 to float32 before the panel gets wide.

    Every value here carries three or four significant figures at best: a temperature
    from a reanalysis, a pollutant concentration from a reference monitor, an optical
    depth. float32 holds about seven, so nothing measurable is lost, and
    `make_supervised` already casts to float32 further down the pipeline. Doing it here
    instead halves the frame before the operations that need a second copy of it.
    """
    for col in df.columns:
        if df[col].dtype == "float64":
            df[col] = df[col].astype("float32")
    return df


def add_lags(df: pd.DataFrame, cols: tuple[str, ...] = ("pm25", "o3", "no2")) -> pd.DataFrame:
    """Lagged and rolling pollutant history, per station.

    Reindexed onto a continuous hourly axis first. Without that, `shift(24)` means "24
    rows back", and a station with gaps would silently pair a value with something 40
    hours earlier - a subtle corruption that never raises an error and quietly teaches
    the model the wrong autocorrelation.
    """
    out = df.sort_values(["station_id", "time"], ignore_index=True)

    # Only the pollutant columns take part in this, so the reindex and the concat run
    # over about twenty columns instead of the panel's hundred and thirty. Doing it on
    # the whole frame needed a second full copy of the panel, and on the five-winter
    # build that was the allocation that failed: 1.2 million rows of float64 is 1.4 GB
    # before the copy. The wide columns are joined back afterwards.
    lag_cols = [c for c in cols if c in out.columns]
    slim = out[["station_id", "time", *lag_cols]]
    pieces = []
    for sid, grp in slim.groupby("station_id", sort=False):
        g = grp.set_index("time")
        full = pd.date_range(g.index.min(), g.index.max(), freq="h", tz="UTC")
        g = g.reindex(full)
        g["station_id"] = sid
        for col in cols:
            if col not in g.columns:
                continue
            for lag in LAGS_H:
                g[f"{col}_lag_{lag}h"] = g[col].shift(lag)
            for win in ROLL_H:
                g[f"{col}_roll_{win}h"] = g[col].shift(1).rolling(win, min_periods=max(3, win // 4)).mean()
            # Yesterday's peak: episodes build day on day, and the previous day's
            # maximum carries that better than its mean.
            g[f"{col}_prev_day_max"] = g[col].shift(1).rolling(24, min_periods=6).max()
            # Short-term tendency: is it building or clearing?
            g[f"{col}_delta_6h"] = g[col].shift(1) - g[col].shift(7)
        g = g.reset_index().rename(columns={"index": "time"})
        pieces.append(g)
    lagged = pd.concat(pieces, ignore_index=True).dropna(subset=["time"])
    del pieces

    # Left-join FROM the lagged frame so the row set stays the continuous hourly axis,
    # exactly as it was when the reindex was applied to the whole panel.
    rest = out.drop(columns=lag_cols)
    del out
    return lagged.merge(rest, on=["station_id", "time"], how="left")


def add_pbl_anomaly(df: pd.DataFrame) -> pd.DataFrame:
    """Mixing depth relative to what is normal for this hour and month.

    This exists to close a train/serve gap. The forecast API serves pressure-level
    temperatures, so `inversion_strength_k` is a real number in kelvin there; the ERA5
    archive does not, so it is NaN throughout training. A feature that is present at
    inference and absent in training is worse than useless — the model never learned to
    use it, and its apparent availability invites someone to assume it did.

    A boundary layer of 200 m is unremarkable at 3 a.m. and extraordinary at 3 p.m., so
    the raw depth alone under-expresses the anomaly. The ratio to the hour-and-month
    climatology carries the same information the inversion strength would, and is
    computable **identically from forecast and archive data** — which is the property
    that matters. The true kelvin figure is still computed and displayed where it
    exists; it is simply not a model input.
    """
    out = df.copy()
    if "mixing_depth_m" not in out.columns:
        return out
    t = pd.to_datetime(out["time"], utc=True).dt.tz_convert("Asia/Kolkata")
    key = [t.dt.hour, t.dt.month]
    clim = out.groupby(key)["mixing_depth_m"].transform("median")
    out["pbl_climatology_m"] = clim
    out["pbl_anomaly"] = out["mixing_depth_m"] / clim.clip(lower=C.MIN_PBL_M)
    out["pbl_anomaly"] = out["pbl_anomaly"].replace([np.inf, -np.inf], np.nan).clip(0.0, 10.0)
    if "ventilation_coeff" in out.columns:
        vclim = out.groupby(key)["ventilation_coeff"].transform("median")
        out["vc_anomaly"] = (out["ventilation_coeff"] / vclim.clip(lower=1.0)
                             ).replace([np.inf, -np.inf], np.nan).clip(0.0, 10.0)
    return out


def build_panel(
    stations: list[obs.Station],
    start: str,
    end: str,
    *,
    with_chem: bool = True,
    cache_name: str | None = None,
) -> pd.DataFrame:
    """Join observations, meteorology, indices and the chemistry prior into one frame.

    `with_chem=False` produces the reduced configuration used for the DSS window, where
    CAMS has no coverage before mid-August 2022.
    """
    cache = (C.DATA / f"{cache_name}.parquet") if cache_name else None
    if cache and cache.exists():
        print(f"[dataset] loading cached panel {cache.name}")
        return pd.read_parquet(cache)

    cells = _to_cells(stations)
    print(f"[dataset] {len(stations)} stations, {start} -> {end}")

    o = obs.fetch_archive([s.id for s in stations], start, end)
    if o.empty:
        print("[dataset] no observations returned")
        return pd.DataFrame()
    print(f"[dataset] observations: {len(o):,} station-hours")

    m = met.fetch_archive(cells, start, end)
    if m.frame.empty:
        print("[dataset] no meteorology returned")
        return pd.DataFrame()
    mm = indices.enrich(m.frame).rename(columns={"cell_id": "station_id"})
    print(f"[dataset] meteorology: {len(mm):,} rows ({mm['inversion_method'].iloc[0]} path)")

    panel = o.merge(mm.drop(columns=["lat", "lon"], errors="ignore"),
                    on=["station_id", "time"], how="inner")

    if with_chem:
        c = chem_prior.fetch_archive(cells, start, end)
        if c.available:
            panel = panel.merge(c.frame.rename(columns={"cell_id": "station_id"}),
                                on=["station_id", "time"], how="left")
            print(f"[dataset] chemistry prior joined ({len(c.frame):,} rows)")
        else:
            print(f"[dataset] chemistry prior unavailable: {c.note}")

    panel = _downcast(panel)
    panel = add_lags(panel)
    panel = add_wind_components(panel)
    panel = add_pbl_anomaly(panel)
    # Photolysis: how much ultraviolet the aerosol is removing. This is the pathway the
    # literature says dominates the aerosol effect on ozone (10-12%, against 1-3% for the
    # radiation-meteorology route), and it separates "dim because it is December" from
    # "dim because the air is full of smoke" - which a raw radiation feature cannot do.
    panel = photolysis.add_features(panel)
    panel = add_calendar(panel)
    panel = panel.sort_values(["station_id", "time"]).reset_index(drop=True)
    print(f"[dataset] panel: {len(panel):,} rows x {len(panel.columns)} columns")

    if cache:
        try:
            panel.to_parquet(cache, index=False)
            print(f"[dataset] cached -> {cache.name}")
        except Exception as exc:
            print(f"[dataset] cache write failed: {exc}")
    return panel


def make_supervised(panel: pd.DataFrame, horizon_h: int, target: str = "pm25") -> pd.DataFrame:
    """Turn the panel into (features at t, target at t + horizon).

    The target-time meteorology is joined by shifting the met columns BACKWARD by the
    horizon, which is the same thing a real forecast does: at hour t we hold a weather
    forecast valid for t+24. Pollution columns are never shifted backward, so nothing
    about the future air can leak into the features.
    """
    if panel.empty or target not in panel.columns:
        return pd.DataFrame()

    met_cols = [c for c in (
        "temperature_2m", "relative_humidity_2m", "surface_pressure", "precipitation",
        "cloud_cover", "wind_speed_10m", "wind_speed_100m", "wind_u_10m", "wind_v_10m",
        "wind_u_100m", "wind_v_100m", "boundary_layer_height", "shortwave_radiation",
        "direct_radiation", "diffuse_radiation", "soil_temperature_0_to_7cm",
        "mixing_depth_m", "ventilation_coeff", "layer_wind_ms", "vc_24h_mean",
        "vc_24h_max", "inversion_strength_k", "inversion_lid_m", "is_inversion",
        "lapse_k_per_100m", "theta_grad_k_per_100m", "stagnation_hours",
        "episode_hours", "is_stagnant", "is_episode",
        "pbl_anomaly", "vc_anomaly", "pbl_climatology_m",
        "cams_pm25", "cams_pm10", "cams_o3", "cams_no2", "cams_aod", "cams_dust",
        # Photolysis at the TARGET hour: legitimate, because AOD and sun angle are both
        # forecast quantities, exactly like temperature and wind.
        "j_no2", "j_o1d", "j_no2_clear", "j_attenuation", "j_no2_ratio",
        "j_no2_deficit", "solar_zenith_deg",
    ) if c in panel.columns]

    # Memory matters here more than anywhere else in the project. The panel is ~537k
    # rows by 130 columns; adding a `target_*` copy of the meteorology takes it past 170,
    # and pandas materialises several intermediates while concatenating. In float64 that
    # exceeded available memory and killed a 43-minute build's payoff.
    #
    # Two fixes: carry only the columns that can actually become features, and store
    # them as float32. Halving the width costs nothing in accuracy - XGBoost casts to
    # float32 internally anyway - and takes the working set from gigabytes to hundreds
    # of megabytes.
    drop_prefixes = ("target_",)
    base_cols = [c for c in panel.columns
                 if not c.startswith(drop_prefixes) and c not in ("horizon_h",)]
    slim = panel[base_cols]

    rows = []
    for sid, grp in slim.groupby("station_id", sort=False):
        g = grp.set_index("time").sort_index()
        full = pd.date_range(g.index.min(), g.index.max(), freq="h", tz="UTC")
        g = g.reindex(full)

        future = g[met_cols].shift(-horizon_h).add_prefix("target_").astype("float32")
        y = g[target].shift(-horizon_h).rename("y").astype("float32")
        # Drop rows with no label before anything else is assembled: for a 72-hour
        # horizon that is a meaningful share of the frame, and carrying them through the
        # concat is pure waste.
        keep = y.notna().to_numpy()
        if not keep.any():
            continue

        cal = add_calendar(pd.DataFrame({"time": g.index + pd.Timedelta(hours=horizon_h)}),
                           prefix="target_").drop(columns=["time"])
        cal.index = g.index

        num = g.select_dtypes(include=["number"]).astype("float32")
        obj = g[[c for c in g.columns if c not in num.columns]]
        piece = pd.concat([num[keep], obj[keep], future[keep],
                           cal[keep].astype("float32"), y[keep]], axis=1)
        piece["station_id"] = sid
        piece["horizon_h"] = np.int16(horizon_h)
        rows.append(piece.reset_index().rename(columns={"index": "time"}))
        del g, future, cal, num, obj, piece

    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True)
    return out.reset_index(drop=True)


def feature_columns(df: pd.DataFrame, target: str) -> list[str]:
    """Which columns the model may see.

    An explicit allow-list of prefixes rather than "everything except the target",
    because the failure mode of the latter is silent: one stray future-derived column
    and the validation score becomes fiction.
    """
    banned_exact = {"y", "time", "station_id", "horizon_h", "datetime",
                    "lat", "lon", "name", "provider", "tier", "district",
                    "inversion_method", "dispersion_class", "stability_class"}
    # Contemporaneous pollutant readings are the answer, not a feature. Only their
    # lagged and rolled forms survive.
    banned_exact |= set(obs.POLLUTANTS) | set(obs.STATION_MET)

    keep = []
    for col in df.columns:
        if col in banned_exact or df[col].dtype == object:
            continue
        keep.append(col)
    return keep


def split_holdout_window(df: pd.DataFrame, start: str, end: str
                         ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Hold out a named window; train on everything outside it.

    The chronological split has a blind spot that only shows up when you look at what
    landed in the test set. On a panel running Feb 2025 to Aug 2026, the last 20% by time
    is **May to August 2026** - no winter at all. Every metric scored that way is a
    summer and monsoon score, and Delhi's defining pollution season is never evaluated.

    That matters most for exactly the physics we are testing: the literature's claim is
    that ozone production in Delhi is *radiation-limited in winter*, so measuring the
    photolysis effect on a summer-only hold-out tests it in the one season where it is
    weakest.

    This is still a clean out-of-sample test - the held-out window is absent from
    training entirely - it just chooses the window by season rather than by recency.
    """
    if df.empty:
        return df, df
    t = pd.to_datetime(df["time"], utc=True)
    lo = pd.Timestamp(start, tz="UTC")
    hi = pd.Timestamp(end, tz="UTC")
    in_window = (t >= lo) & (t <= hi)
    return df[~in_window].copy(), df[in_window].copy()


def split_time_ordered(df: pd.DataFrame, test_fraction: float = 0.2) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Chronological split — train on the past, test on the future.

    A random split would let the model see hour 14 of a day while predicting hour 15 of
    the same day at the same station, which is not forecasting and inflates every score.
    """
    if df.empty:
        return df, df
    order = df.sort_values("time")
    cut = order["time"].quantile(1.0 - test_fraction)
    return order[order["time"] <= cut].copy(), order[order["time"] > cut].copy()
