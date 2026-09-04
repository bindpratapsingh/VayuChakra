"""What would ozone be if the aerosol were cleaned up? A counterfactual, not a forecast.

Run:  python scripts/ozone_sensitivity.py [--horizon 24] [--cuts 25,50,75]

WHY THIS IS THE RIGHT TEST FOR THE PHOTOLYSIS WORK
---------------------------------------------------
Adding explicit photolysis features did not improve the ozone forecast — measured, and
reported as such. That is a real result, but it is an answer to the wrong question.

A statistical forecaster interpolates conditions it has seen. It cannot answer *"what
would ozone be if Delhi's aerosol halved?"*, because that atmosphere is not in the
training data. A **mechanism** can answer it, and that is what the photolysis module
buys: not skill, but the ability to run a counterfactual.

It also happens to be exactly what the problem statement asks for — a system that
"simulates real-time interactions between atmospheric physics and chemical transport",
rather than one that merely predicts.

THE PUBLISHED NUMBER WE ARE CHECKED AGAINST
-------------------------------------------
The APHH-India campaign found that for Delhi, **a 50% reduction in AOD raises ozone by
about 25%**, because wintertime ozone production there is strongly radiation-limited
(Nelson et al., Faraday Discussions 226, 2021). If our chain reproduces the sign and
rough magnitude of that, the physics is doing something real. If it does not, we say so.

HOW THE SENSITIVITY IS OBTAINED
-------------------------------
Perturb the aerosol, recompute photolysis consistently, and let the trained ozone head
respond. Both AOD *and* the J terms derived from it move together — changing one without
the other would ask the model about an atmosphere that cannot exist, and would measure
nothing but its tolerance for contradictory inputs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vayuchakra import config as C                      # noqa: E402
from vayuchakra import dataset, model, photolysis       # noqa: E402

#: The published Delhi result this is checked against: 50% less AOD, ~25% more ozone.
PUBLISHED = {"aod_cut": 0.50, "o3_change": +0.25,
             "source": "Nelson et al., Faraday Discussions 226 (2021), APHH-India"}


def perturb(sup: pd.DataFrame, cut: float, pm: photolysis.PhotolysisModel) -> pd.DataFrame:
    """Scale aerosol down by `cut` and rebuild every quantity that depends on it."""
    out = sup.copy()
    factor = 1.0 - cut
    for col in ("cams_aod", "target_cams_aod"):
        if col in out.columns:
            out[col] = out[col] * factor

    # Recompute photolysis from the perturbed aerosol. The source-time and target-time
    # blocks are rebuilt separately because they sit at different sun angles.
    for prefix, aod_col, time_col in (("", "cams_aod", "time"),
                                      ("target_", "target_cams_aod", None)):
        if aod_col not in out.columns:
            continue
        if time_col and time_col in out.columns:
            times = pd.to_datetime(out[time_col], utc=True)
        elif "time" in out.columns and "horizon_h" in out.columns:
            times = pd.to_datetime(out["time"], utc=True) + pd.to_timedelta(
                out["horizon_h"], unit="h")
        else:
            continue
        lat = out.get("lat", pd.Series(C.DELHI_LAT, index=out.index))
        lon = out.get("lon", pd.Series(C.DELHI_LON, index=out.index))
        from vayuchakra.feedback import solar_zenith_deg
        zen = solar_zenith_deg(times, lat, lon)
        aod = pd.to_numeric(out[aod_col], errors="coerce").to_numpy()
        att = photolysis.attenuation(np.nan_to_num(aod, nan=photolysis.AOD_BACKGROUND),
                                     zen, pm.k)
        clear_no2 = photolysis.clear_sky_j(zen, "no2")
        clear_o1d = photolysis.clear_sky_j(zen, "o1d")
        for name, val in ((f"{prefix}j_attenuation", att),
                          (f"{prefix}j_no2", clear_no2 * att),
                          (f"{prefix}j_o1d", clear_o1d * att)):
            if name in out.columns:
                out[name] = val
        pristine = clear_no2 * photolysis.attenuation(
            np.full(len(out), photolysis.AOD_BACKGROUND), zen, pm.k)
        if f"{prefix}j_no2_deficit" in out.columns:
            out[f"{prefix}j_no2_deficit"] = pristine - clear_no2 * att
        if f"{prefix}j_no2_ratio" in out.columns:
            out[f"{prefix}j_no2_ratio"] = np.where(
                pristine > 1e-9, (clear_no2 * att) / pristine, np.nan)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default="train_panel")
    ap.add_argument("--horizon", type=int, default=24)
    ap.add_argument("--cuts", default="25,50,75")
    ap.add_argument("--out", default="ozone_sensitivity.json")
    ap.add_argument("--holdout-start", default="2025-11-01",
                    help="season-block hold-out start; the chronological split contains "
                         "no winter and so cannot test a winter phenomenon")
    ap.add_argument("--holdout-end", default="2026-02-28")
    ap.add_argument("--chronological", action="store_true",
                    help="use the recency split instead (summer-only test set)")
    args = ap.parse_args()

    panel = pd.read_parquet(C.DATA / f"{args.panel}.parquet")
    pm = photolysis.describe(panel)
    if "j_no2" not in panel.columns:
        panel = photolysis.add_features(panel, pm)
    print(f"[sens] J(NO2) reduction at present-day aerosol: "
          f"{100 * pm.overall_reduction:.1f}%")

    sup = dataset.make_supervised(panel, args.horizon, "o3")
    if args.chronological:
        _, test = dataset.split_time_ordered(sup)
        split_note = "chronological (recency) split - test set is summer only"
    else:
        _, test = dataset.split_holdout_window(sup, args.holdout_start, args.holdout_end)
        split_note = f"season-block hold-out {args.holdout_start} to {args.holdout_end}"
    print(f"[sens] split: {split_note}")
    head = model.Head.load("o3", args.horizon)
    if head is None:
        print("[sens] no trained o3 head - run scripts/train.py first")
        return 1

    base = head.predict(test)
    sw = pd.to_numeric(test.get("target_shortwave_radiation"), errors="coerce").to_numpy()
    day = np.nan_to_num(sw, nan=0.0) > 100.0
    winter = pd.to_numeric(test.get("target_is_winter"), errors="coerce").to_numpy() == 1
    print(f"[sens] test {len(test):,} rows · daytime {day.sum():,} · "
          f"winter daytime {(day & winter).sum():,}")

    rows = []
    for cut in [float(c) / 100.0 for c in args.cuts.split(",") if c.strip()]:
        pert = perturb(test, cut, pm)
        new = head.predict(pert)
        def pct(mask) -> float:
            m = mask & np.isfinite(base) & np.isfinite(new) & (base > 1.0)
            return float(100.0 * np.mean((new[m] - base[m]) / base[m])) if m.sum() > 50 else float("nan")
        rows.append({
            "aod_cut_pct": round(100 * cut, 1),
            "o3_change_all_pct": round(pct(np.ones(len(base), dtype=bool)), 2),
            "o3_change_daytime_pct": round(pct(day), 2),
            "o3_change_winter_day_pct": round(pct(day & winter), 2),
        })
        print(f"[sens] AOD -{100 * cut:.0f}%  ->  ozone "
              f"{rows[-1]['o3_change_daytime_pct']:+.2f}% daytime, "
              f"{rows[-1]['o3_change_winter_day_pct']:+.2f}% winter daytime")

    # --- compare against the published Delhi figure -----------------------
    at50 = next((r for r in rows if abs(r["aod_cut_pct"] - 50) < 1e-6), None)
    verdict = {}
    if at50:
        modelled = at50["o3_change_daytime_pct"] / 100.0
        target = PUBLISHED["o3_change"]
        verdict = {
            "modelled_o3_change_at_50pct_aod_cut": round(100 * modelled, 2),
            "published": round(100 * target, 1),
            "same_sign": bool(modelled > 0),
            "within_factor_of_3": bool(modelled > 0 and (target / 3) <= modelled <= (target * 3)),
            "source": PUBLISHED["source"],
        }
        print("\n" + "=" * 72)
        print("OZONE RESPONSE TO A 50% AEROSOL REDUCTION")
        print("=" * 72)
        print(f"  modelled (daytime)  {100 * modelled:+6.2f}%")
        print(f"  published (Delhi)   {100 * target:+6.1f}%   {PUBLISHED['source']}")
        if verdict["within_factor_of_3"]:
            print("  -> same sign and within a factor of three. The mechanism reproduces")
            print("     a published Delhi result it was never fitted to.")
        elif verdict["same_sign"]:
            print("  -> correct sign, magnitude off. Reported as a partial result.")
        else:
            print("  -> WRONG SIGN. The chain does not reproduce the published behaviour;")
            print("     reported as a negative result.")

    payload = {"horizon_h": args.horizon, "split": split_note,
               "photolysis": pm.to_dict(),
               "sensitivity": rows, "verdict": verdict,
               "note": ("Counterfactual, not a forecast. AOD and the photolysis terms "
                        "derived from it are perturbed together, because changing one "
                        "alone describes an atmosphere that cannot exist.")}
    (C.MODELS / args.out).write_text(json.dumps(payload, indent=2, default=str),
                                     encoding="utf-8")
    print(f"\n[sens] written -> {C.MODELS / args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
