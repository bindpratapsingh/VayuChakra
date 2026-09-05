"""Validation — the two questions that decide whether any of this is worth anything.

**Does the coupling help?** The problem statement asserts that ignoring the
meteorology-chemistry feedback "leads to significant inaccuracies". We can test that
assertion rather than repeat it: run the identical forecast with the feedback loop on
and off and score both against the same observations. If coupled wins, we have
demonstrated the premise with a number. If it does not, we say so and report the
regimes where it does — a clean negative result is still a result, and far better than
an unmeasured claim.

**How does it compare with the system the ministry already runs?** The MoES DSS
forecast archive covers Oct 2021 - Feb 2022 at Day 1-5 lead times. 66 Delhi-area
stations cover the same window. So all three — VayuChakra, the DSS, and persistence —
can be scored against the *same* observations over the *same* hours. That is a genuine
head-to-head rather than two numbers quoted side by side.

FAIRNESS RULES, FIXED BEFORE ANY NUMBER WAS COMPUTED
-----------------------------------------------------
* Same ground truth for everyone: the Delhi city-mean of the same stations, since the
  DSS series is city-level and we must not compare a city number against a ward number.
* Same hours for everyone: only hours where all three produce a value.
* The DSS is scored at the lead it was issued for — Day 1 against +24 h, not against
  our best horizon.
* Our model runs in the **reduced configuration** for that window, because CAMS has no
  coverage before mid-August 2022. Stated every time the number is quoted.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C
from . import chem_prior, dataset, dss, feedback, grid, indices, met, model, obs


def _rmse(a, b) -> float:
    a, b = np.asarray(a, dtype="float64"), np.asarray(b, dtype="float64")
    ok = np.isfinite(a) & np.isfinite(b)
    return float(np.sqrt(np.mean((a[ok] - b[ok]) ** 2))) if ok.any() else float("nan")


def _mae(a, b) -> float:
    a, b = np.asarray(a, dtype="float64"), np.asarray(b, dtype="float64")
    ok = np.isfinite(a) & np.isfinite(b)
    return float(np.mean(np.abs(a[ok] - b[ok]))) if ok.any() else float("nan")


def _corr(a, b) -> float:
    a, b = np.asarray(a, dtype="float64"), np.asarray(b, dtype="float64")
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 3:
        return float("nan")
    return float(np.corrcoef(a[ok], b[ok])[0, 1])


def city_mean_observations(start: str, end: str, max_stations: int = 25,
                           radius_km: float = 40.0) -> pd.DataFrame:
    """Delhi city-mean hourly PM2.5 — the common ground truth.

    A city mean rather than a single station, because the DSS series is a city-level
    product and one station is not a city. Restricted to a radius around the centre so
    the "city" being averaged is Delhi and not the whole NCR.
    """
    stations = obs.discover_stations()
    near = [s for s in stations
            if grid.haversine_km(s.lat, s.lon, C.DELHI_LAT, C.DELHI_LON) <= radius_km
            and "pm25" in s.sensors]
    if not near:
        return pd.DataFrame()

    years = {int(start[:4]), int(end[:4])}
    usable = []
    for s in near:
        if years.issubset(set(obs.archive_years(s.id))):
            usable.append(s)
        if len(usable) >= max_stations:
            break
    if not usable:
        print(f"[validate] no stations with archive coverage for {sorted(years)}")
        return pd.DataFrame()

    raw = obs.fetch_archive([s.id for s in usable], start, end)
    if raw.empty:
        return pd.DataFrame()
    city = (raw.groupby("time")
               .agg(obs_pm25=("pm25", "mean"), n_stations=("pm25", "count"))
               .reset_index())
    # An "average" over two stations is not a city mean; require a quorum.
    city = city[city["n_stations"] >= 3]
    print(f"[validate] city-mean truth: {len(city):,} hours from {len(usable)} stations")
    return city


def hindcast(start: str, end: str, *, max_stations: int = 25,
             with_chem: bool | None = None, model_dir=None,
             met_source: str = "era5") -> pd.DataFrame:
    """Run our model over a past window, at the Delhi city level.

    `with_chem=None` decides automatically from the CAMS coverage boundary rather than
    letting a caller silently request a chemistry prior that does not exist.
    """
    if with_chem is None:
        with_chem = start >= chem_prior.ARCHIVE_START
    stations = obs.discover_stations()
    years = {int(start[:4]), int(end[:4])}
    near = sorted((s for s in stations if "pm25" in s.sensors),
                  key=lambda s: grid.haversine_km(s.lat, s.lon, C.DELHI_LAT, C.DELHI_LON))
    usable = []
    for s in near:
        if grid.haversine_km(s.lat, s.lon, C.DELHI_LAT, C.DELHI_LON) > 40:
            break
        if years.issubset(set(obs.archive_years(s.id))):
            usable.append(s)
        if len(usable) >= max_stations:
            break
    if not usable:
        return pd.DataFrame()

    # The cache name carries the met source. Without it the ERA5 panel and the
    # archived-forecast panel would collide on one file, and the second run would
    # silently score the first run's meteorology.
    suffix = "" if met_source == "era5" else f"_{met_source}"
    panel = dataset.build_panel(usable, start, end, with_chem=with_chem,
                                met_source=met_source,
                                cache_name=f"hindcast_{start}_{end}{suffix}")
    if panel.empty:
        return pd.DataFrame()

    frames = []
    for horizon in C.HORIZONS_H:
        sup = dataset.make_supervised(panel, horizon, "pm25")
        if sup.empty:
            continue
        head = model.Head.load("pm25", horizon, model_dir)
        if head is None:
            continue
        for col in head.features:
            if col not in sup.columns:
                sup[col] = np.nan
        sup["pred_pm25"] = head.predict(sup)
        sup["valid_time"] = sup["time"] + pd.Timedelta(hours=horizon)
        sup["lead_hours"] = horizon
        frames.append(sup[["valid_time", "lead_hours", "station_id",
                           "pred_pm25", "y", "pm25_lag_1h"]])
    if not frames:
        return pd.DataFrame()

    allf = pd.concat(frames, ignore_index=True)
    return (allf.groupby(["valid_time", "lead_hours"])
                .agg(pred_pm25=("pred_pm25", "mean"),
                     obs_pm25=("y", "mean"),
                     persistence=("pm25_lag_1h", "mean"),
                     n=("pred_pm25", "count"))
                .reset_index())


def dss_head_to_head(start: str = "2021-10-06", end: str = "2022-02-28",
                     model_dir=None, met_source: str = "era5") -> dict:
    """Score VayuChakra, the MoES DSS and persistence on identical hours.

    `met_source="archived_forecast"` is the fair version of this comparison: our
    hindcast is then driven by the forecast runs as they were issued rather than by
    reanalysis, so it carries meteorological error the way an operational system does.
    """
    if not dss.available():
        return {"available": False, "reason": "DSS workbook not found"}

    dss_f = dss.forecast_as_valid_time()
    if dss_f.empty:
        return {"available": False, "reason": "DSS forecast sheet empty"}

    truth = city_mean_observations(start, end)
    if truth.empty:
        return {"available": False,
                "reason": "no observations with archive coverage for this window"}

    ours = hindcast(start, end, model_dir=model_dir, met_source=met_source)

    out = {"available": True,
           "window": {"from": start, "to": end},
           "configuration": ("reduced - no chemistry prior; CAMS coverage begins "
                             f"{chem_prior.ARCHIVE_START}, after this window"),
           "ground_truth": "Delhi city-mean hourly PM2.5 from CPCB stations",
           "citation": ("MoES/IITM WRF-Chem Decision Support System (JAMES). "
                        "Third-party output, cited not redistributed."),
           "met_source": met_source,
           # The single most important caveat on this table, stated before the numbers
           # rather than after them - and it is a DIFFERENT caveat depending on which
           # meteorology drove the hindcast. Hard-coding the reanalysis wording would
           # have kept claiming an advantage we had just removed.
           "not_like_for_like": (
               "The DSS forecasts were issued OPERATIONALLY: it had to predict the "
               "weather as well as the chemistry, days ahead. Our hindcast is driven by "
               "ERA5 REANALYSIS - the meteorology as it actually turned out. That is a "
               "material advantage and it is not a fair comparison of forecast skill. "
               "What this table supports is that the statistical layer maps meteorology "
               "to PM2.5 competitively; it does NOT show we forecast better than the "
               "MoES DSS."
               if met_source == "era5" else
               "Our hindcast is driven by ARCHIVED FORECAST RUNS, not reanalysis, so it "
               "carries meteorological error the way an operational system does. That "
               "removes most of the advantage the ERA5 version had, but NOT all of it: "
               "the archive holds the best available run for each hour, which is a short "
               "lead time, while the DSS was scored 24 to 72 hours ahead. Boundary layer "
               "height alone is still backfilled from ERA5, because the forecast archive "
               "does not serve it. The residue is in our favour and is named here rather "
               "than left for a reader to discover."),
           "our_models_trained_on": ("Feb 2025 - Aug 2026, so this window is genuinely "
                                     "out of sample in time."),
           "by_lead": []}

    truth = truth.rename(columns={"time": "valid_time"})
    for lead in sorted(dss_f["lead_hours"].unique()):
        d = dss_f[dss_f["lead_hours"] == lead].merge(truth, on="valid_time", how="inner")
        if d.empty:
            continue
        row = {"lead_hours": int(lead), "n_hours": int(len(d)),
               "dss": {"rmse": round(_rmse(d["dss_pm25"], d["obs_pm25"]), 2),
                       "mae": round(_mae(d["dss_pm25"], d["obs_pm25"]), 2),
                       "corr": round(_corr(d["dss_pm25"], d["obs_pm25"]), 3),
                       "bias": round(float(np.nanmean(d["dss_pm25"] - d["obs_pm25"])), 2)}}

        if not ours.empty:
            o = ours[ours["lead_hours"] == lead]
            common = d.merge(o, on="valid_time", how="inner", suffixes=("", "_v"))
            if not common.empty:
                row["n_common"] = int(len(common))
                row["vayuchakra"] = {
                    "rmse": round(_rmse(common["pred_pm25"], common["obs_pm25"]), 2),
                    "mae": round(_mae(common["pred_pm25"], common["obs_pm25"]), 2),
                    "corr": round(_corr(common["pred_pm25"], common["obs_pm25"]), 3),
                    "bias": round(float(np.nanmean(common["pred_pm25"] - common["obs_pm25"])), 2)}
                row["persistence"] = {
                    "rmse": round(_rmse(common["persistence"], common["obs_pm25"]), 2)}
                # Re-score the DSS on exactly the shared hours, so the comparison is
                # like-for-like rather than two numbers from different samples.
                row["dss_on_common_hours"] = {
                    "rmse": round(_rmse(common["dss_pm25"], common["obs_pm25"]), 2)}
        out["by_lead"].append(row)
    return out


def coupling_ablation(start: str, end: str, *, max_stations: int = 20) -> dict:
    """Coupled vs uncoupled on the same hours — the problem statement's own premise.

    Runs the feedback solver over a hindcast window and compares both states against
    observations. Also reports by regime, because the honest expectation is that the
    feedback helps on stagnant high-aerosol days and does nothing on windy clean ones —
    and an overall average would hide both facts.
    """
    stations = obs.discover_stations()
    years = {int(start[:4]), int(end[:4])}
    near = sorted((s for s in stations if "pm25" in s.sensors),
                  key=lambda s: grid.haversine_km(s.lat, s.lon, C.DELHI_LAT, C.DELHI_LON))
    usable = [s for s in near[:80]
              if grid.haversine_km(s.lat, s.lon, C.DELHI_LAT, C.DELHI_LON) <= 40
              and years.issubset(set(obs.archive_years(s.id)))][:max_stations]
    if not usable:
        return {"available": False, "reason": "no stations with coverage"}

    panel = dataset.build_panel(usable, start, end, with_chem=True,
                                cache_name=f"ablation_{start}_{end}")
    # These are different failures and must not share a message. An HTTP 502 on the
    # meteorology fetch once produced an empty panel, which this reported as "chemistry
    # prior unavailable" — sending the diagnosis in entirely the wrong direction.
    if panel.empty:
        return {"available": False,
                "reason": "empty panel - observations or meteorology could not be assembled"}
    if "cams_pm25" not in panel.columns:
        return {"available": False,
                "reason": "chemistry prior unavailable - the coupling needs an AOD baseline"}

    work = panel.dropna(subset=["pm25", "cams_pm25", "mixing_depth_m",
                                "shortwave_radiation"]).copy()
    if work.empty:
        return {"available": False, "reason": "no complete rows"}
    work = work.rename(columns={"station_id": "cell_id"})

    # The uncoupled state is the CAMS prior corrected only by a constant bias - the
    # simplest thing that isolates the FEEDBACK as the only difference between the two
    # runs. Anything cleverer would confound the ablation with model skill.
    bias = float((work["pm25"] - work["cams_pm25"]).mean())
    work["pm25_uncoupled"] = work["cams_pm25"] + bias

    aod_model = feedback.calibrate_aod(work)
    res = feedback.solve(work, aod_model=aod_model)
    f = res.frame

    # --- make the comparison fair -------------------------------------------
    # The uncoupled arm is CAMS plus a fitted bias, so its mean error is zero BY
    # CONSTRUCTION. The coupled arm is that same series multiplied by roughly 1.075,
    # which therefore *must* come out biased high — and it did, by +4.21 µg/m³. Scoring
    # them against each other that way does not test the feedback; it tests which arm
    # was allowed to fit an intercept.
    #
    # Both arms are re-centred to zero mean bias before scoring. What survives is the
    # only thing the ablation should be asking: does the feedback improve the SHAPE and
    # TIMING of the prediction, independent of its level?
    def _recentre(pred: pd.Series) -> pd.Series:
        return pred - float(np.nanmean(pred - f["pm25"]))

    unc_c = _recentre(f["pm25_uncoupled"])
    cpl_c = _recentre(f["pm25_coupled"])

    overall = {
        "uncoupled_rmse": round(_rmse(unc_c, f["pm25"]), 2),
        "coupled_rmse": round(_rmse(cpl_c, f["pm25"]), 2),
        "uncoupled_bias": round(float(np.nanmean(f["pm25_uncoupled"] - f["pm25"])), 2),
        "coupled_bias": round(float(np.nanmean(f["pm25_coupled"] - f["pm25"])), 2),
        "scoring": ("both arms re-centred to zero mean bias, so this measures shape and "
                    "timing rather than which arm was allowed to fit an intercept"),
        "n": int(len(f)),
    }
    overall["rmse_improvement_pct"] = round(
        100.0 * (overall["uncoupled_rmse"] - overall["coupled_rmse"])
        / overall["uncoupled_rmse"], 2) if overall["uncoupled_rmse"] > 0 else float("nan")

    regimes = {}
    if "is_episode" in f.columns:
        for label, mask in (("stagnant_episode", f["is_episode"] == 1),
                            ("well_ventilated", f["is_episode"] == 0)):
            sub = f[mask]
            if len(sub) < 50:
                continue
            u = _rmse(sub["pm25_uncoupled"] - float(np.nanmean(sub["pm25_uncoupled"] - sub["pm25"])), sub["pm25"])
            c = _rmse(sub["pm25_coupled"] - float(np.nanmean(sub["pm25_coupled"] - sub["pm25"])), sub["pm25"])
            regimes[label] = {"n": int(len(sub)), "uncoupled_rmse": round(u, 2),
                              "coupled_rmse": round(c, 2),
                              "improvement_pct": round(100 * (u - c) / u, 2) if u > 0 else None}
    high_aod = f[pd.to_numeric(f.get("aod_coupled"), errors="coerce") >= feedback.GATE_MIN_AOD]
    if len(high_aod) >= 50:
        u = _rmse(high_aod["pm25_uncoupled"] - float(np.nanmean(high_aod["pm25_uncoupled"] - high_aod["pm25"])), high_aod["pm25"])
        c = _rmse(high_aod["pm25_coupled"] - float(np.nanmean(high_aod["pm25_coupled"] - high_aod["pm25"])), high_aod["pm25"])
        regimes["high_aerosol"] = {"n": int(len(high_aod)), "uncoupled_rmse": round(u, 2),
                                   "coupled_rmse": round(c, 2),
                                   "improvement_pct": round(100 * (u - c) / u, 2) if u > 0 else None}

    return {"available": True, "window": {"from": start, "to": end},
            "overall": overall, "by_regime": regimes,
            "coupling": res.summary(),
            "literature_gate": feedback.check_against_literature(res),
            "note": ("Uncoupled baseline is the bias-corrected CAMS prior, so the ONLY "
                     "difference between the two runs is the radiative feedback.")}
