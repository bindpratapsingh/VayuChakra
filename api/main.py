"""VayuChakra local API.

Run:  uvicorn api.main:app --reload --port 8100

**Local only.** Nothing here is deployed or hosted; there is no keep-alive, no public
URL, and CORS is open to localhost because the only client is a browser on this
machine.

The expensive work — meteorology for 1,100 cells, a chemistry prior, a plume run, four
pollutants at three horizons, and a coupled solve — takes tens of seconds and is
identical for every caller. So it runs once into a process-level cache and every
endpoint reads that snapshot. A request never triggers a model run unless the cache is
cold or `refresh=true` is passed explicitly.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vayuchakra import config as C           # noqa: E402
from vayuchakra import dss, forecast, grid, photolysis, plume  # noqa: E402

app = FastAPI(title="VayuChakra",
              description="Coupled weather-chemistry forecasting for Delhi NCR",
              version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

#: Snapshot cache. A forecast is valid for an hour; upstream models only run four
#: times a day, so recomputing more often burns time without changing the answer.
_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"at": 0.0, "result": None}
CACHE_TTL = 3600.0


def _clean(obj):
    """JSON-safe: NaN and numpy scalars are not valid JSON and crash the encoder."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if (f != f or f in (float("inf"), float("-inf"))) else round(f, 4)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if obj is pd.NaT or (isinstance(obj, float) and obj != obj):
        return None
    return obj


def get_forecast(refresh: bool = False, delhi_only: bool = True):
    with _LOCK:
        fresh = _CACHE["result"] is not None and (time.time() - _CACHE["at"]) < CACHE_TTL
        if fresh and not refresh:
            return _CACHE["result"]
        cells = grid.build_grid()
        if delhi_only:
            cells = [c for c in cells if c.tier == "delhi"]
        result = forecast.run(cells)
        _CACHE.update({"at": time.time(), "result": result})
        return result


# ─── Operational refresh ─────────────────────────────────────────────────────
#: Off by default. A forecast run takes about two minutes and hits four external
#: services, so a background loop is something an operator opts into rather than
#: something that starts itself on import. Set VAYUCHAKRA_REFRESH=1 to enable.
REFRESH_ENABLED = os.getenv("VAYUCHAKRA_REFRESH", "0") == "1"
REFRESH_INTERVAL_S = float(os.getenv("VAYUCHAKRA_REFRESH_SECONDS", "3600"))
_REFRESH: dict[str, Any] = {"runs": 0, "last_ok": None, "last_error": None,
                            "enabled": REFRESH_ENABLED}


