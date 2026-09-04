"""Reader for the MoES/IITM WRF-Chem Decision Support System output.

WHAT THIS FILE IS AND WHERE IT CAME FROM
-----------------------------------------
`DSS-Analysis-JAMES.xlsx` is output from the **operational Decision Support System**
run by IITM Pune for the Ministry of Earth Sciences, described in a JAMES paper whose
authors span IITM, **NCMRWF**, NCAR, TERI, IMD, C-DAC and IISc. NCMRWF is the
department that issued the problem statement we are answering.

**It is a third-party research asset.** It is read from the sibling workspace, never
copied into this repository, never redistributed, and always cited. Nothing here is
our model output and nothing may be presented as such.

WHY IT MATTERS TO US
--------------------
It gives three things no amount of our own compute could produce:

1. **A forecast archive** — 3,488 hourly Delhi PM2.5 forecasts at Day 1 to Day 5 lead
   times, Oct 2021 to Feb 2022. A full pollution season from the operational system.
   This is our benchmark: not "is our model good in the abstract" but "how does it
   compare with the system the ministry actually runs".
2. **Physics-derived source apportionment** — 147 daily rows splitting Delhi's PM2.5
   across eight local sectors, stubble burning, and 19 NCR districts. Ground truth of a
   kind statistical attribution can never generate for itself.
3. **Emission-reduction scenarios** — 3,552 hourly rows at 20% and 40% cuts for every
   district and Delhi sector, which turns a priority ranking into a quantified
   "cut transport 20% and PM2.5 falls by X".

WHAT IT IS NOT
--------------
Model output, not observation. City-level, not ward-level. A specific past season, not
a climatology. Every number drawn from it is reported as "the MoES DSS says", never as
measured truth.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import config as C

SHEET_FORECAST = "Model forecast"
SHEET_APPORTION = "Model source apportionment"
SHEET_SCENARIO = "Model Scenarios"

#: The workbook's own column spellings, several of which are misspelled. They are
#: matched verbatim rather than corrected, because a "helpful" correction here would
#: silently miss the column and return NaN.
DELHI_SECTORS = {
    "Delhi Transport": "Transport",
    "Delhi perpheral Indust": "Peripheral industry",
    "Delhi Residential": "Residential",
    "Delhi Construction": "Construction",
    "Delhi Waste Burning": "Waste burning",
    "Delhi Road dust": "Road dust",
    "Delhi Energy": "Energy",
    "Delhi Other sectors": "Other sectors",
}

DISTRICT_COLUMNS = (
    "Jhajjar", "Gurgaon", "Ghazibad", "Gautam Buddha Nagar", "Faridabad", "Rohtak",
    "Sonipat", "Panipat", "Bagpat", "Karnal", "Muzzafarnagar", "Meeerut",
    "Bulandshar", "Bharatpur", "Alwar", "Mahendragarh", "Raweri", "Bhiwani", "Jind",
)

STUBBLE_COLUMN = "Stubble burning"
OTHER_COLUMN = "Other regions"

#: Scenario suffixes: `_80` is the run with emissions at 80% of base (a 20% cut),
#: `_60` is a 40% cut. Reading these backwards would invert every policy conclusion.
SCENARIO_LEVELS = {"80": 0.20, "60": 0.40}


def available() -> bool:
    return C.DSS_XLSX.exists()


def _read(sheet: str) -> pd.DataFrame:
    if not available():
        print(f"[dss] workbook not found at {C.DSS_XLSX}")
        return pd.DataFrame()
    try:
        return pd.read_excel(C.DSS_XLSX, sheet_name=sheet)
    except Exception as exc:
        print(f"[dss] failed to read '{sheet}': {exc}")
        return pd.DataFrame()


# ─── Sheet 1: the forecast archive ───────────────────────────────────────────
def forecast_archive() -> pd.DataFrame:
    """Hourly Delhi PM2.5 forecasts at Day 1-5 lead times.

    The sheet stores Year/Month/Day/Local time as separate numeric columns and writes
    missing leads as the *string* "NaN", which pandas keeps as text — so a naive
    `.mean()` silently skips them and a naive `.astype(float)` raises. Both are handled
    here rather than at every call site.

    Local time is IST; converted to UTC so it joins with everything else.
    """
    raw = _read(SHEET_FORECAST)
    if raw.empty:
        return raw

    out = pd.DataFrame()
    stamp = pd.to_datetime({
        "year": pd.to_numeric(raw["Year"], errors="coerce"),
        "month": pd.to_numeric(raw["Month"], errors="coerce"),
        "day": pd.to_numeric(raw["Day"], errors="coerce"),
        "hour": pd.to_numeric(raw["Local time"], errors="coerce"),
    }, errors="coerce")
    # IST is UTC+5:30, so an integer IST hour becomes :30 past the hour in UTC. Every
    # observation series in this project is floored to the hour, so leaving the offset
    # in place makes the two impossible to join — a merge on valid_time returned ZERO
    # rows and the head-to-head table came out silently empty rather than erroring.
    # Floor to the hour, matching how observations are binned.
    out["time"] = (stamp.dt.tz_localize("Asia/Kolkata", ambiguous="NaT",
                                        nonexistent="NaT")
                        .dt.tz_convert("UTC").dt.floor("h"))

    for day in range(1, 6):
        col = f"Day {day}"
        if col in raw.columns:
            out[f"dss_day{day}"] = pd.to_numeric(raw[col], errors="coerce")

    out = out.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
    return out


def forecast_as_valid_time(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Reshape the archive from issue-time rows into (valid_time, lead_hours) pairs.

    The sheet is indexed by the hour the forecast was **made**, with a column per lead
    day. To score it against observations we need the hour each value is **valid for**,
    which is issue time plus the lead. Getting this backwards would shift every DSS
    number by one to five days and produce a comparison that looks plausible and is
    entirely wrong.
    """
    src = forecast_archive() if df is None else df
    if src.empty:
        return src
    frames = []
    for day in range(1, 6):
        col = f"dss_day{day}"
        if col not in src.columns:
            continue
        piece = pd.DataFrame({
            "valid_time": src["time"] + pd.Timedelta(days=day),
            "issue_time": src["time"],
            "lead_hours": day * 24,
            "dss_pm25": src[col],
        })
        frames.append(piece.dropna(subset=["dss_pm25"]))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values(
        ["valid_time", "lead_hours"]).reset_index(drop=True)


