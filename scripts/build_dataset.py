"""Build the training panel and cache it to parquet.

Run:  python scripts/build_dataset.py [--start 2025-01-01] [--end 2026-08-31]
                                      [--stations 60] [--name train_panel]

Downloads observations from the OpenAQ S3 archive, meteorology and the CAMS chemistry
prior from Open-Meteo, joins them, and writes one parquet file. Everything is cached on
disk, so a re-run after an interruption is cheap and a re-run with no changes is free.
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vayuchakra import config as C          # noqa: E402
from vayuchakra import dataset, grid, obs    # noqa: E402


def pick_stations(want: int, start: str, end: str,
                  min_months: int | None = None) -> list[obs.Station]:
    """Stations with real coverage of the window, richest and nearest Delhi first.

    Coverage is checked at **month** granularity, not year. A station can advertise
    "2025" while holding only February and March, and a year-level filter then admits
    it and spends 300 downloads discovering 60 days of data. Measured across central
    Delhi, month listings separate stations with continuous Feb-2025-to-Aug-2026
    records from ones with two months, which a year check cannot do.

    Ranked by months held first, then by distance to the city centre: a complete record
    20 km out is worth more to a learner than a fragmentary one in the middle.
    """
    stations = obs.discover_stations()
    print(f"[build] {len(stations)} stations in the NCR box")
    span = pd.date_range(start, end, freq="MS")
    wanted = {(d.year, d.month) for d in span}
    # Scale the coverage bar to the window. A fixed floor of 8 months is impossible to
    # meet on a 4-month request, so every station was rejected and the build reported
    # "nothing to do" for what was actually a misconfigured threshold.
    if min_months is None:
        min_months = max(2, round(len(wanted) * 0.6))

    def check(s: obs.Station):
        try:
            have = set()
            for year in sorted({y for y, _ in wanted}):
                have |= {(year, m) for m in obs.archive_months(s.id, year)}
            return s, have & wanted
        except Exception:
            return s, set()

    scored: list[tuple[int, float, obs.Station]] = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        for s, have in pool.map(check, stations):
            if "pm25" not in s.sensors or len(have) < min_months:
                continue
            d = grid.haversine_km(s.lat, s.lon, C.DELHI_LAT, C.DELHI_LON)
            scored.append((len(have), d, s))
    scored.sort(key=lambda t: (-t[0], t[1]))
    chosen = [s for _, _, s in scored[:want]]
    print(f"[build] {len(scored)} stations hold >={min_months} of "
          f"{len(wanted)} months with PM2.5; taking {len(chosen)}")
    for months, dist, s in scored[:want][:6]:
        print(f"[build]   {months:2d} months  {dist:5.1f} km  {s.name[:44]}")
    return chosen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--end", default="2026-08-31")
    ap.add_argument("--stations", type=int, default=60)
    ap.add_argument("--name", default="train_panel")
    ap.add_argument("--no-chem", action="store_true",
                    help="skip the CAMS prior (the DSS-window configuration)")
    args = ap.parse_args()

    t0 = time.time()

    stations = pick_stations(args.stations, args.start, args.end)
    if not stations:
        print("[build] no stations matched - nothing to do")
        return 1

    panel = dataset.build_panel(stations, args.start, args.end,
                               with_chem=not args.no_chem, cache_name=args.name)
    if panel.empty:
        print("[build] empty panel")
        return 1

    print(f"\n[build] done in {time.time() - t0:.0f}s")
    print(f"[build] rows {len(panel):,}  stations {panel['station_id'].nunique()}  "
          f"columns {len(panel.columns)}")
    print(f"[build] window {panel['time'].min()} -> {panel['time'].max()}")
    for col in ("pm25", "o3", "no2", "cams_pm25", "mixing_depth_m", "ventilation_coeff"):
        if col in panel.columns:
            print(f"[build]   {col:18s} {100 * panel[col].notna().mean():5.1f}% populated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
