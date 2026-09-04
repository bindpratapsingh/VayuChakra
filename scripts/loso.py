"""Leave-one-station-out: does this work where there is no monitor?

Run:  python scripts/loso.py [--targets pm25,o3] [--horizon 24] [--stations 10]

Every score so far has been temporal — train on some hours, test on others, at stations
the model has seen. That answers "does it work next week". It does not answer the
question a **gridded** product actually rests on: the forecast is served for 1,120 cells,
and only about 40 of them contain an instrument. For the other thousand, the model is
extrapolating in space, and nothing measured so far tells us whether it can.

Leave-one-station-out does. Each station is removed from training entirely, the model is
rebuilt on the rest, and it predicts a place it has never seen. If that beats persistence
at the held-out station, gridded output is defensible. If it does not, the honest
conclusion is that the product is a station interpolator wearing a map, and it should be
said.

Persistence is a demanding baseline here for a subtle reason worth stating: it uses the
held-out station's OWN recent history, which the model is denied. So this compares a
model that has never seen the location against a baseline that has.
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

from vayuchakra import config as C                          # noqa: E402
from vayuchakra import dataset, grid, model, obs, photolysis  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default="train_panel")
    ap.add_argument("--targets", default="pm25,o3")
    ap.add_argument("--horizon", type=int, default=24)
    ap.add_argument("--stations", type=int, default=10)
    ap.add_argument("--out", default="loso.json")
    args = ap.parse_args()

    panel = pd.read_parquet(C.DATA / f"{args.panel}.parquet")
    if "j_no2" not in panel.columns:
        panel = photolysis.add_features(panel, photolysis.describe(panel))

    # Station coordinates, so a poor result can be read against geography rather than
    # left as an anonymous id.
    coords = (panel.groupby("station_id")[["lat", "lon"]].first()
              if {"lat", "lon"}.issubset(panel.columns) else pd.DataFrame())

    report: dict = {"panel": args.panel, "horizon_h": args.horizon,
                    "note": ("each station held out of training entirely; persistence "
                             "still uses that station's own history, which the model "
                             "is denied"),
                    "targets": {}}

    for target in [t.strip() for t in args.targets.split(",") if t.strip()]:
        sup = dataset.make_supervised(panel, args.horizon, target)
        if sup.empty:
            continue
        feats = dataset.feature_columns(sup, target)
        print(f"\n[loso] {target} +{args.horizon}h · {len(sup):,} rows · "
              f"{sup['station_id'].nunique()} stations")
        t0 = time.time()
        res = model.leave_one_station_out(sup, feats, target, args.horizon,
                                          max_stations=args.stations, verbose=True)
        if not res.get("available"):
            print(f"[loso] {target}: unavailable")
            continue

        rows = res["per_station"]
        beat = [r for r in rows if r["improvement_pct"] == r["improvement_pct"]
                and r["improvement_pct"] > 0]
        res["stations_beating_persistence"] = len(beat)
        res["stations_evaluated"] = len(rows)
        if not coords.empty:
            for r in rows:
                sid = r["station_id"]
                if sid in coords.index:
                    r["km_from_delhi"] = round(grid.haversine_km(
                        float(coords.loc[sid, "lat"]), float(coords.loc[sid, "lon"]),
                        C.DELHI_LAT, C.DELHI_LON), 1)
        report["targets"][target] = res
        print(f"[loso] {target}: mean RMSE {res['mean_rmse']:.2f} vs persistence "
              f"{res['mean_persistence_rmse']:.2f} "
              f"({res['mean_improvement_pct']:+.2f}%) · "
              f"{len(beat)}/{len(rows)} stations beat persistence · "
              f"{time.time() - t0:.0f}s")

    # --- verdict ----------------------------------------------------------
    print("\n" + "=" * 74)
    print(f"LEAVE-ONE-STATION-OUT — +{args.horizon} h")
    print("=" * 74)
    print(f"  {'target':8s} {'stations':>9s} {'RMSE':>9s} {'persistence':>12s} "
          f"{'vs persist':>11s} {'beat':>7s}")
    for target, res in report["targets"].items():
        print(f"  {target:8s} {res['stations_evaluated']:9d} {res['mean_rmse']:9.2f} "
              f"{res['mean_persistence_rmse']:12.2f} {res['mean_improvement_pct']:+10.2f}% "
              f"{res['stations_beating_persistence']}/{res['stations_evaluated']:>3d}")
    print()
    ok = all(r["mean_improvement_pct"] > 0 for r in report["targets"].values())
    if ok:
        print("  Beats persistence at stations it has never seen, so producing a value")
        print("  for a cell with no instrument is defensible rather than decorative.")
    else:
        print("  Does NOT beat persistence out of sample in space. The gridded output")
        print("  is then closer to an interpolation than a forecast, and must be")
        print("  described that way.")

    (C.MODELS / args.out).write_text(json.dumps(report, indent=2, default=str),
                                     encoding="utf-8")
    print(f"\n[loso] written -> {C.MODELS / args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
