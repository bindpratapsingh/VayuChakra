"""The Delhi NCR domain: grid cells, districts, and the geometry helpers.

The district registry is not decoration. The MoES DSS workbook keys its source
apportionment and its emission-reduction scenarios by three-letter district codes
(`GZB_80`, `JHJ_60`, ...). To validate against that workbook, or to drive a policy
scenario from it, we need those exact codes bound to real coordinates. This module is
the single place that binding lives.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import config as C


# ─── Geometry ────────────────────────────────────────────────────────────────
EARTH_R_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return EARTH_R_KM * 2 * math.asin(math.sqrt(min(1.0, a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing from point 1 to point 2, degrees clockwise from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def angular_diff(a: float, b: float) -> float:
    """Smallest absolute separation between two bearings, 0-180 degrees."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


# ─── Districts ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class District:
    code: str          # the DSS workbook's three-letter key
    name: str          # the DSS workbook's column label, spelling preserved
    lat: float
    lon: float
    state: str


#: The 19 NCR districts the MoES DSS resolves, plus Delhi itself.
#: Names are spelled as the workbook spells them (including "Ghazibad", "Meeerut",
#: "Muzzafarnagar" and "Raweri") so a lookup against the sheet header cannot silently
#: miss. `dss_column` on the loader maps these to tidy display names.
DISTRICTS: tuple[District, ...] = (
    District("DEL", "Delhi",               28.6139, 77.2090, "Delhi"),
    District("KNL", "Karnal",              29.6857, 76.9905, "Haryana"),
    District("PNP", "Panipat",             29.3909, 76.9635, "Haryana"),
    District("SNP", "Sonipat",             28.9931, 77.0151, "Haryana"),
    District("RHT", "Rohtak",              28.8955, 76.6066, "Haryana"),
    District("JHJ", "Jhajjar",             28.6060, 76.6570, "Haryana"),
    District("GRG", "Gurgaon",             28.4595, 77.0266, "Haryana"),
    District("FDB", "Faridabad",           28.4089, 77.3178, "Haryana"),
    District("RWR", "Raweri",              28.1990, 76.6170, "Haryana"),
    District("MHN", "Mahendragarh",        28.2800, 76.1500, "Haryana"),
    District("BWN", "Bhiwani",             28.7930, 76.1390, "Haryana"),
    District("JND", "Jind",                29.3159, 76.3151, "Haryana"),
    District("BGP", "Bagpat",              28.9448, 77.2178, "Uttar Pradesh"),
    District("MRT", "Meeerut",             28.9845, 77.7064, "Uttar Pradesh"),
    District("MZF", "Muzzafarnagar",       29.4727, 77.7085, "Uttar Pradesh"),
    District("GZB", "Ghazibad",            28.6692, 77.4538, "Uttar Pradesh"),
    District("GBN", "Gautam Buddha Nagar", 28.4744, 77.5040, "Uttar Pradesh"),
    District("BLS", "Bulandshahr",         28.4069, 77.8498, "Uttar Pradesh"),
    District("BRP", "Bharatpur",           27.2152, 77.4900, "Rajasthan"),
    District("ALW", "Alwar",               27.5530, 76.6346, "Rajasthan"),
)

BY_CODE = {d.code: d for d in DISTRICTS}

#: Delhi's own emitting sectors, as the DSS scenario sheet keys them
#: (DEL_TRA_80 = Delhi transport at 20% reduction, and so on).
DELHI_SECTORS: dict[str, str] = {
    "TRA": "Transport",
    "IND": "Peripheral industry",
    "WBR": "Waste burning",
    "CON": "Construction",
    "RDT": "Road dust",
    "ENE": "Energy",
}

#: Sector labels in the apportionment sheet, which uses full names rather than codes.
APPORTIONMENT_SECTORS: dict[str, str] = {
    "Delhi Transport": "Transport",
    "Delhi perpheral Indust": "Peripheral industry",
    "Delhi Residential": "Residential",
    "Delhi Construction": "Construction",
    "Delhi Waste Burning": "Waste burning",
    "Delhi Road dust": "Road dust",
    "Delhi Energy": "Energy",
    "Delhi Other sectors": "Other sectors",
}


def nearest_district(lat: float, lon: float) -> District:
    return min(DISTRICTS, key=lambda d: haversine_km(lat, lon, d.lat, d.lon))


# ─── Grid ────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Cell:
    cell_id: int
    lat: float
    lon: float
    district: str      # code
    dist_km: float     # distance to that district centre
    tier: str          # "delhi" (fine) or "ncr" (coarse)

    @property
    def is_delhi(self) -> bool:
        return self.tier == "delhi"


