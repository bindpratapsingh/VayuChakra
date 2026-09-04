"""Calibrate the stubble plume against the MoES DSS attribution.

Run:  python scripts/plume_calibrate.py [--start 2021-10-06] [--end 2022-02-28]
                                        [--quick] [--variants A,B,C]

WHAT THIS FIXES
---------------
Round 1 tested the plume against one four-day episode and got a weak, slightly negative
correlation against *total* observed PM2.5. That was the wrong comparison: transported
smoke is an additive minority term, and total PM2.5 is dominated by local emissions
divided by the mixing depth.

The DSS workbook contains something far better — a **daily stubble-burning attribution
in µg/m³ for 147 days**, from the operational system the ministry runs. Season mean
8.6 µg/m³ (8.8% of PM2.5), peaking at 38.0 µg/m³ (39%) on 7 November 2021. That turns
plume calibration from guesswork into fitting against a reference.

WHAT IS FITTED, AND WHAT IS NOT
-------------------------------
**One multiplicative scale factor**, and nothing else about the magnitude. That factor
absorbs genuinely uncertain emission terms: PM2.5 emission factors for cereal straw span
5-8 g/kg, satellites miss fires under cloud and below the detection limit, and each
detection is credited with one hour of burning when the real duration varies. Fitting a
single scale for that bundle is honest; tuning the physics until the answer looks right
would not be.

**Correlation is therefore the real test**, because the scale factor cannot improve it.
If a variant's timing is wrong, no amount of scaling saves it — which is exactly the
property needed to choose between the three physics variants on evidence.

THE VARIANTS
------------
A  injection height fixed forever          - smoke above a nocturnal lid never lands
B  entrained, no residual layer            - all entrained smoke rides the layer down
C  entrained WITH residual layer (current) - only current_depth/mixed_depth stays coupled
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vayuchakra import config as C                        # noqa: E402
from vayuchakra import dataset, dss, grid, indices, met, plume  # noqa: E402


def corridor_cells() -> list[grid.Cell]:
    """Coarse NCR plus a thinned Delhi tier — enough for nearest-neighbour wind."""
    full = grid.build_grid()
    cells = [c for c in full if c.tier == "ncr"]
    cells += [c for i, c in enumerate(x for x in full if x.tier == "delhi") if i % 3 == 0]
    return cells


def fetch_season_fires(start: str, end: str, chunk_days: int = 4) -> list[plume.Fire]:
    """FIRMS archive in small blocks, halving whenever a request comes back empty.

    The documented per-request maximum is 10 days, but that is not the binding limit
    during the burning season — it is response SIZE. Measured against the stubble bbox:
    a 4-day window on 5 Nov 2021 returns 24,004 detections and succeeds, while 7- and
    10-day windows on the same dates fail outright. A fixed 10-day loop silently
    returned zero fires for the entire season.

    So blocks start small and halve on failure. A genuinely quiet stretch and a
    too-large request are indistinguishable from one empty response, and halving
    resolves the ambiguity rather than assuming the optimistic reading.
    """
    fires: list[plume.Fire] = []
    day = pd.Timestamp(start)
    last = pd.Timestamp(end)
    while day <= last:
        span = min(chunk_days, (last - day).days + 1)
        got: list[plume.Fire] = []
        while span >= 1:
            got = plume.fetch_fires(days=span, start=day.strftime("%Y-%m-%d"))
            if got or span == 1:
                break
            span = max(1, span // 2)
            print(f"[calib]   empty at {span * 2}d, retrying {day:%Y-%m-%d} at {span}d",
                  flush=True)
        fires.extend(got)
        print(f"[calib]   {day:%Y-%m-%d} +{span}d -> {len(got):,} detections "
              f"({len(fires):,} total)", flush=True)
        day += pd.Timedelta(days=span)
    return fires


def apply_variant(name: str) -> None:
    """Switch the plume module between the three physics treatments.

    Implemented as module-level flags rather than three code paths, so the variants
    differ only in the one mechanism under test and cannot drift apart in anything else.
    """
    plume.VARIANT = name


def run_month(fires: list[plume.Fire], grid_met: pd.DataFrame,
              cells: list[grid.Cell], month_start: pd.Timestamp,
              month_end: pd.Timestamp) -> pd.DataFrame:
    """Advect one month. Chunking bounds the puff population and the memory it needs."""
    window = [f for f in fires
              if month_start - pd.Timedelta(days=2) <= f.when <= month_end]
    if not window:
        return pd.DataFrame()
    hours = int((month_end - month_start).total_seconds() // 3600) + 1
    out = plume.run(window, grid_met, cells, hours=hours,
                    start=month_start - pd.Timedelta(days=2))
    if out.empty:
        return out
    return out[(out["time"] >= month_start) & (out["time"] <= month_end)]


def score(daily: pd.DataFrame, target: pd.DataFrame) -> dict:
    """Compare a modelled daily series against the DSS stubble attribution.

    The scale factor is fitted by least squares through the origin — a plume of zero
    smoke must contribute zero, so an intercept would be unphysical.
    """
    j = daily.merge(target, on="date", how="inner").dropna(
        subset=["plume_pm25", "dss_stubble"])
    if len(j) < 20:
        return {"available": False, "n": int(len(j))}

    x = j["plume_pm25"].to_numpy(dtype="float64")
    y = j["dss_stubble"].to_numpy(dtype="float64")
    scale = float(np.sum(x * y) / np.sum(x * x)) if np.sum(x * x) > 0 else float("nan")
    fitted = x * scale

    r = float(np.corrcoef(x, y)[0, 1]) if x.std() > 0 and y.std() > 0 else float("nan")
    rmse = float(np.sqrt(np.mean((fitted - y) ** 2)))
    return {
        "available": True,
        "n_days": int(len(j)),
        "correlation": round(r, 3),
        "scale_factor": round(scale, 4),
        "rmse_after_scaling": round(rmse, 2),
        "modelled_peak_raw": round(float(x.max()), 3),
        "modelled_peak_scaled": round(float(fitted.max()), 2),
        "dss_peak": round(float(y.max()), 2),
        "modelled_mean_scaled": round(float(fitted.mean()), 2),
        "dss_mean": round(float(y.mean()), 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2021-10-06")
    ap.add_argument("--end", default="2022-02-28")
    ap.add_argument("--variants", default="A,B,C")
    ap.add_argument("--quick", action="store_true",
                    help="Oct-Nov only, the season that actually contains the burning")
    ap.add_argument("--out", default="plume_calibration.json")
    args = ap.parse_args()

    end = "2021-11-30" if args.quick else args.end
    print(f"[calib] window {args.start} -> {end}")

    # --- the target -------------------------------------------------------
    ap_frame = dss.apportionment().frame
    if ap_frame.empty or "stubble_burning" not in ap_frame.columns:
        print("[calib] DSS apportionment unavailable - nothing to calibrate against")
        return 1
    target = pd.DataFrame({
        "date": pd.to_datetime(ap_frame["date"]).dt.date,
        "dss_stubble": pd.to_numeric(ap_frame["stubble_burning"], errors="coerce"),
    }).dropna()
    print(f"[calib] DSS target: {len(target)} days, mean {target.dss_stubble.mean():.1f}, "
          f"peak {target.dss_stubble.max():.1f} ug/m3")

    # --- inputs, fetched once and reused across every variant -------------
    t0 = time.time()
    cells = corridor_cells()
    print(f"[calib] fetching meteorology for {len(cells)} cells ...")
    m = met.fetch_archive(cells, args.start, end)
    if m.frame.empty:
        print("[calib] no meteorology")
        return 1
    grid_met = dataset.add_wind_components(indices.enrich(m.frame))
    print(f"[calib] meteorology: {len(grid_met):,} rows in {time.time() - t0:.0f}s")

    print("[calib] fetching archived fire detections ...")
    fires = fetch_season_fires(args.start, end)
    if not fires:
        print("[calib] no fires returned")
        return 1

    delhi = [c for c in cells if c.tier == "delhi"]
    months = pd.date_range(args.start, end, freq="MS").union(
        [pd.Timestamp(args.start)]).sort_values()

    results = {}
    for variant in [v.strip().upper() for v in args.variants.split(",") if v.strip()]:
        apply_variant(variant)
        print(f"\n[calib] === variant {variant} ===", flush=True)
        pieces = []
        for i, ms in enumerate(months):
            me = (months[i + 1] - pd.Timedelta(hours=1)) if i + 1 < len(months) \
                else pd.Timestamp(end) + pd.Timedelta(hours=23)
            ms_utc = pd.Timestamp(ms, tz="UTC")
            me_utc = pd.Timestamp(me, tz="UTC")
            chunk = run_month(fires, grid_met, delhi, ms_utc, me_utc)
            if not chunk.empty:
                pieces.append(chunk)
            print(f"[calib]   {ms:%Y-%m} -> {len(chunk):,} rows", flush=True)
        if not pieces:
            results[variant] = {"available": False, "reason": "no plume rows"}
            continue
        allp = pd.concat(pieces, ignore_index=True)
        daily = (allp.assign(date=allp["time"].dt.date)
                     .groupby("date", as_index=False)["plume_pm25"].mean())
        s = score(daily, target)
        results[variant] = s
        if s.get("available"):
            print(f"[calib]   r={s['correlation']:+.3f}  scale={s['scale_factor']:.3f}  "
                  f"RMSE={s['rmse_after_scaling']:.2f}  "
                  f"peak {s['modelled_peak_scaled']:.1f} vs DSS {s['dss_peak']:.1f}")

    # --- verdict ----------------------------------------------------------
    ranked = sorted(((v, r) for v, r in results.items() if r.get("available")),
                    key=lambda kv: -(kv[1]["correlation"] if kv[1]["correlation"] == kv[1]["correlation"] else -9))
    print("\n" + "=" * 72)
    print("PLUME PHYSICS VARIANTS, SCORED AGAINST THE MoES DSS ATTRIBUTION")
    print("=" * 72)
    print(f"  {'variant':8s} {'r':>8s} {'scale':>9s} {'RMSE':>8s} {'peak':>8s} {'DSS peak':>9s}")
    for v, r in ranked:
        print(f"  {v:8s} {r['correlation']:+8.3f} {r['scale_factor']:9.3f} "
              f"{r['rmse_after_scaling']:8.2f} {r['modelled_peak_scaled']:8.1f} "
              f"{r['dss_peak']:9.1f}")
    if ranked:
        best = ranked[0]
        print(f"\n  Best by correlation: variant {best[0]} (r={best[1]['correlation']:+.3f})")
        print("  Correlation is the meaningful statistic: the scale factor cannot")
        print("  improve it, so it measures the physics rather than the magnitude.")

    payload = {"window": [args.start, end], "variants": results,
               "target": "MoES/IITM DSS daily stubble attribution (third-party, cited)",
               "fitted": "one multiplicative scale factor per variant, through the origin",
               "note": ("The scale absorbs emission-factor uncertainty (5-8 g/kg for "
                        "cereal straw), satellite detection limits, and burn-duration "
                        "assumptions. Physics parameters are NOT fitted.")}
    out = C.MODELS / args.out
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\n[calib] written -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
