"""Ground truth — CPCB station observations, live and historical.

Everything else in this project is a model. This module is the only place real
measurements enter, so it is the only thing that can say whether any of the rest is
right. Two sources, chosen for different jobs:

**The OpenAQ v3 API** for live and recent readings. Low latency, one request per
sensor, needs a key.

**The OpenAQ S3 open-data archive** for bulk history — daily gzipped CSV per station,
no key, no rate limit. Downloading a season of 130 stations through the API would be
tens of thousands of paged requests; through S3 it is a few thousand small files that
parallelise cleanly.

TWO MEASURED FACTS THAT SHAPE THIS MODULE
------------------------------------------
1. **The v3 API's date filters do not work.** `datetime_from` / `datetime_to` on
   `/sensors/{id}/hours` return `found: 0` for a window that demonstrably holds data;
   `date_from` is ignored entirely and silently serves the earliest records instead.
   So historical retrieval never uses filters — it uses S3.
2. **The S3 archive has a 2019-2024 gap** for CPCB stations. Checked across Anand
   Vihar, R K Puram and Punjabi Bagh: years present are 2015-2018 and 2025-2026, with
   nothing between. This is systemic, not per-station, and it is why the DSS window
   (Oct 2021 - Feb 2022) cannot be scored against observations from this source. See
   D-018 for how validation is arranged around it.
"""
from __future__ import annotations

import hashlib
import csv
import gzip
import io
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pandas as pd

from . import config as C
from . import net

API = "https://api.openaq.org/v3"
S3 = "https://openaq-data-archive.s3.amazonaws.com"

#: Pollutants we model or use as predictors. `no`/`nox` are dropped: coverage is half
#: that of no2 and they add nothing the no2 series does not already carry.
POLLUTANTS = ("pm25", "pm10", "o3", "no2", "so2", "co")

#: Station-side meteorology. Kept separate from the pollutants because it is used to
#: sanity-check the gridded meteorology rather than as a target.
STATION_MET = ("temperature", "relativehumidity", "wind_speed", "wind_direction")

WANTED = set(POLLUTANTS) | set(STATION_MET)

#: Physically impossible readings, used to drop instrument faults before they reach a
#: training set. A negative concentration and a 20,000 ug/m3 PM2.5 are both equipment
#: telling us it is broken, and a single one of them can move a station's mean for a day.
PLAUSIBLE = {
    "pm25": (0.0, 1500.0), "pm10": (0.0, 3000.0), "o3": (0.0, 500.0),
    "no2": (0.0, 500.0), "so2": (0.0, 500.0), "co": (0.0, 50.0),
    "temperature": (-10.0, 55.0), "relativehumidity": (0.0, 100.0),
    "wind_speed": (0.0, 40.0), "wind_direction": (0.0, 360.0),
}


@dataclass
class Station:
    id: int
    name: str
    lat: float
    lon: float
    provider: str
    first: str | None
    last: str | None
    sensors: dict           # parameter -> sensor id


def _headers() -> dict:
    return {"X-API-Key": C.OPENAQ_API_KEY} if C.OPENAQ_API_KEY else {}


# ─── Discovery ───────────────────────────────────────────────────────────────
def discover_stations(limit_pages: int = 6) -> list[Station]:
    """Every monitoring location inside the NCR box.

    Measured 2026-09-04: 161 locations, of which 101 are CPCB and 31 caaqm — 132
    government stations. O3 coverage (224 sensors) is nearly as good as PM2.5 (238),
    which is what makes a separate ozone head trainable rather than aspirational.
    """
    if not C.OPENAQ_API_KEY:
        print("[obs] no OPENAQ_API_KEY - station discovery unavailable")
        return []
    bbox = f"{C.LON_MIN},{C.LAT_MIN},{C.LON_MAX},{C.LAT_MAX}"
    out: list[Station] = []
    for page in range(1, limit_pages + 1):
        url = net.build_url(f"{API}/locations",
                            {"bbox": bbox, "limit": 1000, "page": page})
        payload = net.get_json(url, headers=_headers(), ttl=C.CACHE_TTL_ARCHIVE)
        results = (payload or {}).get("results") or []
        for r in results:
            coords = r.get("coordinates") or {}
            lat, lon = coords.get("latitude"), coords.get("longitude")
            if lat is None or lon is None:
                continue
            sensors = {s["parameter"]["name"]: s["id"]
                       for s in (r.get("sensors") or [])
                       if s.get("parameter", {}).get("name") in WANTED}
            if not sensors:
                continue
            out.append(Station(
                id=int(r["id"]), name=str(r.get("name") or r["id"]),
                lat=float(lat), lon=float(lon),
                provider=str((r.get("provider") or {}).get("name") or "unknown"),
                first=((r.get("datetimeFirst") or {}) or {}).get("utc"),
                last=((r.get("datetimeLast") or {}) or {}).get("utc"),
                sensors=sensors))
        if len(results) < 1000:
            break
    return out