def _refresh_loop() -> None:
    """Keep the snapshot warm so a caller never waits for a cold pipeline.

    Upstream models publish four times a day, so refreshing hourly is already more
    often than the inputs change. Failures are recorded and the loop continues: a
    transient upstream outage should leave the previous good forecast in place rather
    than take the service down with it.
    """
    while True:
        time.sleep(REFRESH_INTERVAL_S)
        try:
            get_forecast(refresh=True)
            _REFRESH["runs"] += 1
            _REFRESH["last_ok"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            _REFRESH["last_error"] = None
        except Exception as exc:                      # noqa: BLE001 - loop must survive
            _REFRESH["last_error"] = f"{type(exc).__name__}: {exc}"
            print(f"[refresh] failed, keeping the previous snapshot: {exc}")


if REFRESH_ENABLED:
    threading.Thread(target=_refresh_loop, daemon=True, name="vayuchakra-refresh").start()
    print(f"[refresh] hourly refresh enabled (every {REFRESH_INTERVAL_S:.0f}s)")


@app.get("/health")
def health():
    """Liveness plus an honest inventory of what this instance can actually do."""
    models = sorted(p.stem for p in C.MODELS.glob("*.meta.json"))
    return _clean({
        "status": "ok",
        "domain": {"lat": [C.LAT_MIN, C.LAT_MAX], "lon": [C.LON_MIN, C.LON_MAX]},
        "grid_cells": len(grid.build_grid()),
        "horizons_h": list(C.HORIZONS_H),
        "trained_heads": [m.replace(".meta", "") for m in models],
        "keys": {"openaq": bool(C.OPENAQ_API_KEY), "firms": bool(C.FIRMS_MAP_KEY)},
        "dss_workbook": dss.available(),
        "cache_age_s": round(time.time() - _CACHE["at"], 1) if _CACHE["result"] else None,
        "auto_refresh": _REFRESH,
    })


@app.get("/forecast")
def get_forecast_endpoint(
    horizon: int = Query(24, description="hours ahead: 24, 48 or 72"),
    refresh: bool = False,
):
    """Per-cell forecast at one horizon: concentrations, AQI, and the coupling terms."""
    r = get_forecast(refresh=refresh)
    if not r.available:
        raise HTTPException(503, detail={"reason": "forecast unavailable", "notes": r.notes})
    f = r.frame[r.frame["horizon_h"] == horizon]
    if f.empty:
        raise HTTPException(404, detail=f"horizon {horizon} not produced")

    # One row per cell, valid at (issue time + horizon).
    #
    # NOT the last row of the frame. The state frame runs two days into the past and
    # five into the future, and CAMS stops supplying a prior about eleven hours before
    # its nominal end — so `tail(1)` landed precisely on the sparsest hours and returned
    # a grid where every single cell had a null AQI. Selecting by valid time asks the
    # question the horizon control is actually asking.
    issued = pd.Timestamp(r.generated_at)
    target = issued + pd.Timedelta(hours=horizon)
    times = pd.to_datetime(f["time"], utc=True)
    nearest = times.iloc[(times - target).abs().argsort().iloc[0]]
    latest = f[times == nearest]
    if latest.empty:
        latest = f.sort_values("time").groupby("cell_id").tail(1)
    cols = ["cell_id", "lat", "lon", "district", "time", "pm25", "o3", "pm10", "no2",
            "aqi", "aqi_band", "aqi_driver", "plume_pm25", "mixing_depth_m",
            "inversion_strength_k", "ventilation_coeff", "pm_amplification_frac"]
    keep = [c for c in cols if c in latest.columns]
    return _clean({"horizon_h": horizon, "generated_at": r.generated_at,
                   "valid_at": str(nearest), "degraded": r.degraded, "notes": r.notes,
                   "cells": latest[keep].to_dict("records")})


@app.get("/summary")
def summary(refresh: bool = False):
    """Headline numbers plus the coupling diagnostics and literature gate."""
    return _clean(get_forecast(refresh=refresh).summary())


@app.get("/inversion")
def inversion(cell_id: int | None = None, refresh: bool = False):
    """The inversion tracker the problem statement asks for, as a time series.

    Inversion strength, mixing depth, ventilation coefficient and stagnation run
    length, hour by hour across the forecast — for one cell, or the city mean.
    """
    r = get_forecast(refresh=refresh)
    if not r.available:
        raise HTTPException(503, detail="forecast unavailable")
    f = r.frame[r.frame["horizon_h"] == r.frame["horizon_h"].min()]
    cols = ["inversion_strength_k", "inversion_lid_m", "mixing_depth_m",
            "ventilation_coeff", "vc_24h_max", "stagnation_hours", "episode_hours",
            "is_inversion", "is_stagnant", "is_episode", "shortwave_radiation",
            "temperature_2m", "wind_speed_10m"]
    cols = [c for c in cols if c in f.columns]
    if cell_id is not None:
        f = f[f["cell_id"] == cell_id]
        if f.empty:
            raise HTTPException(404, detail=f"no cell {cell_id}")
        series = f[["time"] + cols].sort_values("time")
        scope = f"cell {cell_id}"
    else:
        series = f.groupby("time")[cols].mean().reset_index()
        scope = "city mean"
    return _clean({
        "scope": scope,
        "method": str(f["inversion_method"].iloc[0]) if "inversion_method" in f else None,
        "thresholds": {"vc_poor": C.VC_POOR, "vc_severe": C.VC_SEVERE},
        "series": series.to_dict("records"),
    })


@app.get("/coupling")
def coupling(refresh: bool = False):
    """The two-way feedback, made inspectable step by step.

    Returns the per-step diagnostics rather than only the final PM2.5, so each piece of
    physics can be checked separately: how much sun the aerosol removed, how much the
    surface cooled, how much the mixed layer shallowed, and what that did to
    concentration — against the pristine-atmosphere control.
    """
    r = get_forecast(refresh=refresh)
    if not r.available:
        raise HTTPException(503, detail="forecast unavailable")
    f = r.frame[r.frame["horizon_h"] == r.frame["horizon_h"].min()]
    cols = [c for c in ["aod_coupled", "sw_coupled", "sw_pristine", "sw_reduction_frac",
                        "delta_t_k", "mixing_depth_pristine_m", "mixing_depth_coupled_m",
                        "pbl_suppression_frac", "pm25_uncoupled", "pm25_coupled",
                        "pm_amplification_frac", "coupling_converged",
                        "wind_coupled_ms", "wind_pristine_ms", "wind_reduction_frac",
                        "ventilation_coeff_coupled"] if c in f.columns]
    if not cols:
        raise HTTPException(503, detail="coupling did not run")
    series = f.groupby("time")[cols].mean().reset_index()
    return _clean({"diagnostics": r.coupling, "chain": [
        "PM2.5 -> AOD", "AOD -> shortwave", "shortwave -> temperature",
        "temperature -> boundary layer", "boundary layer -> wind",
        "boundary layer -> PM2.5"],
        "series": series.to_dict("records")})


@app.get("/plume")
def plume_endpoint(refresh: bool = False, days: int = 3):
    """Active stubble fires and the smoke they are sending toward Delhi."""
    r = get_forecast(refresh=refresh)
    fires = plume.fetch_fires(days=days)
    out = {"fires": plume.summarise(fires),
           "detections": [{"lat": f.lat, "lon": f.lon, "frp_mw": f.frp_mw,
                           "when": f.when, "confidence": f.confidence,
                           "source": f.source} for f in fires[:500]]}
    if r.available and "plume_pm25" in r.frame.columns:
        f = r.frame[r.frame["horizon_h"] == r.frame["horizon_h"].min()]
        out["contribution"] = (f.groupby("time")["plume_pm25"].mean()
                                .reset_index().to_dict("records"))
    return _clean(out)


@app.get("/scenario")
def scenario(kind: str = Query("delhi_sector", pattern="^(delhi_sector|district)$")):
    """Policy simulator from the MoES DSS emission-reduction runs.

    Turns a priority ranking into a decision: not "transport is ranked first" but
    "a 20% cut in Delhi transport removes X ug/m3 on an average day". These are the
    DSS's numbers, not ours, and are labelled as such.
    """
    if not dss.available():
        raise HTTPException(503, detail="DSS workbook not available")
    table = dss.scenario_summary()
    if table.empty:
        raise HTTPException(503, detail="scenario sheet empty")
    sub = table[table["target_kind"] == kind].copy()
    # The workbook keys everything by three-letter code. "TRA" and "RDT" mean nothing to
    # a reader; resolve them to the names the mapping in grid.py already holds, and keep
    # the code alongside so a row stays traceable back to the source sheet.
    def label(code: str) -> str:
        if kind == "delhi_sector":
            return grid.DELHI_SECTORS.get(code, code)
        d = grid.BY_CODE.get(code)
        return d.name if d else code
    sub["label"] = sub["target"].map(label)
    return _clean({
        "source": "MoES/IITM WRF-Chem Decision Support System (JAMES)",
        "caveat": ("Model-derived, city-level, Oct 2021 - Feb 2022. Third-party output, "
                   "cited not redistributed. Not our model's result."),
        "kind": kind,
        "targets": sub.to_dict("records"),
    })


@app.get("/dss")
def dss_endpoint():
    """What the MoES DSS workbook contains, and its apportionment shares."""
    if not dss.available():
        raise HTTPException(503, detail="DSS workbook not available")
    ap = dss.apportionment()
    return _clean({**dss.describe(),
                   "mean_shares": ap.mean_shares() if not ap.frame.empty else {}})


def _artefact(name: str):
    """Read a result file written by one of the offline scripts."""
    import json
    path = C.MODELS / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@app.get("/photolysis")
def photolysis_endpoint(refresh: bool = False):
    """Aerosol suppression of photolysis, and the ozone counterfactual it enables.

    Two things that answer different questions. The **series** shows how much ultraviolet
    today's aerosol is removing, hour by hour. The **counterfactual** answers something a
    statistical forecast structurally cannot: what ozone would be under a cleaner
    atmosphere, which is not a condition present in any training data.
    """
    r = get_forecast(refresh=refresh)
    out: dict = {
        "chain": ["AOD -> ultraviolet", "ultraviolet -> photolysis rate",
                  "photolysis rate -> ozone production"],
        "why": ("The aerosol-photolysis pathway reduces ozone by 10-12% in published "
                "experiments, against 1-3% for the radiation-and-boundary-layer route. "
                "It is the dominant mechanism, and it acts on ozone directly."),
        "counterfactual": _artefact("ozone_sensitivity.json"),
    }
    if r.available:
        f = r.frame[r.frame["horizon_h"] == r.frame["horizon_h"].min()]
        cols = [c for c in ("j_no2_clear", "j_no2", "j_no2_pristine", "j_attenuation",
                            "j_no2_ratio", "cams_aod", "solar_zenith_deg")
                if c in f.columns]
        if cols:
            out["series"] = f.groupby("time")[cols].mean().reset_index().to_dict("records")
    return _clean(out)


@app.get("/plume/calibration")
def plume_calibration():
    """How the plume scores against the MoES DSS daily stubble attribution."""
    data = _artefact("plume_calibration_octnov.json")
    if data is None:
        raise HTTPException(404, detail="no calibration yet - run scripts/plume_calibrate.py")
    data["shipped_variant"] = plume.VARIANT
    return _clean(data)


@app.get("/loso")
def loso_endpoint():
    """Leave-one-station-out: does it work where there is no instrument?"""
    data = _artefact("loso.json")
    if data is None:
        raise HTTPException(404, detail="no LOSO yet - run scripts/loso.py")
    return _clean(data)


@app.get("/uncertainty")
def uncertainty_endpoint(horizon: int = 24, refresh: bool = False):
    """Prediction intervals and the probability of breaching each GRAP stage.

    A point forecast sitting just under a threshold tells an official nothing about the
    risk of crossing it, and GRAP stages are what a decision turns on. This returns the
    fitted conditional distribution instead.
    """
    from vayuchakra import uncertainty as unc

    out: dict = {
        "why": ("GRAP stages trigger at AQI 200, 300 and 400. A decision turns on the "
                "probability of crossing one, not on a point estimate near it."),
        "thresholds_ugm3": unc.GRAP_PM25,
        "validation": _artefact("uncertainty_pm25_24h.json") or _artefact("uncertainty.json"),
    }
    head = unc.QuantileHead.load("pm25", horizon)
    if head is None:
        out["live"] = None
        out["note"] = "no quantile head trained yet - run scripts/train_uncertainty.py"
        return _clean(out)

    r = get_forecast(refresh=refresh)
    if not r.available:
        raise HTTPException(503, detail="forecast unavailable")
    f = r.frame[r.frame["horizon_h"] == horizon]
    absent = [c for c in head.features if c not in f.columns]
    if absent:
        out["live"] = None
        out["note"] = (f"{len(absent)} trained features absent on the inference path "
                       f"(first: {', '.join(absent[:4])}) - intervals withheld rather "
                       f"than computed from nulls")
        return _clean(out)

    q = head.predict(f)
    risk = unc.grap_risk(q)
    joined = pd.concat([f[["time", "cell_id"]].reset_index(drop=True),
                        q.reset_index(drop=True), risk.reset_index(drop=True)], axis=1)
    city = joined.groupby("time").mean(numeric_only=True).reset_index()
    out["live"] = {"horizon_h": horizon, "series": city.to_dict("records")}
    return _clean(out)


@app.get("/profile")
def profile(cell_id: int | None = None, refresh: bool = False):
    """Vertical structure over time: the cross-section a forecaster actually reads.

    Everything else in this system reports a surface number. The problem statement is
    about what happens ABOVE the surface, and until now that was only ever shown as a
    flat line. This returns the temperature profile at each usable pressure level
    together with the mixing depth and the inversion lid, so the lid can be drawn as a
    surface in time and height rather than described in a caption.

    Heights are above ground, not above sea level. 1000 hPa is excluded because over
    Delhi it sits below the terrain (D-009), and a level underground carries no
    information about the air above it.
    """
    r = get_forecast(refresh=refresh)
    if not r.available:
        raise HTTPException(503, detail="forecast unavailable")
    f = r.frame[r.frame["horizon_h"] == r.frame["horizon_h"].min()]
    if cell_id is not None:
        f = f[f["cell_id"] == cell_id]
        if f.empty:
            raise HTTPException(404, detail=f"no cell {cell_id}")

    levels = []
    for name in ("950", "925", "850"):
        z, t = f"z_{name}", f"t_{name}"
        if z in f.columns and t in f.columns and f[z].notna().any():
            levels.append({"pressure_hpa": float(name),
                           "height_col": z, "temp_col": t})

    cols = ["temperature_2m", "mixing_depth_m", "inversion_lid_m",
            "inversion_strength_k", "boundary_layer_height", "is_inversion",
            "shortwave_radiation"]
    cols += [c for lv in levels for c in (lv["height_col"], lv["temp_col"])]
    cols = [c for c in cols if c in f.columns]
    series = f.groupby("time")[cols].mean().reset_index()

    return _clean({
        "scope": f"cell {cell_id}" if cell_id is not None else "domain mean",
        "levels": [{"pressure_hpa": lv["pressure_hpa"],
                    "height": lv["height_col"], "temp": lv["temp_col"]}
                   for lv in levels],
        "surface_height_m": 2.0,
        "note": ("Heights are metres above ground. The 1000 hPa surface is excluded "
                 "because over Delhi it lies below the terrain, so its temperature is a "
                 "downward extrapolation that reads several degrees too warm at night."),
        "series": series.to_dict("records"),
    })


@app.get("/domain")
def domain(refresh: bool = False):
    """The whole modelled region, not just the city.

    The forecast covers 1,120 cells across NCR and the transport that matters starts
    250 km upwind, in Punjab and Haryana. A Delhi-only view cannot show smoke arriving
    from outside the city, which is the mechanism the problem statement asks about.
    """
    cells = grid.build_grid()
    fires = plume.fetch_fires(days=3)
    return _clean({
        "bounds": {"lat": [C.LAT_MIN, C.LAT_MAX], "lon": [C.LON_MIN, C.LON_MAX]},
        "delhi_box": {"lat": [grid.DELHI_BOX[0], grid.DELHI_BOX[1]],
                      "lon": [grid.DELHI_BOX[2], grid.DELHI_BOX[3]]},
        "stubble_bbox": {"lon": [plume.STUBBLE_BBOX[0], plume.STUBBLE_BBOX[2]],
                         "lat": [plume.STUBBLE_BBOX[1], plume.STUBBLE_BBOX[3]]},
        "delhi": {"lat": C.DELHI_LAT, "lon": C.DELHI_LON},
        "districts": [{"code": d.code, "name": d.name, "lat": d.lat, "lon": d.lon,
                       "state": d.state} for d in grid.DISTRICTS],
        "cells": [{"lat": c.lat, "lon": c.lon, "tier": c.tier} for c in cells],
        "fires": [{"lat": f.lat, "lon": f.lon, "frp_mw": f.frp_mw,
                   "confidence": f.confidence} for f in fires[:1500]],
        "fire_summary": plume.summarise(fires),
    })


@app.get("/validation")
def validation():
    """Stored training metrics for the models this API is actually serving.

    It used to read models/metrics.json unconditionally, and that went wrong the moment
    a second configuration existed. The multi-winter run writes its scores to
    metrics_multiwinter.json while its boosters land in models/ as the shipped ones, so
    the endpoint reported the single-winter recency split beside predictions from a
    four-winter model: PM2.5 +18.0% on screen for a head that scores +19.2% on a winter
    it never saw, and a row count and split that described neither.

    So the metrics file is chosen by matching the panel recorded in the shipped model's
    own metadata, which is written at fit time and cannot drift from the booster it
    describes.
    """
    import json
    metrics = sorted(C.MODELS.glob("metrics*.json"))
    if not metrics:
        raise HTTPException(404, detail="no metrics yet - run scripts/train.py")

    # The panel is recorded inside config_note, as "panel=X; chem=Y; inversion=Z".
    shipped = None
    for meta in sorted(C.MODELS.glob("*.meta.json")):
        try:
            note = json.loads(meta.read_text(encoding="utf-8")).get("config_note", "")
        except Exception:
            continue
        for part in str(note).split(";"):
            if part.strip().startswith("panel="):
                shipped = part.strip()[len("panel="):].strip()
                break
        if shipped:
            break

    chosen, why = None, "only one metrics file"
    if shipped:
        for path in metrics:
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if d.get("panel") == shipped:
                chosen, why = path, f"matches the shipped models, which were fit on {shipped}"
                break
    if chosen is None:
        chosen = C.MODELS / "metrics.json"
        if not chosen.exists():
            chosen = max(metrics, key=lambda q: q.stat().st_mtime)
        why = ("no metrics file records the panel the shipped models were fit on; "
               "showing the most recent, which may not describe them")

    out = json.loads(chosen.read_text(encoding="utf-8"))
    out["metrics_file"] = chosen.name
    out["metrics_source"] = why
    return _clean(out)
