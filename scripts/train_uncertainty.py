"""Fit prediction intervals and GRAP exceedance probabilities.

Run:  python scripts/train_uncertainty.py [--panel train_panel] [--targets pm25,o3]
                                          [--holdout-start 2025-11-01 --holdout-end 2026-02-28]

A point forecast of 118 µg/m³ sitting just under a GRAP boundary tells an official
nothing about the risk of crossing it. This fits the conditional distribution instead,
so the system can answer the question a decision actually turns on: *what is the chance
tomorrow breaches Stage III?*

Coverage is the acceptance test, not sharpness. An 80% interval must contain the truth
about 80% of the time; one that contains 95% is hedging and useless for a decision, and
one that contains 55% is overconfident and dangerous.
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

from vayuchakra import config as C                              # noqa: E402
from vayuchakra import dataset, photolysis, uncertainty          # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default="train_panel")
    ap.add_argument("--targets", default="pm25,o3")
    ap.add_argument("--horizons", default="24,48,72")
    ap.add_argument("--holdout-start", default=None)
    ap.add_argument("--holdout-end", default=None)
    ap.add_argument("--out", default="uncertainty.json")
    args = ap.parse_args()

    path = C.DATA / f"{args.panel}.parquet"
    if not path.exists():
        print(f"[unc] no panel at {path}")
        return 1
    panel = pd.read_parquet(path)
    if "j_no2" not in panel.columns:
        panel = photolysis.add_features(panel, photolysis.describe(panel))
    holdout = ((args.holdout_start, args.holdout_end)
               if args.holdout_start and args.holdout_end else None)
    print(f"[unc] panel {len(panel):,} rows · split "
          f"{'holdout ' + args.holdout_start + '..' + args.holdout_end if holdout else 'chronological'}")

    report: dict = {"panel": args.panel,
                    "split": (f"holdout {args.holdout_start}..{args.holdout_end}"
                              if holdout else "chronological"),
                    "quantiles": list(uncertainty.QUANTILES),
                    "interval": list(uncertainty.INTERVAL),
                    "grap_thresholds_ugm3": uncertainty.GRAP_PM25,
                    "heads": {}}
    t0 = time.time()

    for target in [t.strip() for t in args.targets.split(",") if t.strip()]:
        for horizon in [int(h) for h in args.horizons.split(",") if h.strip()]:
            sup = dataset.make_supervised(panel, horizon, target)
            if len(sup) < 1000:
                continue
            feats = dataset.feature_columns(sup, target)
            head = uncertainty.train_quantile_head(sup, feats, target, horizon,
                                                   holdout=holdout)
            head.save()
            entry = dict(head.metrics)

            # GRAP risk is only meaningful for PM2.5, which is what the thresholds are
            # defined on.
            if target == "pm25":
                if holdout:
                    _, test = dataset.split_holdout_window(sup, holdout[0], holdout[1])
                else:
                    _, test = dataset.split_time_ordered(sup)
                preds = head.predict(test)
                risk = uncertainty.grap_risk(preds)
                y = test["y"].to_numpy(dtype="float64")
                entry["grap"] = {}
                for label, thr in uncertainty.GRAP_PM25.items():
                    p = risk[label].to_numpy()
                    actual = (y > thr)
                    ok = np.isfinite(p) & np.isfinite(y)
                    # Reliability: when the model says 70%, does it happen 70% of the
                    # time? A probability nobody can trust is worse than no probability.
                    bins, rel = np.linspace(0, 1, 6), []
                    for i in range(len(bins) - 1):
                        m = ok & (p >= bins[i]) & (p < bins[i + 1])
                        if m.sum() > 50:
                            rel.append({"predicted": round(float(p[m].mean()), 3),
                                        "observed": round(float(actual[m].mean()), 3),
                                        "n": int(m.sum())})
                    entry["grap"][label] = {
                        "threshold_ugm3": thr,
                        "base_rate": round(float(actual[ok].mean()), 4),
                        "mean_predicted": round(float(p[ok].mean()), 4),
                        "brier_score": round(float(np.mean((p[ok] - actual[ok]) ** 2)), 4),
                        "reliability": rel,
                    }
            report["heads"][f"{target}_{horizon}h"] = entry

    out = C.MODELS / args.out
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\n[unc] {len(report['heads'])} heads in {time.time() - t0:.0f}s -> {out}")

    print("\n" + "=" * 78)
    print("PREDICTION INTERVALS — coverage is the test, not sharpness")
    print("=" * 78)
    print(f"  {'head':12s} {'nominal':>8s} {'measured':>9s} {'width':>9s} {'crossing':>9s}  verdict")
    for name, m in report["heads"].items():
        c = m.get("coverage", {})
        if not c:
            continue
        print(f"  {name:12s} {100 * c['nominal']:7.0f}% {100 * c['measured']:8.1f}% "
              f"{c['median_width']:9.1f} {100 * m['quantile_crossing_rate']:8.1f}%  {c['verdict']}")

    pm = report["heads"].get("pm25_24h", {}).get("grap")
    if pm:
        print("\n  GRAP exceedance, PM2.5 +24 h — Brier score, lower is better")
        print(f"  {'threshold':44s} {'base rate':>10s} {'predicted':>10s} {'Brier':>8s}")
        for label, g in pm.items():
            print(f"  {label:44s} {g['base_rate']:10.3f} {g['mean_predicted']:10.3f} "
                  f"{g['brier_score']:8.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