# ─── S3 archive ──────────────────────────────────────────────────────────────
def _s3_list(prefix: str) -> list[str]:
    url = (f"{S3}/?list-type=2&delimiter=/&max-keys=1000&prefix="
           + urllib.parse.quote(prefix, safe=""))
    body = net.get_text(url, ttl=C.CACHE_TTL_ARCHIVE)
    if not body:
        return []
    return re.findall(r"<Prefix>([^<]*?)</Prefix>", body)[1:]


def archive_years(location_id: int) -> list[int]:
    """Which years this station actually has in the S3 archive.

    Worth calling before a bulk pull: per-station year gaps mean an optimistic date
    range can spend thousands of requests discovering nothing exists.
    """
    years = []
    for p in _s3_list(f"records/csv.gz/locationid={location_id}/"):
        m = re.search(r"year=(\d{4})", p)
        if m:
            years.append(int(m.group(1)))
    return sorted(years)


def archive_months(location_id: int, year: int) -> list[int]:
    """Which months of a year this station has.

    Year-level coverage is too coarse to plan a pull with. A station can advertise
    "2025" while holding only February and March, and a naive request then spends 300
    downloads to discover 60 days of data. Checking months costs one listing per
    station-year and typically removes most of the wasted requests.
    """
    months = []
    for p in _s3_list(f"records/csv.gz/locationid={location_id}/year={year}/"):
        m = re.search(r"month=(\d{2})", p)
        if m:
            months.append(int(m.group(1)))
    return sorted(months)


def available_days(location_id: int, start: str, end: str) -> list[pd.Timestamp]:
    """Days within [start, end] that this station plausibly has, by month listing."""
    days = pd.date_range(start, end, freq="D", tz="UTC")
    have: dict[int, set[int]] = {}
    for year in sorted({d.year for d in days}):
        have[year] = set(archive_months(location_id, year))
    return [d for d in days if d.month in have.get(d.year, set())]


def _fetch_day(location_id: int, day: pd.Timestamp) -> list[dict]:
    key = (f"records/csv.gz/locationid={location_id}/year={day:%Y}/month={day:%m}/"
           f"location-{location_id}-{day:%Y%m%d}.csv.gz")
    try:
        raw = urllib.request.urlopen(
            urllib.request.Request(f"{S3}/{key}", headers={"User-Agent": C.USER_AGENT}),
            timeout=C.HTTP_TIMEOUT).read()
        text = gzip.decompress(raw).decode("utf-8", "replace")
    except Exception:
        # A missing day is entirely normal - stations go offline. Not worth a warning
        # per file when a season pull touches thousands.
        return []
    rows = []
    try:
        for rec in csv.DictReader(io.StringIO(text)):
            param = rec.get("parameter")
            if param not in WANTED:
                continue
            try:
                value = float(rec["value"])
            except (TypeError, ValueError):
                continue
            rows.append({"station_id": int(rec["location_id"]), "parameter": param,
                         "datetime": rec["datetime"], "value": value,
                         "lat": float(rec["lat"]), "lon": float(rec["lon"])})
    except (csv.Error, KeyError, ValueError):
        return []
    return rows


