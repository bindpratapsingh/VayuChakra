"""Chemistry prior from CAMS — the "coupled framework" the problem statement asks for.

The PS says to *"leverage advanced weather-chemistry models (such as WRF-Chem or
similar open-source coupled frameworks)"*. We cannot run WRF-Chem: it needs a Linux
cluster, an MPI/netCDF stack, and a district emission inventory we do not have. What we
can do is **consume the output of one that is already running operationally**.

CAMS — the Copernicus Atmosphere Monitoring Service, ECMWF's IFS-COMPO — is exactly
that: a global coupled meteorology-chemistry model, run four times a day, with online
aerosol. Open-Meteo redistributes it with no API key. It gives us:

  * **PM2.5, PM10, O3, NO2, SO2, CO** — the chemistry the PS names, O3 as its own
    field rather than folded into an index;
  * **aerosol optical depth** — the single variable the chemistry-to-meteorology
    feedback needs, and the reason this module exists at all;
  * **dust** — separable from combustion aerosol, which matters in a city where
    spring dust storms and winter smoke look alike in a PM10 number.

WHAT CAMS IS NOT
----------------
It is a global model at ~40 km. Over Delhi it is biased low and poorly correlated with
station observations — we measured r = 0.085 and a bias of −61.7 against 62 CPCB
stations on the sibling project. That is not a reason to discard it; it is the reason
the machine-learning layer exists. CAMS supplies the *physics and the regional
gradient*; the stations supply the *local truth*; the model learns the mapping. Used
as one feature among many, a biased-but-physical prior is worth a great deal. Used
raw, it would be worse than useless.

COVERAGE LIMIT (measured 2026-09-04)
------------------------------------
The archive begins around mid-August 2022. The MoES DSS workbook we validate against
covers Oct 2021 – Feb 2022, so that window has **no** chemistry prior. See D-012:
the DSS comparison runs a reduced configuration and says so.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import config as C
from . import net
from .grid import Cell

AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

#: Requested hourly fields. Names on the left are CAMS/Open-Meteo's; we rename to the
#: short forms used everywhere else in this project on the way out.
AQ_VARS: tuple[str, ...] = (
    "pm2_5",
    "pm10",
    "ozone",
    "nitrogen_dioxide",
    "sulphur_dioxide",
    "carbon_monoxide",
    "aerosol_optical_depth",
    "dust",
    "uv_index",
    # Clear-sky UV is what makes the photolysis model independently checkable: the ratio
    # uv_index / uv_index_clear_sky is a MEASURED actinic attenuation factor, derived by
    # a different provider from a different calculation than ours. Without it, validating
    # the photolysis attenuation would be circular.
    "uv_index_clear_sky",
)

RENAME = {
    "pm2_5": "cams_pm25",
    "pm10": "cams_pm10",
    "ozone": "cams_o3",
    "nitrogen_dioxide": "cams_no2",
    "sulphur_dioxide": "cams_so2",
    "carbon_monoxide": "cams_co",
    "aerosol_optical_depth": "cams_aod",
    "dust": "cams_dust",
    "uv_index": "cams_uv",
    "uv_index_clear_sky": "cams_uv_clear_sky",
}

OUT_COLS = tuple(RENAME.values())

#: Batch size for multi-point requests, matching the meteorology fetcher.
BATCH = 100

#: CAMS on Open-Meteo starts here. Requests before it return a valid time axis with
#: every value null, which is worse than an error because it looks like success.
ARCHIVE_START = "2022-08-15"


@dataclass
class ChemResult:
    frame: pd.DataFrame
    ok_cells: int
    failed_cells: int
    note: str = ""

    @property
    def available(self) -> bool:
        return not self.frame.empty


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _rows(item: dict, cell: Cell) -> list[dict]:
    hourly = (item or {}).get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return []
    out = []
    for i, ts in enumerate(times):
        row = {"cell_id": cell.cell_id, "time": ts}
        for src, dst in RENAME.items():
            series = hourly.get(src)
            row[dst] = series[i] if series is not None and i < len(series) else None
        out.append(row)
    return out


def _fetch(cells: list[Cell], params: dict, ttl: float) -> ChemResult:
    frames, ok, bad = [], 0, 0
    for batch in _chunks(cells, BATCH):
        q = dict(params)
        q["latitude"] = ",".join(str(c.lat) for c in batch)
        q["longitude"] = ",".join(str(c.lon) for c in batch)
        q["hourly"] = ",".join(AQ_VARS)
        q["timezone"] = "UTC"
        q["domains"] = "cams_global"
        payload = net.get_json(net.build_url(AQ_URL, q), ttl=ttl)
        if payload is None:
            bad += len(batch)
            continue
        items = payload if isinstance(payload, list) else [payload]
        if len(items) != len(batch):
            # Results align to cells positionally; a length mismatch makes that unsafe.
            print(f"[chem] batch mismatch: {len(items)} results for {len(batch)} cells")
            bad += len(batch)
            continue
        for item, cell in zip(items, batch):
            r = _rows(item, cell)
            if r:
                frames.append(pd.DataFrame(r))
                ok += 1
            else:
                bad += 1

    if not frames:
        return ChemResult(pd.DataFrame(), ok, bad, "no CAMS rows returned")

    df = pd.concat(frames, ignore_index=True)
    df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
    df = df.dropna(subset=["time"])
    for col in OUT_COLS:
        df[col] = pd.to_numeric(df.get(col), errors="coerce")

    # An all-null frame is the signature of an out-of-coverage archive request. Say so
    # loudly rather than letting a silent wall of NaN propagate into the feature matrix.
    filled = df["cams_pm25"].notna().mean() if len(df) else 0.0
    note = "" if filled > 0.05 else (
        f"CAMS returned {filled:.0%} non-null PM2.5 — outside archive coverage "
        f"(starts {ARCHIVE_START}). Chemistry prior unavailable for this window."
    )
    if note:
        print(f"[chem] {note}")
    return ChemResult(df.sort_values(["cell_id", "time"]).reset_index(drop=True),
                      ok, bad, note)


def fetch_forecast(cells: list[Cell], days: int = 4) -> ChemResult:
    """Forward chemistry prior for the grid."""
    return _fetch(cells, {"forecast_days": days, "past_days": 2}, C.CACHE_TTL_FORECAST)


def fetch_archive(cells: list[Cell], start: str, end: str) -> ChemResult:
    """Past chemistry for a hindcast window. Returns empty before ARCHIVE_START."""
    if start < ARCHIVE_START:
        msg = (f"requested {start} but CAMS archive starts {ARCHIVE_START}; "
               f"returning empty rather than a wall of nulls")
        print(f"[chem] {msg}")
        return ChemResult(pd.DataFrame(), 0, len(cells), msg)
    return _fetch(cells, {"start_date": start, "end_date": end}, C.CACHE_TTL_ARCHIVE)


def calibrate_aod_pm25(df: pd.DataFrame) -> dict:
    """Fit AOD = a * PM2.5**b on CAMS's own paired output.

    Step one of the feedback chain needs to turn a predicted PM2.5 into an optical
    depth. Rather than assume a mass-extinction efficiency from the literature, we fit
    the relation on data: CAMS reports both quantities for the same place and hour, and
    it is an actual radiative-transfer model, so its internal AOD/PM2.5 relation is
    physically consistent by construction.

    A power law rather than a straight line because the relation saturates — doubling
    the mass does not double the optical depth once particles start shading each other,
    and humidity swells particles non-linearly.

    Returns the fitted coefficients plus the sample size and fit quality, so a caller
    can refuse a bad fit instead of silently using it.
    """
    import numpy as np

    sub = df[["cams_pm25", "cams_aod"]].dropna()
    sub = sub[(sub["cams_pm25"] > 1.0) & (sub["cams_aod"] > 0.01)]
    if len(sub) < 50:
        return {"ok": False, "n": len(sub), "reason": "insufficient paired samples"}

    x = np.log(sub["cams_pm25"].to_numpy())
    y = np.log(sub["cams_aod"].to_numpy())
    b, log_a = np.polyfit(x, y, 1)
    pred = log_a + b * x
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return {"ok": bool(r2 > 0.3), "a": float(np.exp(log_a)), "b": float(b),
            "r2": float(r2), "n": int(len(sub))}