#: Delhi NCT's bounding box. Used to decide grid tier, not to clip anything.
DELHI_BOX = (28.40, 28.88, 76.84, 77.35)   # lat_min, lat_max, lon_min, lon_max


def in_delhi_box(lat: float, lon: float) -> bool:
    a, b, c, d = DELHI_BOX
    return a <= lat <= b and c <= lon <= d


def _round(x: float) -> float:
    return round(x, 4)


def _span(lo: float, hi: float, step: float) -> list[float]:
    n = int(round((hi - lo) / step))
    return [_round(lo + i * step) for i in range(n + 1)]


def build_grid(
    ncr_step: float = C.GRID_STEP_DEG,
    delhi_step: float = C.DELHI_GRID_STEP_DEG,
) -> list[Cell]:
    """Two-tier grid: fine over Delhi, coarse over the wider NCR.

    A single 0.1 degree grid put only eight cells inside Delhi - useless for a problem
    statement that asks for high resolution. A single 0.025 degree grid over the whole
    NCR box would be ~11,000 cells, which is a lot of upstream requests for mostly
    farmland whose only role is to carry a plume towards the city.

    So: 0.025 degrees (~2.8 km) inside Delhi where the forecast is consumed, 0.1
    degrees (~11 km) outside it where the field only needs to advect.

    A coarse cell is dropped only when the fine tier covers the WHOLE of its footprint.
    Testing the coarse centre instead, which is what this did originally, left a real
    hole: the box starts at 28.40, so the coarse cell centred at 28.40 was dropped even
    though it covers down to 28.35, while the fine tier only reaches 28.3875. That left
    a 4.2 km strip along Delhi's southern edge with no cell in either tier, and it was
    visible as a white seam once the domain was drawn at its full extent. The northern
    edge never had the problem because 28.90 falls outside the box and was kept anyway,
    so the two edges were not even wrong in the same way. Footprint containment makes
    them consistent: a slight overlap at both edges, and a gap at neither.
    """
    cells: list[Cell] = []
    cid = 0

    # The ground the fine tier actually paints, which is half a fine cell beyond its
    # outermost centres, not the nominal box.
    d_lats = _span(DELHI_BOX[0], DELHI_BOX[1], delhi_step)
    d_lons = _span(DELHI_BOX[2], DELHI_BOX[3], delhi_step)
    half = delhi_step / 2.0
    fine_lat0, fine_lat1 = d_lats[0] - half, d_lats[-1] + half
    fine_lon0, fine_lon1 = d_lons[0] - half, d_lons[-1] + half
    ch = ncr_step / 2.0

    def covered_by_fine(lat: float, lon: float) -> bool:
        """Is every corner of this coarse cell already served by the fine tier?"""
        return (lat - ch >= fine_lat0 - 1e-9 and lat + ch <= fine_lat1 + 1e-9
                and lon - ch >= fine_lon0 - 1e-9 and lon + ch <= fine_lon1 + 1e-9)

    for lat in _span(C.LAT_MIN, C.LAT_MAX, ncr_step):
        for lon in _span(C.LON_MIN, C.LON_MAX, ncr_step):
            if covered_by_fine(lat, lon):
                continue                      # the fine tier owns this area
            d = nearest_district(lat, lon)
            cells.append(Cell(cid, lat, lon, d.code,
                              round(haversine_km(lat, lon, d.lat, d.lon), 2), "ncr"))
            cid += 1

    for lat in d_lats:
        for lon in d_lons:
            dd = nearest_district(lat, lon)
            cells.append(Cell(cid, lat, lon, dd.code,
                              round(haversine_km(lat, lon, dd.lat, dd.lon), 2), "delhi"))
            cid += 1

    return cells


def delhi_cells(cells: list[Cell] | None = None) -> list[Cell]:
    return [c for c in (cells or build_grid()) if c.tier == "delhi"]


def idw(pairs: list[tuple[float, float]], k: int = 3, power: float = 2.0) -> float | None:
    """Inverse-distance weighting over (value, distance_km) pairs.

    Same k and power as the AirGrid live layer, so the two products interpolate
    identically and a reviewer comparing them is not chasing a methodology difference.
    """
    usable = [(v, d) for v, d in pairs if v is not None and d is not None and d == d]
    if not usable:
        return None
    usable.sort(key=lambda vd: vd[1])
    usable = usable[:k]
    for v, d in usable:
        if d < 1e-6:
            return v
    w = [1.0 / (d ** power) for _, d in usable]
    tot = sum(w)
    return sum(wi * v for wi, (v, _) in zip(w, usable)) / tot if tot > 0 else None