def _archive_key(station_ids: list[int], start: str, end: str) -> str:
    """Stable short key for one archive request.

    Station order must not change the key, or the same request made twice would cache
    twice and hit neither.
    """
    raw = ",".join(str(i) for i in sorted(station_ids)) + f"|{start}|{end}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def fetch_archive(station_ids: list[int], start: str, end: str,
                  workers: int = 12, flush_every: int = 250) -> pd.DataFrame:
    """Hourly observations for a set of stations over a date range.

    Downloads one gzipped CSV per station-day in parallel, filters implausible values,
    then averages the sub-hourly records up to hourly means.

    **Aggregated in batches rather than all at once.** The archive stores 15-minute
    records, so a season for 60 stations is several million dicts held simultaneously
    before the first DataFrame is built — which ran the machine out of memory. Reducing
    each batch to hourly means as it arrives cuts peak memory by roughly the sampling
    ratio and keeps it flat in the number of days requested, at the cost of a final
    regroup to merge batch boundaries.
    """
    # The download is the expensive half of the whole project: 48,000 gzipped
    # station-days for the five-winter window, about 80 minutes at the archive's rate.
    # The assembled panel is cached further up, but that cache is only written once
    # assembly SUCCEEDS, so a failure after the fetch, which is exactly what an
    # out-of-memory error in add_lags is, threw away the 80 minutes and made every
    # attempt at a fix cost another 80. Caching the hourly frame separates the two:
    # download once, then iterate on assembly for the price of a parquet read.
    cache = C.CACHE / f"obs_archive_{_archive_key(station_ids, start, end)}.parquet"
    if cache.exists():
        try:
            df = pd.read_parquet(cache)
            print(f"[obs] cached archive {cache.name}: {len(df):,} station-hours")
            return df
        except Exception as exc:                       # a truncated or partial write
            print(f"[obs] cache {cache.name} unreadable ({exc}); refetching")
            cache.unlink(missing_ok=True)

    # Ask each station which months it actually holds before requesting any day of
    # them. One listing per station-year replaces up to 365 futile downloads.
    jobs: list[tuple[int, pd.Timestamp]] = []
    with ThreadPoolExecutor(max_workers=min(workers, 12)) as pool:
        for sid, days_for in zip(
                station_ids,
                pool.map(lambda s: available_days(s, start, end), station_ids)):
            jobs.extend((sid, d) for d in days_for)
    if not jobs:
        return pd.DataFrame()

    parts: list[pd.DataFrame] = []
    buffer: list[dict] = []

    def flush() -> None:
        nonlocal buffer
        if not buffer:
            return
        piece = _to_hourly(pd.DataFrame(buffer))
        if not piece.empty:
            parts.append(piece)
        buffer = []

    # A season for 40 stations is ~20,000 small files and takes tens of minutes. Silence
    # for that long is indistinguishable from a hang, so report progress and a rate.
    import time as _time
    started = _time.time()
    total = len(jobs)
    print(f"[obs] {total:,} station-days to fetch across {len(station_ids)} stations")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, chunk in enumerate(pool.map(lambda a: _fetch_day(*a), jobs), 1):
            buffer.extend(chunk)
            if i % flush_every == 0:
                flush()
                rate = i / max(_time.time() - started, 1e-6)
                eta = (total - i) / rate if rate > 0 else float("nan")
                print(f"[obs]   {i:,}/{total:,} ({100 * i / total:4.1f}%) "
                      f"· {rate:.0f} files/s · ~{eta / 60:.0f} min left", flush=True)
    flush()
    print(f"[obs] done in {(_time.time() - started) / 60:.1f} min")

    if not parts:
        return pd.DataFrame()
    combined = pd.concat(parts, ignore_index=True)

    # A batch boundary can split one station-hour across two parts, giving duplicate
    # (station, time) keys whose values are each a partial mean. Regrouping merges them;
    # without it a downstream join would silently fan out rows.
    numeric = [c for c in combined.columns if c not in ("station_id", "time")]
    combined = (combined.groupby(["station_id", "time"], as_index=False)[numeric]
                        .mean(numeric_only=True))
    combined = combined.sort_values(["station_id", "time"]).reset_index(drop=True)

    # Write via a temporary name and rename, so an interrupted write cannot leave a
    # half-file that a later run would read as complete.
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".parquet.tmp")
        combined.to_parquet(tmp, index=False)
        tmp.replace(cache)
        print(f"[obs] cached -> {cache.name}")
    except Exception as exc:
        print(f"[obs] could not cache the archive ({exc}); continuing")
    return combined


