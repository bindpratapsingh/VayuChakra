"""Join the multi-winter panel to the recent one.

Run:  python scripts/combine_panels.py [--panels winters_panel,train_panel]
                                       [--out combined_panel] [--keep-chem]

WHY THIS EXISTS
---------------
The project trained on a single winter (Nov 2025 - Feb 2026), which made both of its
evaluation splits misleading in opposite directions: the recency split kept that winter
in training and then tested on summer, while the winter hold-out tested winter with the
model having never seen one. Neither is the operational question, which is *trained on
past winters, forecasting the current one*.

The archive holds four more usable winters (2018-19 through 2021-22). This concatenates
them onto the recent panel so a winter can be held out while five others remain in
training.

THE CHEMISTRY PRIOR IS DROPPED BY DEFAULT, AND THAT IS DELIBERATE
------------------------------------------------------------------
CAMS begins in August 2022, so it exists for the recent panel and not for the older one.
Concatenating without care would give the model a feature that is present *only* in
2025-26 — and a tree can then use "CAMS is not missing" as a proxy for "this is the
recent period", learning the era rather than the atmosphere. That is a subtle leak with
an obvious symptom only after it has already flattered a score.

So the combined panel drops the CAMS columns unless `--keep-chem` is passed. The
recent-only panel keeps them and is still trained separately; the two configurations are
reported side by side rather than blended.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vayuchakra import config as C   # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panels", default="winters_panel,train_panel")
    ap.add_argument("--out", default="combined_panel")
    ap.add_argument("--allow-missing", action="store_true",
                    help="proceed even if a named panel is absent; off by default so a "
                         "failed upstream build cannot pass silently")
    ap.add_argument("--keep-chem", action="store_true",
                    help="keep CAMS columns even though they cover only part of the "
                         "record; see the module docstring for why this is off")
    args = ap.parse_args()

    names = [n.strip() for n in args.panels.split(",") if n.strip()]
    frames = []
    for name in names:
        path = C.DATA / f"{name}.parquet"
        if not path.exists():
            # Skipping quietly is how a failed multi-winter build turned into a
            # "successful" single-winter retrain: combine dropped the missing panel,
            # every downstream step ran on the remaining one, and the pipeline
            # reported six green stages for a model that had seen one winter.
            print(f"[combine] ERROR: {path.name} does not exist.")
            print("[combine] Refusing to silently produce a panel that is missing one "
                  "of its named inputs. Build it, or pass --allow-missing if you "
                  "genuinely mean to combine only what is present.")
            if not args.allow_missing:
                return 2
            print("[combine] --allow-missing given, continuing without it")
            continue
        df = pd.read_parquet(path)
        df["source_panel"] = name
        print(f"[combine] {name}: {len(df):,} rows · {df['station_id'].nunique()} stations · "
              f"{df['time'].min().date()} -> {df['time'].max().date()}")
        frames.append(df)

    if not frames:
        print("[combine] nothing to combine")
        return 1

    chem = [c for f in frames for c in f.columns if c.startswith("cams_")]
    chem = sorted(set(chem))
    if chem and not args.keep_chem:
        coverage = {}
        for f in frames:
            present = [c for c in chem if c in f.columns and f[c].notna().any()]
            coverage[f["source_panel"].iloc[0]] = len(present)
        if len(set(coverage.values())) > 1:
            print(f"[combine] dropping {len(chem)} CAMS columns: present in "
                  f"{ {k: v for k, v in coverage.items()} } — uneven coverage would let a "
                  f"tree use 'chemistry prior is not missing' as a proxy for 'recent era'")
            frames = [f.drop(columns=[c for c in chem if c in f.columns]) for f in frames]

    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined = combined.sort_values(["station_id", "time"]).reset_index(drop=True)

    dup = combined.duplicated(["station_id", "time"]).sum()
    if dup:
        # Overlapping windows would double-weight those hours in training.
        print(f"[combine] dropping {dup:,} duplicate (station, hour) rows")
        combined = combined.drop_duplicates(["station_id", "time"], keep="last")

    out = C.DATA / f"{args.out}.parquet"
    combined.to_parquet(out, index=False)

    ist = pd.to_datetime(combined["time"], utc=True).dt.tz_convert("Asia/Kolkata")
    winters = sorted({(y if m >= 11 else y - 1)
                      for y, m in zip(ist.dt.year, ist.dt.month) if m in (11, 12, 1, 2)})
    print(f"\n[combine] {len(combined):,} rows · {combined['station_id'].nunique()} stations · "
          f"{len(combined.columns)} columns -> {out.name}")
    print(f"[combine] window {combined['time'].min().date()} -> {combined['time'].max().date()}")
    print(f"[combine] winters covered: {', '.join(f'{w}-{w + 1}' for w in winters)}"
          f"  ({len(winters)} total)")
    for col in ("pm25", "o3", "no2", "mixing_depth_m"):
        if col in combined.columns:
            print(f"[combine]   {col:16s} {100 * combined[col].notna().mean():5.1f}% populated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
