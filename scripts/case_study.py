"""Replay a past stubble-burning episode and test the plume model against observations.

Run:  python scripts/case_study.py [--start 2021-11-05] [--days 4]

Off-season the plume model correctly reports almost nothing, which demonstrates that it
is honest but not that it works. This replays a real episode with archived satellite
detections and archived meteorology, and asks a question with a falsifiable answer:

    does modelled plume arrival line up with the observed PM2.5 spike?

The default window is 5-8 November 2021, three days after Diwali, in the middle of the
paddy-burning season. Our own pulled observations put the Delhi city mean at 414 µg/m³
on 4 November and still above 300 on the 5th and 6th.

**This is a hindcast, and it is labelled as one wherever its numbers are quoted.**
Everything it uses - fire detections, meteorology, observations - is archived. It shows
the mechanism working on a real case; it is not evidence about forecast skill.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vayuchakra import config as C                          # noqa: E402
from vayuchakra import dataset, grid, indices, met, obs, plume  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2021-11-05")
    ap.add_argument("--days", type=int, default=4)
    ap.add_argument("--out", default="case_study.json")
    args = ap.parse_args()

    end = (pd.Timestamp(args.start) + pd.Timedelta(days=args.days - 1)).strftime("%Y-%m-%d")
    print(f"[case] replaying {args.start} -> {end}")

    # --- fires from the archive ------------------------------------------
    fires = plume.fetch_fires(days=args.days, start=args.start)
    if not fires:
        print("[case] no archived detections returned - cannot run the case study")
        return 1
    summary = plume.summarise(fires)
    print(f"[case] {summary['n_fires']:,} detections, {summary['total_frp_mw']:,.0f} MW total, "
          f"mean {summary['mean_distance_km']:.0f} km from Delhi")

    # --- meteorology over Delhi and the transport corridor ---------------
    # Delhi at full resolution, plus every coarse NCR cell as the transport corridor.
    # The fine Delhi tier is thinned to every third cell: the puff model reads wind by
    # nearest neighbour, so 2.8 km spacing buys nothing over 8 km for advection and
    # triples the request count straight into Open-Meteo's archive rate limit.
    full = grid.build_grid()
    corridor = [c for c in full if c.tier == "ncr"]
    corridor += [c for i, c in enumerate(x for x in full if x.tier == "delhi") if i % 3 == 0]
    print(f"[case] meteorology for {len(corridor)} cells")
    m = met.fetch_archive(corridor, args.start, end)
    if m.frame.empty:
        print("[case] no archived meteorology")
        return 1
    grid_met = dataset.add_wind_components(indices.enrich(m.frame))

    # --- run the plume ---------------------------------------------------
    delhi = [c for c in corridor if c.tier == "delhi"]
    t0 = pd.Timestamp(args.start, tz="UTC")
    print(f"[case] advecting {len(fires):,} parcels over {args.days * 24} hours ...")
    pl = plume.run(fires, grid_met, delhi, hours=args.days * 24, start=t0)
    if pl.empty:
        print("[case] plume produced no rows")
        return 1
    modelled = (pl.groupby("time")
                  .agg(plume_pm25=("plume_pm25", "mean"),
                       mixing_depth_m=("mixing_depth_m", "mean"),
                       n_puffs=("n_puffs", "max"))
                  .reset_index())

    # --- observations ----------------------------------------------------
    stations = obs.discover_stations()
    years = {int(args.start[:4])}
    near = sorted((s for s in stations if "pm25" in s.sensors),
                  key=lambda s: grid.haversine_km(s.lat, s.lon, C.DELHI_LAT, C.DELHI_LON))
    usable = []
    for s in near:
        if grid.haversine_km(s.lat, s.lon, C.DELHI_LAT, C.DELHI_LON) > 40:
            break
        if years.issubset(set(obs.archive_years(s.id))):
            usable.append(s)
        if len(usable) >= 12:
            break
    observed = pd.DataFrame()
    if usable:
        raw = obs.fetch_archive([s.id for s in usable], args.start, end)
        if not raw.empty:
            observed = (raw.groupby("time")
                           .agg(obs_pm25=("pm25", "mean"), n=("pm25", "count"))
                           .reset_index())
            observed = observed[observed["n"] >= 3]
    print(f"[case] observations from {len(usable)} stations, {len(observed)} hours")

    joined = modelled.merge(observed, on="time", how="inner") if not observed.empty else modelled
    if "obs_pm25" not in joined.columns or joined.empty:
        print("[case] no overlapping observations - reporting the modelled series only")
        report = {"available": True, "window": [args.start, end], "fires": summary,
                  "observed": False,
                  "modelled_peak_ugm3": round(float(modelled["plume_pm25"].max()), 2)}
    else:
        # Two correlations, because the raw one is not the meaningful test.
        #
        # Transported smoke is an ADDITIVE minority term. Total observed PM2.5 is
        # dominated by local emissions divided by the mixing depth, which swings by an
        # order of magnitude every night. Correlating a few µg/m³ of plume against that
        # mostly measures whether the plume happens to share a diurnal cycle with the
        # boundary layer, and would look weak even for a perfect plume model.
        #
        # The informative test regresses out the dominant local driver first (1/mixing
        # depth, the box-model term) and asks whether the plume explains any of what is
        # LEFT. Both are reported; only the residual one is evidence about transport.
        def _best_lag(target: pd.Series) -> tuple[int, float]:
            best_l, best_val = 0, float("nan")
            for lag in range(-12, 13):
                shifted = joined["plume_pm25"].shift(lag)
                ok = shifted.notna() & target.notna()
                if ok.sum() < 12:
                    continue
                if shifted[ok].std() < 1e-9 or target[ok].std() < 1e-9:
                    continue
                r = float(np.corrcoef(shifted[ok], target[ok])[0, 1])
                if not np.isnan(r) and (np.isnan(best_val) or r > best_val):
                    best_l, best_val = lag, r
            return best_l, best_val

        best_lag, best_r = _best_lag(joined["obs_pm25"])

        inv_depth = 1.0 / joined["mixing_depth_m"].clip(lower=C.MIN_PBL_M)
        ok = inv_depth.notna() & joined["obs_pm25"].notna()
        residual = pd.Series(np.nan, index=joined.index)
        if ok.sum() > 12 and inv_depth[ok].std() > 1e-9:
            A = np.column_stack([np.ones(ok.sum()), inv_depth[ok].to_numpy()])
            coef, *_ = np.linalg.lstsq(A, joined["obs_pm25"][ok].to_numpy(), rcond=None)
            residual.loc[ok] = joined["obs_pm25"][ok].to_numpy() - A @ coef
        res_lag, res_r = _best_lag(residual)

        peak_model = joined.loc[joined["plume_pm25"].idxmax(), "time"]
        peak_obs = joined.loc[joined["obs_pm25"].idxmax(), "time"]
        report = {
            "available": True, "observed": True,
            "window": [args.start, end],
            "fires": summary,
            "hours_compared": int(len(joined)),
            "modelled_peak_ugm3": round(float(joined["plume_pm25"].max()), 2),
            "observed_peak_ugm3": round(float(joined["obs_pm25"].max()), 1),
            "observed_mean_ugm3": round(float(joined["obs_pm25"].mean()), 1),
            "peak_model_at": str(peak_model),
            "peak_obs_at": str(peak_obs),
            "peak_lead_hours": round((peak_obs - peak_model).total_seconds() / 3600, 1),
            "corr_vs_total_pm25": round(best_r, 3),
            "corr_vs_total_lag_h": best_lag,
            "corr_vs_residual": round(res_r, 3) if res_r == res_r else None,
            "corr_vs_residual_lag_h": res_lag,
            "residual_note": ("Residual = observed PM2.5 after regressing out 1/mixing "
                              "depth, the dominant local driver. This is the informative "
                              "test; the raw correlation is reported for completeness."),
            "mean_mixing_depth_m": round(float(joined["mixing_depth_m"].mean()), 0),
            "caveat": ("Hindcast. Archived fire detections, archived meteorology, archived "
                       "observations. Demonstrates the transport mechanism on a real "
                       "episode; says nothing about forecast skill."),
        }
        print()
        print(f"  observed peak      {report['observed_peak_ugm3']:>8.1f} µg/m³ at {peak_obs}")
        print(f"  modelled plume max {report['modelled_peak_ugm3']:>8.2f} µg/m³ at {peak_model}")
        print(f"  peak lead          {report['peak_lead_hours']:>8.1f} h "
              f"(positive = plume arrives before the spike)")
        print(f"  corr vs total      {report['corr_vs_total_pm25']:>8.3f} at lag "
              f"{report['corr_vs_total_lag_h']} h   (weak by construction)")
        rr = report['corr_vs_residual']
        print(f"  corr vs residual   {rr if rr is None else format(rr, '8.3f')} at lag "
              f"{report['corr_vs_residual_lag_h']} h   <-- the informative one")
        print(f"  mean mixing depth  {report['mean_mixing_depth_m']:>8.0f} m")

    out = C.MODELS / args.out
    series = joined.copy()
    series["time"] = series["time"].astype(str)
    report["series"] = series.to_dict("records")
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\n[case] written -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
