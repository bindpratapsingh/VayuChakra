"""Does the photolysis pathway improve the ozone forecast? Resolved by regime.

Run:  python scripts/photolysis_ablation.py [--target o3] [--horizon 24]

An overall RMSE hides the answer. The literature's claim is specific: aerosol suppresses
photolysis, which suppresses ozone *production*, which only matters when ozone is being
produced — daylight, and most strongly when the aerosol load is high. Averaging that over
nights and clean days dilutes a real effect toward nothing.

So this trains three configurations on identical splits and scores each **by regime**:

    full        every feature
    no_j        photolysis features removed, radiation inputs retained
    no_rad      photolysis AND its inputs removed (shortwave, UV, AOD)

`full` vs `no_j` asks whether the explicit photolysis calculation adds anything.
`no_j` vs `no_rad` asks how much radiation information matters at all.

Together they can distinguish two very different conclusions:

  * photolysis matters and we captured it explicitly       -> full beats no_j
  * photolysis matters but the model already inferred it   -> full == no_j, both beat no_rad

The second is the outcome D-036 predicted for the PM2.5 coupling, and it is a finding
rather than a failure — but only if the third configuration is run to demonstrate it.
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
from vayuchakra import dataset, model, photolysis           # noqa: E402

#: Features that carry radiation information, beyond the photolysis block itself.
RADIATION_INPUTS = ("shortwave_radiation", "direct_radiation", "diffuse_radiation",
                    "cams_uv", "cams_uv_clear_sky", "cams_aod")


def drop_cols(sup: pd.DataFrame, config: str) -> list[str]:
    """Which feature columns each configuration is allowed to see."""
    feats = dataset.feature_columns(sup, "o3")
    if config == "full":
        return feats
    j_like = [c for c in feats if c.startswith(("j_", "target_j_",
                                                "solar_zenith", "target_solar_zenith"))]
    if config == "no_j":
        return [c for c in feats if c not in j_like]
    rad = [c for c in feats
           if any(r in c for r in RADIATION_INPUTS)] + j_like
    return [c for c in feats if c not in set(rad)]


def regime_scores(test: pd.DataFrame, pred: np.ndarray, target: str) -> dict:
    """RMSE overall and split by the regimes where photolysis should matter."""
    y = test[target + "_y"] if target + "_y" in test.columns else test["y"]
    y = y.to_numpy(dtype="float64")

    def rmse(mask) -> float:
        m = mask & np.isfinite(y) & np.isfinite(pred)
        return float(np.sqrt(np.mean((pred[m] - y[m]) ** 2))) if m.sum() > 30 else float("nan")

    sw = pd.to_numeric(test.get("target_shortwave_radiation",
                                test.get("shortwave_radiation")), errors="coerce").to_numpy()
    aod = pd.to_numeric(test.get("target_cams_aod",
                                 test.get("cams_aod")), errors="coerce").to_numpy()
    winter = pd.to_numeric(test.get("target_is_winter"), errors="coerce").to_numpy() == 1
    summer = pd.to_numeric(test.get("target_is_summer"), errors="coerce").to_numpy() == 1

    day = np.nan_to_num(sw, nan=0.0) > 100.0
    high_aod = np.nan_to_num(aod, nan=0.0) >= 0.7
    everything = np.ones(len(y), dtype=bool)
    return {
        "overall": round(rmse(everything), 3),
        "daytime": round(rmse(day), 3),
        "daytime_high_aod": round(rmse(day & high_aod), 3),
        "winter_daytime": round(rmse(day & winter), 3),
        "summer_daytime": round(rmse(day & summer), 3),
        "n_daytime": int((day & np.isfinite(y)).sum()),
        "n_daytime_high_aod": int((day & high_aod & np.isfinite(y)).sum()),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default="train_panel")
    ap.add_argument("--target", default="o3")
    ap.add_argument("--horizon", type=int, default=24)
    ap.add_argument("--out", default="photolysis_ablation.json")
    args = ap.parse_args()

    panel = pd.read_parquet(C.DATA / f"{args.panel}.parquet")
    if "j_no2" not in panel.columns:
        pm = photolysis.describe(panel)
        panel = photolysis.add_features(panel, pm)
        print(f"[abl] photolysis added · J(NO2) reduction {100 * pm.overall_reduction:.1f}% "
              f"({'in' if pm.in_reference_range else 'OUTSIDE'} the 20-30% literature range)")

    sup = dataset.make_supervised(panel, args.horizon, args.target)
    train, test = dataset.split_time_ordered(sup)
    print(f"[abl] {args.target} +{args.horizon}h · train {len(train):,} test {len(test):,}")

    results = {}
    for config in ("full", "no_j", "no_rad"):
        feats = drop_cols(sup, config)
        head = model.train_head(sup, feats, args.target, args.horizon,
                                config_note=f"ablation:{config}", verbose=False)
        pred = head.predict(test)
        results[config] = {
            "n_features": len(head.features),
            "regimes": regime_scores(test, pred, args.target),
            "top_features": [f for f, _ in model.importance(head, top=8)],
        }
        r = results[config]["regimes"]
        print(f"[abl] {config:8s} feats {len(head.features):3d} · "
              f"overall {r['overall']:7.3f} · daytime {r['daytime']:7.3f} · "
              f"high-AOD day {r['daytime_high_aod']:7.3f} · winter day {r['winter_daytime']:7.3f}")

    # --- verdict ----------------------------------------------------------
    def delta(a: str, b: str, regime: str) -> float:
        ra = results[a]["regimes"][regime]
        rb = results[b]["regimes"][regime]
        return 100.0 * (rb - ra) / rb if rb and rb == rb else float("nan")

    print("\n" + "=" * 74)
    print(f"PHOTOLYSIS ABLATION — {args.target} at +{args.horizon} h")
    print("=" * 74)
    print(f"  {'regime':22s} {'full':>9s} {'no_j':>9s} {'no_rad':>9s} "
          f"{'j adds':>9s} {'rad adds':>9s}")
    for regime in ("overall", "daytime", "daytime_high_aod",
                   "winter_daytime", "summer_daytime"):
        f = results["full"]["regimes"][regime]
        nj = results["no_j"]["regimes"][regime]
        nr = results["no_rad"]["regimes"][regime]
        print(f"  {regime:22s} {f:9.3f} {nj:9.3f} {nr:9.3f} "
              f"{delta('full', 'no_j', regime):+8.2f}% {delta('no_j', 'no_rad', regime):+8.2f}%")

    j_day = delta("full", "no_j", "daytime_high_aod")
    rad_day = delta("no_j", "no_rad", "daytime_high_aod")
    print()
    if j_day > 0.5:
        print("  VERDICT: the explicit photolysis calculation adds measurable skill.")
    elif rad_day > 1.0:
        print("  VERDICT: radiation matters, but the model already infers the photolysis")
        print("  effect from shortwave, UV and AOD. Computing J explicitly is redundant")
        print("  for prediction — though it remains the interpretable, physical route,")
        print("  and it is what makes the mechanism reportable rather than implicit.")
    else:
        print("  VERDICT: neither photolysis nor radiation adds materially at this")
        print("  horizon. Reported as a negative result.")

    (C.MODELS / args.out).write_text(json.dumps(
        {"target": args.target, "horizon_h": args.horizon, "configs": results},
        indent=2, default=str), encoding="utf-8")
    print(f"\n[abl] written -> {C.MODELS / args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