# ─── Sheet 2: source apportionment ───────────────────────────────────────────
@dataclass
class Apportionment:
    frame: pd.DataFrame
    sectors: list[str]
    districts: list[str]

    def shares(self) -> pd.DataFrame:
        """Each contributor as a fraction of that day's modelled total."""
        cols = self.sectors + self.districts + ["stubble_burning", "other_regions"]
        cols = [c for c in cols if c in self.frame.columns]
        total = self.frame[cols].sum(axis=1).replace(0, np.nan)
        out = self.frame[["date"]].copy()
        for c in cols:
            out[c] = self.frame[c] / total
        out["total_pm25"] = total
        return out

    def mean_shares(self) -> dict:
        s = self.shares()
        cols = [c for c in s.columns if c not in ("date", "total_pm25")]
        return {c: round(float(s[c].mean()), 4) for c in cols}


def apportionment() -> Apportionment:
    """Daily PM2.5 contributions by Delhi sector, NCR district and stubble burning."""
    raw = _read(SHEET_APPORTION)
    if raw.empty:
        return Apportionment(pd.DataFrame(), [], [])

    out = pd.DataFrame({"date": pd.to_datetime(raw["Date"], errors="coerce")})
    sectors, districts = [], []
    for src, tidy in DELHI_SECTORS.items():
        if src in raw.columns:
            key = "delhi_" + tidy.lower().replace(" ", "_")
            out[key] = pd.to_numeric(raw[src], errors="coerce")
            sectors.append(key)
    for src in DISTRICT_COLUMNS:
        if src in raw.columns:
            key = src.lower().replace(" ", "_")
            out[key] = pd.to_numeric(raw[src], errors="coerce")
            districts.append(key)
    if STUBBLE_COLUMN in raw.columns:
        out["stubble_burning"] = pd.to_numeric(raw[STUBBLE_COLUMN], errors="coerce")
    if OTHER_COLUMN in raw.columns:
        out["other_regions"] = pd.to_numeric(raw[OTHER_COLUMN], errors="coerce")

    out = out.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    return Apportionment(out, sectors, districts)


