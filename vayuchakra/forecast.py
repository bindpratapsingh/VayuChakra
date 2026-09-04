"""The forecast pipeline — everything joined into one run.

    stations -> grid          spatial interpolation of the initial condition
    meteorology -> indices    inversion strength, mixing depth, ventilation
    CAMS -> prior             the coupled-model chemistry input
    fires -> plume            Lagrangian transport of stubble smoke
    models -> PM2.5, O3       two heads, one per pollutant, per horizon
    feedback -> coupling      aerosol dims the sun, the layer shallows, PM2.5 rises
    concentrations -> AQI     the CPCB formula, applied once at the end

DEGRADATION IS PART OF THE DESIGN
----------------------------------
Every stage can fail independently and the run continues without it, recording what was
lost in `notes`. No models trained yet, no OpenAQ key, NASA unreachable, CAMS outside
its coverage window — each degrades one term rather than failing the forecast, and the
result says which. A pipeline that only works when six external services all cooperate
is not a pipeline, and the one thing worse than a missing plume term is a forecast that
quietly pretends it had one.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import aqi as aqi_mod
from . import chem_prior, config as C, dataset, feedback, grid, indices, met, model, obs, photolysis, plume


#: Pollutants the pipeline produces. The first two are the problem statement's own
#: targets and get the careful treatment; the other two exist so the CPCB index has the
#: three-pollutant minimum it requires, and fall back to the CAMS prior when untrained.
TARGETS = ("pm25", "o3", "pm10", "no2")


@dataclass
class ForecastResult:
    frame: pd.DataFrame
    notes: list[str] = field(default_factory=list)
    coupling: dict = field(default_factory=dict)
    fires: dict = field(default_factory=dict)
    generated_at: str = ""
    degraded: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return not self.frame.empty

    def summary(self) -> dict:
        if self.frame.empty:
            return {"available": False, "notes": self.notes, "degraded": self.degraded}
        f = self.frame
        out = {
            "available": True,
            "generated_at": self.generated_at,
            "cells": int(f["cell_id"].nunique()),
            "hours": int(f["time"].nunique()),
            "from": str(f["time"].min()), "to": str(f["time"].max()),
            "degraded": self.degraded,
            "notes": self.notes,
            "coupling": self.coupling,
            "fires": self.fires,
        }
        for col in ("pm25", "o3", "aqi", "plume_pm25"):
            if col in f.columns and f[col].notna().any():
                out[col] = {"mean": round(float(f[col].mean()), 1),
                            "max": round(float(f[col].max()), 1)}
        return out


def interpolate_observations(stations_obs: pd.DataFrame, cells: list[grid.Cell],
                             k: int = 3, power: float = 2.0) -> pd.DataFrame:
    """Spread the station network onto the grid by inverse-distance weighting.

    This is the forecast's initial condition. k=3 and power=2 match the sibling
    project's live layer deliberately, so a reviewer comparing the two is not chasing a
    methodology difference that does not exist.
    """
    if stations_obs.empty or not cells:
        return pd.DataFrame()

    pollutants = [p for p in obs.POLLUTANTS if p in stations_obs.columns]
    coords = (stations_obs.groupby("station_id")[["lat", "lon"]].first()
              .reset_index())
    if coords.empty:
        return pd.DataFrame()

    # Distance matrix once, reused for every hour.
    dist = {}
    for c in cells:
        d = np.array([grid.haversine_km(c.lat, c.lon, r.lat, r.lon)
                      for r in coords.itertuples()])
        order = np.argsort(d)[:k]
        dist[c.cell_id] = (coords["station_id"].to_numpy()[order], d[order])

    rows = []
    for when, grp in stations_obs.groupby("time"):
        by_station = grp.set_index("station_id")
        for c in cells:
            sids, dd = dist[c.cell_id]
            rec = {"cell_id": c.cell_id, "time": when, "lat": c.lat, "lon": c.lon}
            for p in pollutants:
                vals, w = [], []
                for sid, dkm in zip(sids, dd):
                    if sid not in by_station.index:
                        continue
                    v = by_station.at[sid, p]
                    if pd.isna(v):
                        continue
                    if dkm < 1e-6:
                        vals, w = [float(v)], [1.0]
                        break
                    vals.append(float(v))
                    w.append(1.0 / dkm ** power)
                rec[p] = float(np.dot(vals, w) / sum(w)) if w else np.nan
            rows.append(rec)
    return pd.DataFrame(rows)


#: Effective resolution of the inputs, in km. The display grid is 2.8 km over Delhi, but
#: nothing feeding it varies that finely: meteorology is ~11 km, the CAMS prior ~40 km,
#: and the station network averages roughly 5 km between sites.
EFFECTIVE_RESOLUTION_KM = 6.0


def smooth_field(df: pd.DataFrame, cols: tuple[str, ...],
                 radius_km: float = EFFECTIVE_RESOLUTION_KM) -> pd.DataFrame:
    """Gaussian spatial smoothing of the predicted fields.

    This removes structure the model cannot justify, rather than inventing structure it
    does not have.

    **Why it is needed.** Gradient-boosted trees are piecewise constant. Where the
    inputs vary only slightly across a city - measured here, PM2.5 spanned 2.46 µg/m³
    standard deviation across all 420 Delhi cells - neighbouring cells land on either
    side of a split threshold and the output becomes nearly bimodal. The rendered map
    showed a salt-and-pepper checkerboard alternating between two leaf values, with a
    neighbour correlation of 0.50 where a real atmospheric field at 2.8 km spacing
    should exceed 0.9. That pattern is an artefact of the estimator, and displaying it
    invites a reader to interpret quantisation noise as a pollution gradient.

    Smoothing at the inputs' effective resolution states the honest claim: the forecast
    resolves what its drivers resolve, and no finer.
    """
    from scipy.spatial import cKDTree

    if df.empty or not any(c in df.columns for c in cols):
        return df
    out = df.copy()
    present = [c for c in cols if c in out.columns]

    for (_, _), block in out.groupby(["horizon_h", "time"], sort=False):
        if len(block) < 4:
            continue
        lat = block["lat"].to_numpy()
        lon = block["lon"].to_numpy()
        # Local equirectangular projection to kilometres; the domain is small enough
        # that the distortion is far below the smoothing radius.
        x = lon * 111.32 * np.cos(np.radians(lat.mean()))
        y = lat * 110.57
        tree = cKDTree(np.column_stack([x, y]))
        neigh = tree.query_ball_point(np.column_stack([x, y]), r=radius_km * 2.0)
        for col in present:
            v = block[col].to_numpy(dtype="float64")
            sm = np.empty_like(v)
            for i, idx in enumerate(neigh):
                idx = np.asarray(idx, dtype=int)
                vals = v[idx]
                ok = np.isfinite(vals)
                if not ok.any():
                    sm[i] = np.nan
                    continue
                d2 = (x[idx] - x[i]) ** 2 + (y[idx] - y[i]) ** 2
                w = np.exp(-d2 / (2.0 * radius_km ** 2))[ok]
                sm[i] = float(np.sum(w * vals[ok]) / np.sum(w))
            out.loc[block.index, col] = sm
    return out


def _persistence_fallback(frame: pd.DataFrame, target: str) -> np.ndarray:
    """Last resort when no trained head exists: carry the initial condition forward.

    Coalesces the sources **row by row** rather than picking the first column that has
    any data at all. Choosing per column looks equivalent and is not: `pm25_lag_1h`
    exists as a column but is populated only where observations exist — that is, in the
    recent past and nowhere in the forecast window. Returning it wholesale yielded a
    2%-populated forecast, when the CAMS prior was sitting right there covering every
    future hour.

    Reported as degraded regardless. Persistence is a real baseline, not a real
    forecast, and labelling it as the model's output would be the most misleading thing
    this pipeline could do.
    """
    out = pd.Series(np.nan, index=frame.index, dtype="float64")
    for col in (f"{target}_lag_1h", target, f"cams_{target}"):
        if col in frame.columns:
            out = out.fillna(pd.to_numeric(frame[col], errors="coerce"))
    return out.to_numpy(dtype="float64")


def run(
    cells: list[grid.Cell] | None = None,
    horizons: tuple[int, ...] = C.HORIZONS_H,
    *,
    with_plume: bool = True,
    with_coupling: bool = True,
    model_dir=None,
) -> ForecastResult:
    """Produce a 72-hour coupled forecast for the grid."""
    now = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    notes: list[str] = []
    degraded: list[str] = []
    cells = cells or grid.build_grid()

    # --- meteorology (mandatory) -----------------------------------------
    m = met.fetch_forecast(cells, days=5)
    if not m.available:
        return ForecastResult(pd.DataFrame(), ["meteorology unavailable"], {}, {},
                              now.isoformat(), ["meteorology"])
    grid_met = dataset.add_wind_components(indices.enrich(m.frame))
    grid_met = dataset.add_pbl_anomaly(grid_met)
    notes.append(f"meteorology: {m.ok_cells} cells, {m.source}, "
                 f"{grid_met['inversion_method'].iloc[0]} inversion path")

    # --- chemistry prior --------------------------------------------------
    chem = chem_prior.fetch_forecast(cells, days=5)
    if chem.available:
        grid_met = grid_met.merge(chem.frame, on=["cell_id", "time"], how="left")
        notes.append(f"CAMS prior: {chem.ok_cells} cells")
    else:
        degraded.append("chemistry_prior")
        notes.append(f"CAMS prior unavailable: {chem.note}")

    # --- observations as the initial condition ----------------------------
    stations = obs.discover_stations()
    latest = obs.fetch_latest(stations) if stations else pd.DataFrame()
    if latest.empty:
        # Recent archive is a reasonable stand-in and better than starting cold.
        since = (now - dt.timedelta(days=4)).strftime("%Y-%m-%d")
        latest = obs.fetch_archive([s.id for s in stations[:40]], since,
                                   now.strftime("%Y-%m-%d")) if stations else pd.DataFrame()
        if not latest.empty:
            notes.append("live station feed empty; using recent archive")
    if latest.empty:
        degraded.append("observations")
        notes.append("no station observations - initial condition from CAMS only")
        interp = pd.DataFrame()
    else:
        interp = interpolate_observations(latest, cells)
        notes.append(f"observations: {latest['station_id'].nunique()} stations "
                     f"interpolated to {len(cells)} cells")

    # --- assemble the state frame ----------------------------------------
    state = grid_met
    if not interp.empty:
        state = state.merge(interp.drop(columns=["lat", "lon"], errors="ignore"),
                            on=["cell_id", "time"], how="left")
        state = dataset.add_lags(state.rename(columns={"cell_id": "station_id"})
                                 ).rename(columns={"station_id": "cell_id"})
        state = dataset.add_wind_components(state)
    # Photolysis, computed the same way it was for training. Without this the ozone and
    # NO2 heads - which were trained WITH these features - would be served NaN for every
    # one of them. The gap was invisible because the missing-column fallback below fills
    # absent features with NaN, which silently defeats the train/serve check built to
    # catch exactly this.
    state = photolysis.add_features(state)
    state = dataset.add_calendar(state)

    # --- plume ------------------------------------------------------------
    fire_summary: dict = {}
    if with_plume:
        fires = plume.fetch_fires(days=3)
        fire_summary = plume.summarise(fires)
        if fires:
            pl = plume.run(fires, grid_met, cells, hours=max(horizons), start=now)
            if not pl.empty:
                state = state.merge(pl[["cell_id", "time", "plume_pm25"]],
                                    on=["cell_id", "time"], how="left")
                notes.append(f"plume: {len(fires)} fires, "
                             f"peak contribution {pl['plume_pm25'].max():.1f} ug/m3")
        else:
            notes.append("no active fires in the stubble belt (correct off-season)")
    if "plume_pm25" not in state.columns:
        state["plume_pm25"] = 0.0
    state["plume_pm25"] = state["plume_pm25"].fillna(0.0)

    # --- prediction -------------------------------------------------------
    # PM2.5 and O3 are what the problem statement names and what we model properly.
    # PM10 and NO2 are carried too because the CPCB index needs at least three
    # pollutants including a particulate - with only two, `aqi_from_concentrations`
    # correctly refuses and every AQI comes back NaN.
    pieces = []
    for horizon in horizons:
        block = state.copy()
        block["horizon_h"] = horizon
        for target in TARGETS:
            head = model.Head.load(target, horizon, model_dir)
            if head is None:
                block[target] = _persistence_fallback(block, target)
                tag = f"model_{target}_{horizon}h"
                if tag not in degraded:
                    degraded.append(tag)
                continue
            # Target-time meteorology is the same row here: the grid frame is already
            # indexed by valid time, so no shifting is needed - unlike training, where
            # rows are indexed by issue time.
            for col in list(block.columns):
                if f"target_{col}" in head.features and f"target_{col}" not in block.columns:
                    block[f"target_{col}"] = block[col]
            absent = [c for c in head.features if c not in block.columns]
            if absent:
                # Filling a trained feature with NaN is a real degradation, not a
                # formality: the model was fitted expecting a value there. Say so rather
                # than papering over it.
                notes.append(f"{target}/{horizon}h: {len(absent)} trained features "
                             f"absent at inference, filled NaN "
                             f"(first: {', '.join(absent[:3])})")
                tag = f"features_{target}_{horizon}h"
                if tag not in degraded:
                    degraded.append(tag)
            for col in absent:
                block[col] = np.nan
            try:
                block[target] = head.predict(block)
            except (ValueError, RuntimeError) as exc:
                notes.append(f"{target}/{horizon}h prediction failed: {exc}")
                block[target] = _persistence_fallback(block, target)
                degraded.append(f"model_{target}_{horizon}h")
        pieces.append(block)

    out = pd.concat(pieces, ignore_index=True) if pieces else state

    # Smooth to the resolution the inputs actually carry, before the plume and the
    # coupling are applied - both are physically smooth fields and should not be
    # blurred, and the plume in particular carries genuine sharp gradients.
    out = smooth_field(out, TARGETS)

    # Plume smoke is additional mass on top of what the statistical model expects from
    # local conditions, so it adds rather than replaces.
    #
    # NaN is preserved deliberately. Filling an unpredictable hour with zero would turn
    # "we do not know" into "the air is perfectly clean" — the most dangerous possible
    # direction to be wrong in, and one that looks entirely plausible on a map.
    out["pm25_local"] = out["pm25"]
    out["pm25"] = out["pm25"] + out["plume_pm25"].where(out["pm25"].notna(), other=np.nan)

    # --- coupling ---------------------------------------------------------
    coupling: dict = {}
    if with_coupling and "pm25" in out.columns and out["pm25"].notna().any():
        out["pm25_uncoupled"] = out["pm25"]
        aod_model = feedback.calibrate_aod(out) if "cams_aod" in out.columns else feedback.DEFAULT_AOD
        res = feedback.solve(out, aod_model=aod_model)
        out = res.frame
        out["pm25"] = out["pm25_coupled"]
        coupling = res.summary()
        coupling["literature_gate"] = feedback.check_against_literature(res)
        notes.append(f"coupling: {res.iterations} iterations, "
                     f"{'converged' if res.converged else 'DID NOT CONVERGE'}, "
                     f"{res.diverged_rows} rows fell back")
    else:
        degraded.append("coupling")

    # --- AQI --------------------------------------------------------------
    out = aqi_mod.compute(aqi_mod.rolling_for_index(out))

    return ForecastResult(out.sort_values(["cell_id", "horizon_h", "time"]).reset_index(drop=True),
                          notes, coupling, fire_summary, now.isoformat(), degraded)
