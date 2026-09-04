"""Run the two validations that decide whether the project is worth anything.

Run:  python scripts/validate.py [--ablation-start 2025-11-01] [--ablation-end 2026-02-28]
                                 [--skip-dss] [--skip-ablation]

1. **Coupling ablation** — the same forecast with the feedback loop on and off, scored
   against the same observations. This tests the problem statement's own premise rather
   than repeating it.
2. **MoES DSS head-to-head** — VayuChakra, the ministry's operational DSS, and
   persistence, all scored against the same Delhi city-mean observations over the same
   hours at the same lead times.

Writes `models/validation.json`. A negative result is reported as a negative result.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vayuchakra import config as C     # noqa: E402
from vayuchakra import validate        # noqa: E402


def _print_ablation(a: dict) -> None:
    print("\n" + "=" * 74)
    print("COUPLING ABLATION — does modelling the feedback actually help?")
    print("=" * 74)
    if not a.get("available"):
        print(f"  unavailable: {a.get('reason')}")
        return
    o = a["overall"]
    print(f"  window {a['window']['from']} -> {a['window']['to']}   n = {o['n']:,}")
    print(f"  {'':22s} {'RMSE':>9s} {'bias':>9s}")
    print(f"  {'uncoupled':22s} {o['uncoupled_rmse']:9.2f} {o['uncoupled_bias']:9.2f}")
    print(f"  {'coupled':22s} {o['coupled_rmse']:9.2f} {o['coupled_bias']:9.2f}")
    imp = o.get("rmse_improvement_pct")
    verdict = ("coupling HELPS" if imp and imp > 0 else
               "coupling does NOT help overall" if imp is not None else "inconclusive")
    print(f"  improvement {imp:+.2f}%   -> {verdict}")

    if a.get("by_regime"):
        print("\n  by regime (the honest expectation: it helps when the air is stagnant")
        print("  and high in aerosol, and does nothing on a windy clean day):")
        print(f"    {'regime':20s} {'n':>7s} {'uncoupled':>10s} {'coupled':>9s} {'change':>9s}")
        for name, r in a["by_regime"].items():
            print(f"    {name:20s} {r['n']:7,d} {r['uncoupled_rmse']:10.2f} "
                  f"{r['coupled_rmse']:9.2f} {r['improvement_pct']:+8.2f}%")

    gate = a.get("literature_gate", {})
    if gate.get("checks"):
        print(f"\n  literature gate (n = {gate.get('n_in_regime')} high-aerosol daylight hours):")
        for k, v in gate["checks"].items():
            print(f"    {k:24s} {str(v['value']):>9s}  expected {str(v['expected']):16s} "
                  f"{'PASS' if v['ok'] else 'FAIL'}")
        print(f"    overall: {'PASS' if gate.get('ok') else 'FAIL'}")


def _print_dss(d: dict) -> None:
    print("\n" + "=" * 74)
    print("HEAD-TO-HEAD vs the MoES/IITM Decision Support System")
    print("=" * 74)
    if not d.get("available"):
        print(f"  unavailable: {d.get('reason')}")
        return
    print(f"  window        {d['window']['from']} -> {d['window']['to']}")
    print(f"  ground truth  {d['ground_truth']}")
    print(f"  our config    {d['configuration']}")
    print(f"  DSS source    {d['citation']}")
    print()
    print(f"  {'lead':>6s} {'hours':>7s} {'DSS RMSE':>10s} {'ours':>9s} "
          f"{'persistence':>12s} {'corr(DSS)':>10s}")
    for row in d["by_lead"]:
        ours = row.get("vayuchakra", {})
        pers = row.get("persistence", {})
        dss_c = row.get("dss_on_common_hours", row["dss"])
        print(f"  {row['lead_hours']:5d}h {row.get('n_common', row['n_hours']):7,d} "
              f"{dss_c.get('rmse', float('nan')):10.2f} "
              f"{ours.get('rmse', float('nan')):9.2f} "
              f"{pers.get('rmse', float('nan')):12.2f} "
              f"{row['dss'].get('corr', float('nan')):10.3f}")
    print("\n  READ THIS BEFORE QUOTING THE TABLE")
    print("  The DSS forecasts were issued OPERATIONALLY - it had to predict the weather")
    print("  as well as the chemistry, days ahead. Our hindcast is driven by ERA5")
    print("  REANALYSIS, the meteorology as it actually turned out. That is a material")
    print("  advantage and it is NOT a fair comparison of forecast skill.")
    print("  It supports: the statistical layer maps meteorology to PM2.5 competitively.")
    print("  It does NOT support: 'we forecast better than the MoES DSS'.")
    print("  The DSS is also a full chemical transport model producing far more than a")
    print("  city PM2.5 number, and is being scored here on one of its outputs.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ablation-start", default="2025-11-01")
    ap.add_argument("--ablation-end", default="2026-02-28")
    ap.add_argument("--dss-start", default="2021-10-06")
    ap.add_argument("--dss-end", default="2022-02-28")
    ap.add_argument("--skip-dss", action="store_true")
    ap.add_argument("--skip-ablation", action="store_true")
    args = ap.parse_args()

    report: dict = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    if not args.skip_ablation:
        print("[validate] running coupling ablation ...")
        a = validate.coupling_ablation(args.ablation_start, args.ablation_end)
        report["coupling_ablation"] = a
        _print_ablation(a)

    if not args.skip_dss:
        print("\n[validate] running DSS head-to-head ...")
        d = validate.dss_head_to_head(args.dss_start, args.dss_end)
        report["dss_head_to_head"] = d
        _print_dss(d)

    out = C.MODELS / "validation.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\n[validate] written -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
