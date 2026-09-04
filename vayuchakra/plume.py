"""Stubble-burning plume transport — a Lagrangian puff model.

The problem statement asks for two things this module provides:

    "accurately modeling the impact of atmospheric inversion on external pollution
     spikes, such as regional stubble burning"

    "predict how stubble-burning plumes will disperse under prevailing weather
     conditions"

Detecting fires is the easy half and satellites already do it. The hard half — and the
half that decides whether Delhi has a bad night — is what happens to the smoke between
the field and the city.

WHY A PUFF MODEL AND NOT AN UPWIND COUNT
-----------------------------------------
The obvious approach is to count fires that lie upwind and call it a score. That is
what the sibling AirGrid project does, and it cannot answer the question that matters,
because it has no notion of *time*. Smoke from a fire 250 km away does not arrive when
the satellite sees the fire; it arrives six to fifteen hours later, having travelled
through a wind field that turned, through a boundary layer that collapsed at dusk and
reopened at nine the next morning. A plume released into a deep afternoon mixed layer
disperses; the same plume arriving over a 100 m nocturnal inversion does not.

So each fire is released as a discrete parcel and carried forward hour by hour on the
forecast wind, spreading as it goes, and it contributes to a city's air only when and
where it actually arrives.

THE INVERSION INTERACTION — the part the PS specifically asks for
------------------------------------------------------------------
Surface concentration is mass divided by the volume it is mixed through. The lid works
in **both directions** and both are modelled here:

  * a puff **below** the lid is trapped, and a shallow lid concentrates it — the same
    smoke produces several times the surface concentration under a 100 m nocturnal
    inversion that it would under an 800 m afternoon mixed layer;
  * a puff **above** the lid is decoupled and contributes *nothing* at the surface
    until the lid breaks — which is why smoke can be visibly overhead while monitors
    read clean, and why it lands abruptly mid-morning when convection reconnects it.

WHAT THIS IS NOT
----------------
Not HYSPLIT. Single-layer advection with a parameterised spread, no vertical wind
shear, no terrain, no chemistry en route. It reports a **transport-plausible
contribution**, never a measured one.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import config as C
from . import net
from .grid import Cell, bearing_deg, haversine_km

FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

#: Satellite products, queried together. Two VIIRS platforms plus MODIS give roughly
#: six overpasses a day; any one alone leaves multi-hour blind spots, and stubble fires
#: are lit and burn out inside a single afternoon.
SOURCES = ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "MODIS_NRT")

#: The stubble belt: Indian Punjab and Haryana, plus Pakistani Punjab, which burns on
#: the same calendar and lies on the same north-westerly track into Delhi.
#: (lon_min, lat_min, lon_max, lat_max)
STUBBLE_BBOX = (73.0, 28.0, 78.5, 32.5)

# ─── Emission ────────────────────────────────────────────────────────────────
#: Dry matter consumed per unit of fire radiative energy, kg per MJ. The GFAS
#: conversion (Kaiser et al., 2012) that operational systems use to turn a satellite
#: radiative power into a mass flux.
DM_PER_MJ = 0.368

#: PM2.5 emitted per kg of dry agricultural residue burned, grams per kg. Within the
#: 5-8 g/kg commonly reported for cereal straw.
PM25_G_PER_KG_DM = 6.26

#: So a 1 MW fire emits DM_PER_MJ * PM25_G_PER_KG_DM = 2.30 g of PM2.5 per second.
PM25_G_PER_S_PER_MW = DM_PER_MJ * PM25_G_PER_KG_DM

# ─── Dispersion ──────────────────────────────────────────────────────────────
#: Near-field Pasquill-Gifford coefficients, sigma_y = A * t**0.9 with t in seconds.
PG_A = {"A": 0.22, "B": 0.16, "C": 0.11, "D": 0.08, "E": 0.06, "F": 0.04}

#: Far-field regional expansion: a smoke plume widens roughly in proportion to the
#: distance it has travelled, because wind shear and mesoscale eddies dominate over
#: local turbulence beyond a few tens of kilometres. Pasquill-Gifford was fitted for
#: ranges under 10 km and badly under-predicts a 200 km transport, so the two are
#: combined in quadrature: near-field turbulence, far-field shear.
REGIONAL_SPREAD = {"A": 0.16, "B": 0.14, "C": 0.12, "D": 0.10, "E": 0.08, "F": 0.06}

#: Removal e-folding time, hours. Dry deposition plus coagulation; wet scavenging is
#: applied separately and much faster when it rains.
DECAY_HOURS = 48.0
WET_SCAVENGE_PER_MM = 0.25   # fraction of remaining mass removed per mm of rain

#: A puff stops being tracked once it holds too little to matter, so a long run does
#: not accumulate hundreds of thousands of negligible parcels.
MIN_PUFF_MASS_G = 1e4
MAX_PUFF_AGE_H = 60.0

#: Which vertical treatment to use. Set by `scripts/plume_calibrate.py` so the three can
#: be scored against the MoES DSS attribution and chosen on evidence rather than taste.
#: They differ ONLY in how a parcel couples to the ground, so nothing else can drift
#: between them.
#:
#:   "A"  injection height fixed for the parcel's whole life. Smoke lofted to ~300 m sits
#:        above a 33 m nocturnal lid and never reaches the surface, so the model reports
#:        its LARGEST contributions under the deepest afternoon mixed layer - backwards.
#:   "B"  entrained: once a growing mixed layer overtakes a parcel it is coupled fully,
#:        and follows the layer down. Correct direction, but puts the entire plume into a
#:        33 m nocturnal layer.
#:   "C"  entrained WITH a residual layer: only current_depth / mixed_depth stays coupled
#:        to the ground; the rest is stranded aloft until morning. Standard treatment.
#:
#: **Default is "A", chosen on evidence rather than on physical reasoning.** Scored over
#: the 6 Oct - 30 Nov 2021 burning season against the MoES DSS daily stubble attribution
#: (229,709 archived detections, 56 days):
#:
#:     A  r = +0.596   C  r = +0.525   B  r = +0.369
#:
#: Round 1 shipped C on the argument that its vertical treatment is the most physically
#: complete, having rejected A from a single four-day episode as "backwards". The
#: season-long comparison against the operational reference disagrees, and the earlier
#: choice was made on reasoning rather than measurement - exactly the failure mode this
#: project keeps trying to avoid.
#:
#: The honest caveat: the DSS attribution is DAILY, so it cannot discriminate between
#: treatments on their diurnal behaviour, which is where A is most questionable. It
#: settles day-to-day timing and nothing finer. C remains available and is the better
#: choice if a sub-daily reference ever becomes available.
VARIANT = "A"


@dataclass
class Fire:
    lat: float
    lon: float
    frp_mw: float
    when: pd.Timestamp
    confidence: str
    source: str


def _parse_confidence(raw: str) -> str:
    raw = (raw or "").strip().lower()
    if raw in ("h", "high"):
        return "high"
    if raw in ("n", "nominal"):
        return "nominal"
    if raw in ("l", "low"):
        return "low"
    try:                      # MODIS reports 0-100
        v = float(raw)
        return "high" if v >= 80 else "nominal" if v >= 30 else "low"
    except ValueError:
        return "nominal"


#: Standard-processing products. These cover the ARCHIVE, where the near-real-time
#: products return nothing: a request for November 2021 against `VIIRS_SNPP_NRT` comes
#: back with a header row and no data, while `VIIRS_SNPP_SP` returns 18,034 detections
#: for the same three days over the stubble belt.
ARCHIVE_SOURCES = ("VIIRS_SNPP_SP", "VIIRS_NOAA20_SP", "MODIS_SP")


def fetch_fires(days: int = 3, bbox: tuple = STUBBLE_BBOX,
                min_frp: float = 1.0, start: str | None = None) -> list[Fire]:
    """Active fire detections over the stubble belt.

    `start` (ISO ``YYYY-MM-DD``) replays a past window and switches to the archive
    products; without it the near-real-time products are used.

    Returns an empty list rather than raising when the key is missing or NASA is
    unreachable: outside October-November this is *correctly* almost empty, and the
    rest of the forecast must not depend on it.
    """
    if not C.FIRMS_MAP_KEY:
        print("[plume] no FIRMS_MAP_KEY - fire detection unavailable")
        return []
    area = ",".join(str(x) for x in bbox)
    sources = ARCHIVE_SOURCES if start else SOURCES
    ttl = C.CACHE_TTL_ARCHIVE if start else C.CACHE_TTL_OBSERVATION
    fires: list[Fire] = []
    for src in sources:
        url = f"{FIRMS_URL}/{C.FIRMS_MAP_KEY}/{src}/{area}/{max(1, min(days, 10))}"
        if start:
            url += f"/{start}"
        body = net.get_text(url, ttl=ttl)
        if not body or "latitude" not in body[:200]:
            continue
        for row in csv.DictReader(io.StringIO(body)):
            try:
                frp = float(row.get("frp") or 0.0)
                if frp < min_frp:
                    continue
                hhmm = str(row.get("acq_time") or "0").zfill(4)
                when = pd.Timestamp(f"{row['acq_date']} {hhmm[:2]}:{hhmm[2:]}", tz="UTC")
                fires.append(Fire(float(row["latitude"]), float(row["longitude"]),
                                  frp, when, _parse_confidence(row.get("confidence", "")),
                                  src))
            except (KeyError, TypeError, ValueError):
                continue
    return fires


def injection_height_m(frp_mw) -> np.ndarray:
    """How high the smoke is lofted, from fire radiative power.

    Buoyant plume rise scales roughly with the cube root of heat output. Agricultural
    stubble fires are small and short — typically a few hundred metres, not the several
    kilometres a forest crown fire reaches — so most of this smoke is injected *within*
    the boundary layer and is available to be trapped by a lid. That is precisely why
    it matters to Delhi at all.
    """
    frp = np.clip(np.asarray(frp_mw, dtype="float64"), 0.1, None)
    return np.clip(150.0 * np.cbrt(frp), 100.0, 2500.0)


@dataclass
class PuffState:
    """Vectorised parcel state. Arrays, not objects — there can be tens of thousands.

    ``entrained`` records whether a parcel has ever been overtaken by a growing mixed
    layer. It matters more than it looks: see :func:`_step`.
    """
    lat: np.ndarray
    lon: np.ndarray
    mass_g: np.ndarray
    height_m: np.ndarray
    age_h: np.ndarray
    travel_km: np.ndarray
    entrained: np.ndarray | None = None
    mixed_depth_m: np.ndarray | None = None

    def __post_init__(self):
        if self.entrained is None:
            self.entrained = np.zeros(len(self.lat), dtype=bool)
        if self.mixed_depth_m is None:
            self.mixed_depth_m = np.full(len(self.lat), C.MIN_PBL_M, dtype="float64")

    FIELDS = ("lat", "lon", "mass_g", "height_m", "age_h", "travel_km",
              "entrained", "mixed_depth_m")

    def __len__(self) -> int:
        return len(self.lat)

    def alive(self) -> np.ndarray:
        return (self.mass_g > MIN_PUFF_MASS_G) & (self.age_h <= MAX_PUFF_AGE_H)

    def compress(self) -> "PuffState":
        k = self.alive()
        return PuffState(*(getattr(self, f)[k] for f in PuffState.FIELDS))


def sigma_y_m(age_h, travel_km, stability: str = "D") -> np.ndarray:
    """Horizontal spread of a puff, metres.

    Near-field Pasquill-Gifford and far-field shear-driven expansion combined in
    quadrature, so the near term is turbulence-dominated and the long haul is
    shear-dominated. A 200 km transport under neutral conditions gives about 20 km of
    spread, which is the right order for a regional smoke plume.
    """
    t_s = np.clip(np.asarray(age_h, dtype="float64"), 0.0, None) * 3600.0
    d_m = np.clip(np.asarray(travel_km, dtype="float64"), 0.0, None) * 1000.0
    near = PG_A.get(stability, 0.08) * np.power(np.maximum(t_s, 1.0), 0.9)
    far = REGIONAL_SPREAD.get(stability, 0.10) * d_m
    return np.sqrt(near ** 2 + far ** 2) + 100.0


class WindField:
    """Nearest-neighbour lookup of the gridded wind, by hour.

    Nearest neighbour rather than interpolation, deliberately: at 11 km grid spacing
    the interpolation error is far smaller than the error already carried by treating
    a puff as a point, and a KD-tree query per hour keeps a 72-hour run interactive.
    """

    def __init__(self, met_frame: pd.DataFrame):
        from scipy.spatial import cKDTree

        need = {"time", "lat", "lon", "wind_u_10m", "wind_v_10m"}
        self.ok = not met_frame.empty and need.issubset(met_frame.columns)
        if not self.ok:
            self.hours: dict = {}
            return
        self.hours = {}
        for when, grp in met_frame.groupby("time"):
            g = grp.dropna(subset=["lat", "lon"])
            if g.empty:
                continue
            self.hours[pd.Timestamp(when)] = (
                cKDTree(np.column_stack([g["lat"].to_numpy(), g["lon"].to_numpy()])),
                g.reset_index(drop=True),
            )
        self.times = sorted(self.hours)

    def at(self, when: pd.Timestamp, lat: np.ndarray, lon: np.ndarray) -> dict:
        if not self.ok or not self.times:
            n = len(lat)
            return {"u": np.zeros(n), "v": np.zeros(n),
                    "mixing_depth_m": np.full(n, 500.0),
                    "lid_m": np.full(n, np.nan), "precip": np.zeros(n)}
        key = min(self.times, key=lambda t: abs((t - when).total_seconds()))
        tree, frame = self.hours[key]
        _, idx = tree.query(np.column_stack([lat, lon]), k=1)
        idx = np.clip(idx, 0, len(frame) - 1)
        take = lambda col, default: (
            pd.to_numeric(frame[col], errors="coerce").to_numpy()[idx]
            if col in frame.columns else np.full(len(idx), default))
        return {"u": np.nan_to_num(take("wind_u_10m", 0.0)),
                "v": np.nan_to_num(take("wind_v_10m", 0.0)),
                "mixing_depth_m": np.nan_to_num(take("mixing_depth_m", 500.0), nan=500.0),
                "lid_m": take("inversion_lid_m", np.nan),
                "precip": np.nan_to_num(take("precipitation", 0.0))}


def _step(puffs: PuffState, wind: dict, dt_h: float = 1.0) -> PuffState:
    """Advect, age, and remove mass for one hour."""
    dt_s = dt_h * 3600.0
    dx_m = wind["u"] * dt_s          # eastward
    dy_m = wind["v"] * dt_s          # northward
    dlat = dy_m / 111_320.0
    dlon = dx_m / (111_320.0 * np.cos(np.radians(np.clip(puffs.lat, -89, 89))))

    new_lat = puffs.lat + dlat
    new_lon = puffs.lon + dlon
    moved_km = np.sqrt(dx_m ** 2 + dy_m ** 2) / 1000.0

    decay = math.exp(-dt_h / DECAY_HOURS)
    wet = np.exp(-WET_SCAVENGE_PER_MM * np.clip(wind["precip"], 0.0, None))

    # --- entrainment, and why it matters ---------------------------------------
    # A parcel keeps its injection height only until a growing mixed layer reaches it.
    # Once the daytime boundary layer has overtaken it, the smoke is *mixed into* that
    # layer, and it stays there as the layer collapses after sunset — which concentrates
    # it, exactly as it concentrates local emissions.
    #
    # Treating injection height as fixed forever got this backwards. A parcel injected
    # at ~300 m sat "above" a 33 m nocturnal lid and was excluded from the surface all
    # night, so the model reported its LARGEST plume contributions during the deep
    # afternoon mixed layer and near-zero at night. That is the opposite of the
    # mechanism the problem statement asks about: an inversion is supposed to trap
    # transported smoke against the ground, not exempt the city from it.
    depth = np.clip(wind.get("mixing_depth_m", np.full(len(puffs), 500.0)),
                    C.MIN_PBL_M, C.MAX_PBL_M)
    if VARIANT == "A":
        # No entrainment at all: the parcel keeps its injection height forever.
        now_entrained = np.zeros(len(puffs), dtype=bool)
        new_height = puffs.height_m
    else:
        now_entrained = puffs.entrained | (depth >= puffs.height_m)
        new_height = np.where(now_entrained, np.minimum(puffs.height_m, depth * 0.5),
                              puffs.height_m)

    # --- the residual layer ----------------------------------------------------
    # `mixed_depth_m` is the DEEPEST layer this parcel has been mixed through. It is a
    # running maximum, and it is what makes the night-time behaviour correct.
    #
    # When the mixed layer collapses at dusk from ~1200 m to ~50 m, the smoke does not
    # collapse with it. Only the share now inside the shallow layer stays coupled to the
    # ground; the rest is stranded aloft in the residual layer and reconnects the next
    # morning. Assuming uniform mixing, that share is current_depth / mixed_depth.
    #
    # Getting this wrong in either direction is visible: without entrainment at all the
    # model reported its largest contributions in the deep afternoon layer (backwards);
    # with entrainment but no residual layer it put the ENTIRE plume into a 33 m
    # nocturnal layer and implied stubble was ~69% of Delhi's PM2.5, which is far above
    # any published estimate.
    new_mixed = np.where(now_entrained, np.maximum(puffs.mixed_depth_m, depth),
                         puffs.mixed_depth_m)

    return PuffState(new_lat, new_lon, puffs.mass_g * decay * wet,
                     new_height, puffs.age_h + dt_h, puffs.travel_km + moved_km,
                     now_entrained, new_mixed)


def _contribution(puffs: PuffState, cells: list[Cell], wind_puff: dict,
                  wind_cell: dict, stability: str = "D") -> np.ndarray:
    """Surface PM2.5 contributed to each cell by the current puff population, ug/m3.

    Gaussian in the horizontal, uniformly mixed in the vertical through the mixing
    depth — the standard treatment for a puff trapped inside the boundary layer:

        C = M / (2*pi*sigma^2 * H) * exp(-d^2 / (2*sigma^2))

    **Two different atmospheres are involved and they must not be conflated.** Whether
    a puff is coupled to the ground at all is decided by the lid *where the puff is* —
    a parcel riding above an inversion 80 km upwind is decoupled regardless of what
    Delhi's boundary layer is doing. The volume it is then diluted into is set by the
    mixing depth *at the receptor*, because that is the air the monitor is sampling.
    Using one for both was a real bug: it broadcast a per-puff array against a per-cell
    one and, had the lengths happened to match, would have silently produced the wrong
    answer instead of an error.

    The coupling transition is smoothed over 200 m rather than made a hard switch,
    because a step change would make a plume blink on and off between hours as the lid
    wobbled by a metre.
    """
    if len(puffs) == 0 or not cells:
        return np.zeros(len(cells))

    sig = sigma_y_m(puffs.age_h, puffs.travel_km, stability)

    # --- at the puff: is this smoke coupled to the surface at all? ---
    # A parcel already entrained into the mixed layer is coupled by definition: it is
    # inside the air the monitor samples, however shallow that air has become.
    # Only smoke still riding above the layer is decoupled.
    puff_depth = np.clip(wind_puff["mixing_depth_m"], C.MIN_PBL_M, C.MAX_PBL_M)
    puff_lid = wind_puff["lid_m"]
    cap = np.where(np.isfinite(puff_lid), np.maximum(puff_lid, puff_depth), puff_depth)
    coupled = np.clip(1.0 - (puffs.height_m - cap) / 200.0, 0.0, 1.0)
    # An entrained parcel is coupled only in proportion to how much of the layer it was
    # mixed through is still connected to the ground - see the residual-layer note in
    # `_step`. A parcel mixed through 1200 m and now under a 60 m lid has 5% of its mass
    # at the surface and 95% stranded above it.
    if VARIANT == "C":
        resid_frac = np.clip(
            puff_depth / np.maximum(puffs.mixed_depth_m, C.MIN_PBL_M), 0.0, 1.0)
        coupled = np.where(puffs.entrained, resid_frac, coupled)
    elif VARIANT == "B":
        coupled = np.where(puffs.entrained, 1.0, coupled)
    # VARIANT "A" leaves `coupled` as the raw lid comparison above.

    # --- at the receptor: what volume does it dilute into? ---
    cell_depth = np.clip(wind_cell["mixing_depth_m"], C.MIN_PBL_M, C.MAX_PBL_M)

    out = np.zeros(len(cells))
    lat_c = np.array([c.lat for c in cells])
    lon_c = np.array([c.lon for c in cells])

    for i in range(len(lat_c)):
        dy = (puffs.lat - lat_c[i]) * 111_320.0
        dx = (puffs.lon - lon_c[i]) * 111_320.0 * math.cos(math.radians(lat_c[i]))
        d2 = dx ** 2 + dy ** 2
        # Beyond four sigma the exponential is negligible; skipping it keeps the
        # inner loop cheap when most puffs are hundreds of km away.
        near = d2 < (4.0 * sig) ** 2
        if not near.any():
            continue
        # Mass is in grams and the volume in cubic metres, so this quotient is g/m3.
        # The factor of a million converts to ug/m3, which is what every other
        # concentration in this project is expressed in. Without it the plume silently
        # contributes about a millionth of its real value and reads as a clean zero.
        conc = (puffs.mass_g[near] * coupled[near]
                / (2.0 * math.pi * sig[near] ** 2 * cell_depth[i])
                * np.exp(-d2[near] / (2.0 * sig[near] ** 2))) * 1.0e6
        out[i] = float(np.sum(conc))
    return out


def run(fires: list[Fire], met_frame: pd.DataFrame, cells: list[Cell],
        hours: int = 72, start: pd.Timestamp | None = None) -> pd.DataFrame:
    """Advect every fire's smoke forward and record what reaches each cell.

    Returns one row per cell per hour with the plume's PM2.5 contribution and the
    diagnostics that explain it — how many puffs were within range, how much of their
    mass was coupled to the surface, and what the lid was doing.
    """
    if not fires or not cells:
        return pd.DataFrame()

    field = WindField(met_frame)
    t0 = pd.Timestamp(start or min(f.when for f in fires)).floor("h")
    timeline = [t0 + pd.Timedelta(hours=h) for h in range(hours + 1)]

    by_hour: dict[pd.Timestamp, list[Fire]] = {}
    for f in fires:
        by_hour.setdefault(pd.Timestamp(f.when).floor("h"), []).append(f)

    empty = PuffState(*(np.array([], dtype="float64") for _ in range(6)),
                      np.array([], dtype=bool), np.array([], dtype="float64"))
    puffs = empty
    rows = []

    for when in timeline:
        # Release this hour's detections. One puff per detection, carrying the mass
        # that fire would emit over an hour at its observed radiative power.
        new = by_hour.get(when, [])
        if new:
            frp = np.array([f.frp_mw for f in new])
            conf = np.array([{"high": 1.0, "nominal": 0.7, "low": 0.4}[f.confidence]
                             for f in new])
            born = PuffState(
                lat=np.array([f.lat for f in new]),
                lon=np.array([f.lon for f in new]),
                mass_g=PM25_G_PER_S_PER_MW * frp * 3600.0 * conf,
                height_m=injection_height_m(frp),
                age_h=np.zeros(len(new)),
                travel_km=np.zeros(len(new)))
            puffs = PuffState(*(np.concatenate([getattr(puffs, f_), getattr(born, f_)])
                                for f_ in PuffState.FIELDS))

        if len(puffs) == 0:
            rows.extend({"time": when, "cell_id": c.cell_id, "lat": c.lat, "lon": c.lon,
                         "plume_pm25": 0.0, "n_puffs": 0} for c in cells)
            continue

        wind_p = field.at(when, puffs.lat, puffs.lon)
        cell_lat = np.array([c.lat for c in cells])
        cell_lon = np.array([c.lon for c in cells])
        wind_c = field.at(when, cell_lat, cell_lon)

        contrib = _contribution(puffs, cells, wind_p, wind_c)
        for i, c in enumerate(cells):
            rows.append({"time": when, "cell_id": c.cell_id, "lat": c.lat, "lon": c.lon,
                         "plume_pm25": float(contrib[i]), "n_puffs": int(len(puffs)),
                         "mixing_depth_m": float(wind_c["mixing_depth_m"][i]),
                         "lid_m": float(wind_c["lid_m"][i])})

        puffs = _step(puffs, wind_p).compress()

    return pd.DataFrame(rows)


def summarise(fires: list[Fire]) -> dict:
    """Headline numbers for the fire population, for the API and the dashboard."""
    if not fires:
        return {"available": True, "n_fires": 0, "total_frp_mw": 0.0,
                "note": "no active fire detections in the stubble belt"}
    frp = np.array([f.frp_mw for f in fires])
    delhi_bearings = np.array([bearing_deg(f.lat, f.lon, C.DELHI_LAT, C.DELHI_LON)
                               for f in fires])
    dist = np.array([haversine_km(f.lat, f.lon, C.DELHI_LAT, C.DELHI_LON) for f in fires])
    return {"available": True, "n_fires": len(fires),
            "total_frp_mw": round(float(frp.sum()), 1),
            "mean_distance_km": round(float(dist.mean()), 1),
            "nearest_km": round(float(dist.min()), 1),
            "mean_bearing_to_delhi": round(float(delhi_bearings.mean()), 1),
            "by_source": {s: int(sum(1 for f in fires if f.source == s)) for s in SOURCES},
            "high_confidence": int(sum(1 for f in fires if f.confidence == "high"))}