def _to_hourly(df: pd.DataFrame) -> pd.DataFrame:
    """Sub-hourly records -> hourly means, one column per pollutant, UTC."""
    if df.empty:
        return df
    # Archive timestamps carry +05:30; parse the offset rather than assuming UTC.
    df["time"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce", format="mixed")
    df = df.dropna(subset=["time"])

    lo = df["parameter"].map(lambda p: PLAUSIBLE.get(p, (float("-inf"), float("inf")))[0])
    hi = df["parameter"].map(lambda p: PLAUSIBLE.get(p, (float("-inf"), float("inf")))[1])
    df = df[(df["value"] >= lo) & (df["value"] <= hi)]
    if df.empty:
        return pd.DataFrame()

    df["time"] = df["time"].dt.floor("h")
    grouped = (df.groupby(["station_id", "time", "parameter"])
                 .agg(value=("value", "mean"), lat=("lat", "first"), lon=("lon", "first"))
                 .reset_index())
    wide = grouped.pivot_table(index=["station_id", "time"], columns="parameter",
                               values="value", aggfunc="mean").reset_index()
    coords = grouped.groupby("station_id")[["lat", "lon"]].first().reset_index()
    wide = wide.merge(coords, on="station_id", how="left")
    wide.columns.name = None
    for p in WANTED:
        if p not in wide.columns:
            wide[p] = pd.NA
    return wide.sort_values(["station_id", "time"]).reset_index(drop=True)


# ─── Live ────────────────────────────────────────────────────────────────────
def fetch_latest(stations: list[Station], workers: int = 6) -> pd.DataFrame:
    """Most recent reading per station, for the live layer.

    Uses `/locations/{id}/latest`, which returns **every sensor at a location in one
    response**. The obvious alternative — one request per sensor — is roughly 800
    requests for the NCR network and reliably earns an HTTP 429 partway through,
    leaving a partial picture that looks like a quiet day rather than a throttled one.
    One request per location is about 130, which the rate limit tolerates.

    Uses the API rather than S3 because the archive lags by a day or more, which is
    useless for a "what is the air doing right now" panel.
    """
    if not C.OPENAQ_API_KEY or not stations:
        return pd.DataFrame()

    # sensor id -> (station, parameter), so the flat `latest` payload can be resolved
    # back to what each reading actually is.
    lookup: dict[int, tuple[Station, str]] = {}
    for st in stations:
        for param, sid in st.sensors.items():
            if param in POLLUTANTS:
                lookup[int(sid)] = (st, param)

    def one(st: Station) -> list[dict]:
        payload = net.get_json(net.build_url(f"{API}/locations/{st.id}/latest", {"limit": 100}),
                               headers=_headers(), ttl=C.CACHE_TTL_OBSERVATION)
        got = []
        for r in (payload or {}).get("results") or []:
            sid = r.get("sensorsId")
            hit = lookup.get(int(sid)) if sid is not None else None
            if hit is None:
                continue
            station, param = hit
            val = r.get("value")
            period = (r.get("datetime") or {}).get("utc")
            if val is None or period is None:
                continue
            lo, hi = PLAUSIBLE.get(param, (float("-inf"), float("inf")))
            try:
                fval = float(val)
            except (TypeError, ValueError):
                continue
            if not (lo <= fval <= hi):
                continue
            got.append({"station_id": station.id, "parameter": param,
                        "datetime": period, "value": fval,
                        "lat": station.lat, "lon": station.lon})
        return got

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for chunk in pool.map(one, stations):
            rows.extend(chunk)
    return _to_hourly(pd.DataFrame(rows)) if rows else pd.DataFrame()


def stations_frame(stations: list[Station]) -> pd.DataFrame:
    return pd.DataFrame([{
        "station_id": s.id, "name": s.name, "lat": s.lat, "lon": s.lon,
        "provider": s.provider, "first": s.first, "last": s.last,
        "n_sensors": len(s.sensors),
        "has_pm25": int("pm25" in s.sensors), "has_o3": int("o3" in s.sensors),
    } for s in stations])
