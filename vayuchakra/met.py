"""Meteorology ingestion — the variables the coupling actually needs.

AirGrid fetched four surface variables: temperature, humidity, wind speed, wind
direction. That is enough to *correlate* weather with pollution and nothing like
enough to *couple* them. Coupling needs the vertical structure, because the two
mechanisms the problem statement names both live above the surface:

  * **the inversion** - a temperature profile that rises with height, which needs
    temperatures at pressure levels, not a thermometer at 2 m;
  * **the mixing depth** - boundary layer height, which sets the volume the day's
    emissions are diluted into and therefore the concentration.

Both are free from Open-Meteo, in the forecast API and in the ERA5 archive.
Verified 2026-09-04: PBL over Delhi ranged 15-840 m across the next 72 h, and
1680 m in the October 2021 archive.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pandas as pd

from . import config as C
from . import net
from .grid import Cell

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

#: Hourly fields requested from Open-Meteo.
#:
#: The pressure levels are chosen for Delhi's winter inversion, which is shallow.
#: 1000 hPa sits ~100 m up, 950 hPa ~550 m, 925 hPa ~780 m, 850 hPa ~1500 m. A nocturnal
#: surface inversion is usually capped below 925 hPa, so the 1000/950 pair is what
#: actually detects it; 850 hPa gives the free-atmosphere lapse rate above the mixed
#: layer, which the encroachment model needs.
HOURLY_VARS: tuple[str, ...] = (
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "surface_pressure",
    "precipitation",
    "cloud_cover",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_speed_100m",
    "wind_direction_100m",
    "boundary_layer_height",
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
    "temperature_1000hPa",
    "temperature_950hPa",
    "temperature_925hPa",
    "temperature_850hPa",
    "geopotential_height_1000hPa",
    "geopotential_height_950hPa",
    "geopotential_height_925hPa",
    "geopotential_height_850hPa",
    "wind_speed_925hPa",
    "wind_direction_925hPa",
)

#: What the ERA5 archive actually serves, measured 2026-09-04 rather than assumed.
#:
#: The archive returns a valid response for pressure-level fields but fills them with
#: nulls - `temperature_925hPa` came back 0/24 non-null on every date tested, from 2021
#: to 2026 - while `boundary_layer_height` came back 24/24. So the hindcast has a
#: mixing depth but no vertical temperature profile, and `indices.inversion()`
#: dispatches to its surface proxy accordingly.
#:
#: `soil_temperature_0_to_7cm` is added here as an extra surface-energy signal. It is
#: a damped layer average with real thermal inertia, so it is NOT a skin temperature
#: and NOT a clean inversion proxy (checked: it runs warmer than the air at night and
#: cooler at midday, the opposite phase to a skin temperature). It is kept as a
#: predictor, not as a diagnosis.
ARCHIVE_VARS: tuple[str, ...] = (
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "soil_temperature_0_to_7cm",
    "surface_pressure",
    "precipitation",
    "cloud_cover",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_speed_100m",
    "wind_direction_100m",
    "boundary_layer_height",
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
)

#: Union of both lists. Rows always carry every column either list can produce, so a
#: forecast frame and an archive frame have identical schemas and concatenate cleanly;
#: whichever fields the chosen endpoint does not serve simply arrive as NaN.
ALL_VARS: tuple[str, ...] = tuple(dict.fromkeys(HOURLY_VARS + ARCHIVE_VARS))

#: Open-Meteo accepts comma-separated coordinate lists and returns one object per
#: point. 100 keeps the URL well inside limits while cutting 1,120 cells to 12 calls.
BATCH = 100


@dataclass
class MetResult:
    frame: pd.DataFrame
    ok_cells: int
    failed_cells: int
    source: str

    @property
    def available(self) -> bool:
        return not self.frame.empty


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _normalise(payload, batch: list[Cell]) -> list[dict]:
    """Open-Meteo returns a bare object for one point and a list for many."""
    if payload is None:
        return []
    items = payload if isinstance(payload, list) else [payload]
    if len(items) != len(batch):
        # Ordering is positional, so a length mismatch means we cannot safely align
        # results to cells. Dropping the batch is the only honest response.
        print(f"[met] batch length mismatch: {len(items)} results for {len(batch)} cells")
        return []
    return items


def _to_rows(item: dict, cell: Cell) -> list[dict]:
    hourly = (item or {}).get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return []
    # Ground elevation matters more than it looks. Geopotential heights are above SEA
    # level, so without it we cannot say which pressure levels are above GROUND - and
    # over Delhi the 1000 hPa surface sits below the terrain, making its temperature a
    # downward extrapolation that reads several degrees too warm at night. Excluding
    # such levels is the difference between detecting an inversion and inventing one.
    elev = item.get("elevation")
    if elev is None:
        # Barometric fallback from surface pressure, referenced to 1013.25 hPa.
        sp = (hourly.get("surface_pressure") or [None])[0]
        elev = 44330.0 * (1.0 - (float(sp) / 1013.25) ** 0.1903) if sp else 0.0
    rows = []
    for i, ts in enumerate(times):
        row = {"cell_id": cell.cell_id, "lat": cell.lat, "lon": cell.lon,
               "district": cell.district, "tier": cell.tier, "time": ts,
               "elevation": float(elev)}
        for var in ALL_VARS:
            series = hourly.get(var)
            row[var] = series[i] if series is not None and i < len(series) else None
        rows.append(row)
    return rows


def _fetch(cells: list[Cell], *, url: str, params: dict, vars_: tuple[str, ...],
           ttl: float, label: str) -> MetResult:
    frames, ok, bad = [], 0, 0

    def request(batch: list[Cell], depth: int = 0) -> None:
        """Fetch one batch, splitting it on failure rather than losing all of it.

        A single upstream error used to cost every cell in the batch. Since a whole
        hindcast can fit in one batch, one HTTP 502 wiped out an entire run's
        meteorology and the caller saw only "no meteorology returned". Halving on
        failure isolates a bad cell or an oversized request instead of surrendering the
        lot; two levels is enough to tell "the service blinked" from "this cell is
        genuinely unavailable".
        """
        nonlocal ok, bad
        q = dict(params)
        q["latitude"] = ",".join(str(c.lat) for c in batch)
        q["longitude"] = ",".join(str(c.lon) for c in batch)
        q["hourly"] = ",".join(vars_)
        q["timezone"] = "UTC"
        # m/s, not the km/h default. The ventilation coefficient is metres squared per
        # second by definition; mixing the units would inflate it by 3.6x and quietly
        # move every stagnation threshold.
        q["wind_speed_unit"] = "ms"
        payload = net.get_json(net.build_url(url, q), ttl=ttl)
        items = _normalise(payload, batch)
        if not items:
            if len(batch) > 1 and depth < 3:
                mid = len(batch) // 2
                print(f"[met] batch of {len(batch)} failed, splitting")
                request(batch[:mid], depth + 1)
                request(batch[mid:], depth + 1)
            else:
                bad += len(batch)
            return
        for item, cell in zip(items, batch):
            rows = _to_rows(item, cell)
            if rows:
                frames.append(pd.DataFrame(rows))
                ok += 1
            else:
                bad += 1

    for batch in _chunks(cells, BATCH):
        request(batch)

    if not frames:
        return MetResult(pd.DataFrame(), ok, bad, label)

    df = pd.concat(frames, ignore_index=True)
    df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
    df["elevation"] = pd.to_numeric(df.get("elevation"), errors="coerce")
    df = df.dropna(subset=["time"])
    for var in ALL_VARS:
        if var not in df.columns:
            df[var] = pd.NA
        df[var] = pd.to_numeric(df[var], errors="coerce")
    return MetResult(df.sort_values(["cell_id", "time"]).reset_index(drop=True), ok, bad, label)


def fetch_forecast(cells: list[Cell], days: int = 4) -> MetResult:
    """Forward meteorology for the whole grid.

    `days=4` rather than 3: the 72-hour forecast needs lag features that reach back
    from each target hour, and the plume model needs wind slightly beyond the last
    forecast hour to finish advecting puffs already in flight.
    """
    return _fetch(cells, url=FORECAST_URL,
                  params={"forecast_days": days, "past_days": 2},
                  vars_=HOURLY_VARS, ttl=C.CACHE_TTL_FORECAST, label="open-meteo-forecast")


def fetch_archive(cells: list[Cell], start: str, end: str) -> MetResult:
    """ERA5 reanalysis for a past window - the hindcast path for DSS validation.

    Dates are ISO ``YYYY-MM-DD``. ERA5 lags real time by about five days.
    """
    # models=era5 explicitly: the default selection was observed returning a null
    # boundary layer height on some dates while era5 served it 24/24 for the same day.
    return _fetch(cells, url=ARCHIVE_URL,
                  params={"start_date": start, "end_date": end, "models": "era5"},
                  vars_=ARCHIVE_VARS, ttl=C.CACHE_TTL_ARCHIVE, label="open-meteo-era5")


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