# ─── Sheet 3: emission-reduction scenarios ───────────────────────────────────
def scenarios() -> pd.DataFrame:
    """Hourly PM2.5 response to 20% and 40% emission cuts, by district and sector.

    Long format: one row per timestamp per scenario, with the target parsed out of the
    column name (`DEL_TRA_80` -> Delhi transport, 20% cut; `GZB_60` -> Ghaziabad, 40%).
    """
    raw = _read(SHEET_SCENARIO)
    if raw.empty:
        return raw

    date = pd.to_datetime(raw["Date"], errors="coerce")
    if "Time" in raw.columns:
        # Time arrives as datetime.time; combining as strings avoids a dtype fight.
        time_str = raw["Time"].astype(str).str.slice(0, 8)
        stamp = pd.to_datetime(date.dt.strftime("%Y-%m-%d") + " " + time_str,
                               errors="coerce")
    else:
        stamp = date

    rows = []
    for col in raw.columns:
        if col in ("Date", "Time"):
            continue
        parts = str(col).split("_")
        if len(parts) < 2 or parts[-1] not in SCENARIO_LEVELS:
            continue
        level = parts[-1]
        if parts[0] == "DEL" and len(parts) == 3:
            target_kind, target = "delhi_sector", parts[1]
        else:
            target_kind, target = "district", parts[0]
        rows.append(pd.DataFrame({
            "time": stamp,
            "target_kind": target_kind,
            "target": target,
            "reduction": SCENARIO_LEVELS[level],
            "value": pd.to_numeric(raw[col], errors="coerce"),
        }))
    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True).dropna(subset=["time", "value"])
    return out.sort_values(["time", "target_kind", "target", "reduction"]).reset_index(drop=True)


def scenario_summary() -> pd.DataFrame:
    """Mean PM2.5 benefit per target per reduction level — the policy table.

    This is what turns an enforcement ranking into a decision: not "transport is
    ranked first" but "a 20% cut in Delhi transport removes X ug/m3 on an average day".
    """
    s = scenarios()
    if s.empty:
        return s
    g = (s.groupby(["target_kind", "target", "reduction"])["value"]
           .agg(mean_ugm3="mean", max_ugm3="max", n="count").reset_index())
    return g.sort_values(["target_kind", "mean_ugm3"], ascending=[True, False]).reset_index(drop=True)


def describe() -> dict:
    """One-call inventory of what the workbook actually contains."""
    if not available():
        return {"available": False, "path": str(C.DSS_XLSX)}
    fc = forecast_archive()
    ap = apportionment()
    sc = scenarios()
    out = {"available": True, "path": str(C.DSS_XLSX),
           "citation": ("MoES/IITM WRF-Chem Decision Support System (JAMES). "
                        "Third-party research output - cited, not redistributed.")}
    if not fc.empty:
        out["forecast"] = {
            "rows": int(len(fc)),
            "from": str(fc["time"].min()), "to": str(fc["time"].max()),
            "leads": [c for c in fc.columns if c.startswith("dss_day")],
            "day1_mean": round(float(fc["dss_day1"].mean()), 1) if "dss_day1" in fc else None,
        }
    if not ap.frame.empty:
        out["apportionment"] = {"rows": int(len(ap.frame)),
                                "sectors": len(ap.sectors), "districts": len(ap.districts),
                                "from": str(ap.frame["date"].min().date()),
                                "to": str(ap.frame["date"].max().date())}
    if not sc.empty:
        out["scenarios"] = {"rows": int(len(sc)),
                            "targets": int(sc["target"].nunique()),
                            "levels": sorted(sc["reduction"].unique().tolist())}
    return out
