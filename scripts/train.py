"""Train every forecast head and write a metrics report.

Run:  python scripts/train.py [--panel train_panel] [--loso] [--targets pm25,o3]

Trains one model per (pollutant, horizon) with a chronological hold-out, scores each
against persistence, and writes `models/metrics.json`.

Persistence is the baseline that matters. "Tomorrow looks like today" is embarrassingly
hard to beat at 24 hours, and the sibling AirGrid project's 24 h model **lost to it by
4.2%** — a result that only surfaced because the comparison was run. Any head that
fails to beat it is printed as a failure here rather than quietly shipped.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vayuchakra import config as C                  # noqa: E402
from vayuchakra import dataset, model, photolysis   # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default="train_panel")
    ap.add_argument("--targets", default="pm25,o3,pm10,no2")
    ap.add_argument("--horizons", default="24,48,72")
    ap.add_argument("--loso", action="store_true",
                    help="also run leave-one-station-out spatial validation")
    ap.add_argument("--note", default="", help="configuration note stored with each model")
    ap.add_argument("--no-photolysis", action="store_true",
                    help="ablation: train without the photolysis features")
    ap.add_argument("--out", default="metrics.json", help="metrics filename")
    ap.add_argument("--holdout-start", default=None,
                    help="hold out this window instead of the most recent slice; the "
                         "recency split contains no winter")
    ap.add_argument("--holdout-end", default=None)
    ap.add_argument("--model-dir", default=None,
                    help="write boosters here instead of models/. Needed so a model "
                         "trained for a specific hold-out does not overwrite the "
                         "production one - and so the DSS comparison can use a model "
                         "that never saw the DSS window.")
    args = ap.parse_args()

    path = C.DATA / f"{args.panel}.parquet"
    if not path.exists():
        print(f"[train] no panel at {path} - run scripts/build_dataset.py first")
        return 1

    panel = pd.read_parquet(path)
    print(f"[train] panel {len(panel):,} rows, {panel['station_id'].nunique()} stations, "
          f"{panel['time'].min()} -> {panel['time'].max()}")

    # Backfill photolysis onto panels built before this module existed, rather than
    # forcing a 43-minute rebuild for six derived columns.
    if "j_no2" not in panel.columns:
        pm = photolysis.describe(panel)
        panel = photolysis.add_features(panel, pm)
        print(f"[train] photolysis features added · J(NO2) reduction "
              f"{100 * pm.overall_reduction:.1f}% "
              f"(literature 20-30%: {'in range' if pm.in_reference_range else 'OUTSIDE'})")

    if args.no_photolysis:
        drop = [c for c in panel.columns if c.startswith(("j_", "solar_zenith"))]
        panel = panel.drop(columns=drop)
        print(f"[train] ABLATION: dropped {len(drop)} photolysis features")

    targets = [t.strip() for t in args.targets.split(",") if t.strip()]
    horizons = [int(h) for h in args.horizons.split(",") if h.strip()]
    note = args.note or (
        f"panel={args.panel}; chem={'yes' if 'cams_pm25' in panel.columns else 'no'}; "
        f"inversion={panel['inversion_method'].iloc[0] if 'inversion_method' in panel else 'unknown'}")

    report: dict = {"panel": args.panel,
                    "split": (f"holdout {args.holdout_start}..{args.holdout_end}"
                              if args.holdout_start else "chronological (summer-only test)"),
                    "rows": int(len(panel)),
                    "stations": int(panel["station_id"].nunique()),
                    "window": [str(panel["time"].min()), str(panel["time"].max())],
                    "note": note, "heads": {}}
    t0 = time.time()

    for target in targets:
        if target not in panel.columns or panel[target].notna().sum() < 500:
            print(f"[train] skipping {target}: too few observations")
            continue
        for horizon in horizons:
            sup = dataset.make_supervised(panel, horizon, target)
            if len(sup) < 1000:
                print(f"[train] skipping {target}/{horizon}h: only {len(sup)} rows")
                continue
            feats = dataset.feature_columns(sup, target)
            holdout = ((args.holdout_start, args.holdout_end)
                       if args.holdout_start and args.holdout_end else None)
            head = model.train_head(sup, feats, target, horizon, config_note=note,
                                    holdout=holdout)
            head.save(Path(args.model_dir) if args.model_dir else None)
            entry = dict(head.metrics)
            entry["n_features"] = len(head.features)
            entry["top_features"] = [f for f, _ in model.importance(head, top=12)]

            if args.loso:
                entry["loso"] = model.leave_one_station_out(
                    sup, feats, target, horizon, max_stations=8, verbose=False)
            report["heads"][f"{target}_{horizon}h"] = entry

    out = (Path(args.model_dir) if args.model_dir else C.MODELS) / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n[train] {len(report['heads'])} heads in {time.time() - t0:.0f}s -> {out}")

    # Summary table, with the persistence verdict made explicit rather than left for
    # the reader to work out from two RMSE columns.
    print(f"\n{'head':14s} {'RMSE':>8s} {'persist':>8s} {'vs persist':>11s} {'r2':>7s}  verdict")
    for name, m in report["heads"].items():
        imp = m.get("improvement_pct")
        verdict = "-" if imp is None or imp != imp else ("BEATS" if imp > 0 else "LOSES TO")
        print(f"{name:14s} {m['rmse']:8.2f} {m['persistence_rmse']:8.2f} "
              f"{imp:+10.2f}% {m['r2']:7.3f}  {verdict} persistence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
