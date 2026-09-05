"""Capture a full-resolution forecast as a static bundle the hosted instance can serve.

Run:  python scripts/export_snapshot.py [--base http://127.0.0.1:8100]
                                        [--out data/snapshot]

WHY THIS EXISTS
---------------
The live pipeline does not fit in 512 MB, which is what the free hosting tier gives you.
Measured on this machine, with the frame already cast to float32:

    420 Delhi cells   211,680 rows   peak RSS 1,083 MB
    182 Delhi cells    91,728 rows   peak RSS   701 MB

Fitting a line through those two points gives a fixed cost of about 283 MB before a
single cell is forecast, on top of a 126 MB floor for Python, pandas, XGBoost and the
twelve boosters. So even a grid coarse enough to be useless would still not fit: the
problem is not the number of cells, and coarsening the domain to chase it would have
degraded the product for no gain.

So the hosted instance does not run the pipeline. It serves a bundle produced here, by
the real pipeline, at the real resolution: 420 cells at 2.8 km, all four pollutants,
the coupled solver, photolysis, the plume, and every validation number. What the
deployment gives up is freshness, not fidelity, and that is the right thing to give up
of the two. Every payload carries the timestamp it was generated at, and the dashboard
shows it.

The bundle is captured from the running API rather than rebuilt from the modules, so
what ships is byte-for-byte what the endpoints return. A reimplementation here would be
a second copy of the serialisation logic and a second place for it to drift.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

#: Every route the dashboard calls, with the query variants it uses. A snapshot that is
#: missing one of these shows an offline panel on an otherwise working page, which is a
#: worse failure than an obviously missing deployment.
ROUTES: list[str] = [
    "/health",
    "/summary",
    "/forecast?horizon=24",
    "/forecast?horizon=48",
    "/forecast?horizon=72",
    "/profile",
    "/domain",
    "/coupling",
    "/photolysis",
    "/inversion",
    "/plume",
    "/plume/calibration",
    "/uncertainty?horizon=24",
    "/uncertainty?horizon=48",
    "/uncertainty?horizon=72",
    "/validation",
    "/loso",
    "/scenario?kind=delhi_sector",
    "/scenario?kind=district",
    "/dss",
]

#: Filename for a route. "/forecast?horizon=24" -> "forecast__horizon=24.json".
def slug(route: str) -> str:
    s = route.lstrip("/").replace("/", "__").replace("?", "__")
    return (s or "index") + ".json"


def fetch(base: str, route: str, timeout: float) -> tuple[object | None, str]:
    try:
        with urllib.request.urlopen(base.rstrip("/") + route, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")), "ok"
    except urllib.error.HTTPError as e:
        # A 404 on an optional route is a real answer: that panel has nothing to show
        # and the dashboard already renders an empty state for it. Record it as such
        # rather than aborting the whole bundle.
        return None, f"HTTP {e.code}"
    except Exception as e:                       # noqa: BLE001
        return None, str(e)[:120]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8100",
                    help="a running VayuChakra API, at full resolution")
    ap.add_argument("--out", default="data/snapshot")
    ap.add_argument("--timeout", type=float, default=900.0,
                    help="the first call builds the forecast and takes minutes")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print(f"[snapshot] capturing {len(ROUTES)} routes from {args.base}")
    manifest: dict[str, object] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base": args.base,
        "routes": {},
    }
    ok = 0
    for route in ROUTES:
        t0 = time.time()
        payload, status = fetch(args.base, route, args.timeout)
        took = time.time() - t0
        path = out / slug(route)
        if payload is None:
            # A route can fail because the pipeline is broken, or because this machine
            # legitimately cannot reach something another one could. The MoES DSS
            # workbook is the standing example: it is third-party research output that
            # we cite and deliberately do not redistribute, so it exists on a developer
            # machine and never on a CI runner, and /dss and /scenario answer 503 there.
            #
            # The old behaviour recorded `file: None` and dropped the route from the
            # manifest. The previously captured file stayed on disk and the API kept
            # serving it - it globs the directory rather than reading the manifest - so
            # the manifest became a document that disagreed with what the service
            # actually returned. Worse, a CI check reading the manifest would reject an
            # entire healthy bundle over a dependency that was never expected to be
            # present.
            #
            # So a retained file is reported as retained, with the reason and the age of
            # what is being kept. That is the honest description: this run did not
            # refresh the route, and the bundle still serves the last good capture.
            if path.exists():
                age_h = (time.time() - path.stat().st_mtime) / 3600.0
                print(f"  {route:34s} {status:12s} {took:6.1f}s  RETAINED "
                      f"(previous capture, {age_h:.0f} h old)")
                manifest["routes"][route] = {
                    "file": path.name, "status": "retained",
                    "bytes": path.stat().st_size,
                    "reason": status,
                    "retained_age_hours": round(age_h, 1)}
            else:
                print(f"  {route:34s} {status:12s} {took:6.1f}s  NOT CAPTURED")
                manifest["routes"][route] = {"file": None, "status": status}
            continue
        path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        kb = path.stat().st_size / 1024
        print(f"  {route:34s} {status:12s} {took:6.1f}s  {kb:8.0f} KB -> {path.name}")
        manifest["routes"][route] = {"file": path.name, "status": "ok",
                                     "bytes": path.stat().st_size}
        ok += 1

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    total = sum(p.stat().st_size for p in out.glob("*.json")) / 1024 / 1024
    print(f"\n[snapshot] {ok}/{len(ROUTES)} routes captured, {total:.1f} MB -> {out}")
    if ok < len(ROUTES):
        print("[snapshot] some routes are missing. The hosted dashboard will show their")
        print("[snapshot] empty states, which is honest but probably not what you meant.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
