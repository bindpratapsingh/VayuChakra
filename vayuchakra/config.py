"""Central configuration: paths, domain, credentials, physical constants.

Everything tunable lives here so that a reviewer can find every magic number in one
file rather than hunting through the modules. Values that came from published
literature carry their source inline, because the whole credibility of the coupled
solver rests on those numbers being defensible rather than invented.
"""
from __future__ import annotations

import os
from pathlib import Path

# ─── Paths ───────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "cache"
MODELS = ROOT / "models"
DOCS = ROOT / "docs"

for _d in (DATA, CACHE, MODELS):
    _d.mkdir(parents=True, exist_ok=True)

#: The AirGrid repo sits one level up. We read two things from it and never write:
#: the MoES DSS workbook, and (optionally) its ward geometry. Both are guarded by
#: existence checks so VayuChakra runs standalone if the folder is absent.
AIRGRID = ROOT.parent
DSS_XLSX = AIRGRID / "Bind's Workspace" / "DSS Paper related" / "DSS-Analysis-JAMES.xlsx"


# ─── Credentials ─────────────────────────────────────────────────────────────
def _load_env() -> None:
    """Read .env from VayuChakra/ then fall back to the AirGrid .env beside it.

    We deliberately do not add python-dotenv as a dependency for a nine-line parser.
    Existing environment variables always win, so a shell export can override a file.
    """
    for path in (ROOT / ".env", AIRGRID / ".env"):
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


_load_env()

OPENAQ_API_KEY = os.getenv("OPENAQ_API_KEY", "").strip()
FIRMS_MAP_KEY = os.getenv("FIRMS_MAP_KEY", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()


# ─── Domain (D-005) ──────────────────────────────────────────────────────────
#: Delhi NCR, deliberately wider than AirGrid's Delhi-only box. The MoES DSS
#: apportionment resolves 19 NCR districts. The box is set by its extremes -
#: Karnal at 29.69 N, Bharatpur at 27.22 N, Mahendragarh at 76.15 E, Bulandshahr at
#: 77.85 E - all of which fall outside AirGrid's 28.4-28.9 N / 76.8-77.4 E grid.
LAT_MIN, LAT_MAX = 27.0, 29.9
LON_MIN, LON_MAX = 75.8, 78.1

#: ~0.1 deg is about 11 km. Coarse enough that the whole NCR forecast is a few hundred
#: cells (cheap to run every hour on a laptop), fine enough to resolve the Delhi-to-
#: Panipat gradient the DSS cares about. The high-resolution ward layer is produced by
#: interpolating this grid onto ward centroids, exactly as AirGrid does.
GRID_STEP_DEG = 0.10

#: Fine tier over Delhi NCT: ~2.8 km. "High-resolution" in the PS means the city, and
#: this is where every forecast is actually consumed.
DELHI_GRID_STEP_DEG = 0.025

#: Central Delhi. Used for city-level series and as the anchor for single-point pulls.
DELHI_LAT, DELHI_LON = 28.6139, 77.2090


# ─── Forecast horizon ────────────────────────────────────────────────────────
HORIZONS_H = (24, 48, 72)
MAX_LEAD_H = 72


# ─── Physical constants for the coupled solver ───────────────────────────────
#: Standard atmosphere / dry air.
GRAVITY = 9.80665          # m s-2
R_DRY = 287.05             # J kg-1 K-1
CP_AIR = 1004.0            # J kg-1 K-1
RHO_AIR = 1.225            # kg m-3, sea-level standard

#: Solar constant at the top of the atmosphere.
SOLAR_CONSTANT = 1361.0    # W m-2

#: Surface albedo for an urban plain. Delhi's mixed built-up and bare soil sits
#: around 0.15-0.20; 0.18 is the mid-point and the value the sensitivity test varies.
SURFACE_ALBEDO = 0.18

#: Fraction of absorbed shortwave that becomes sensible heat flux (Bowen-ratio
#: partitioning). Delhi's dry winter surface is sensible-heat dominated, so most of
#: the absorbed energy heats the air rather than evaporating water.
SENSIBLE_HEAT_FRACTION = 0.35

#: Free-atmosphere potential-temperature lapse rate above the mixed layer, used by the
#: encroachment model. 0.0065 K m-1 is the standard atmosphere value.
GAMMA_FREE_ATM = 0.0065    # K m-1

#: --- Feedback rails (D-006) ---------------------------------------------------
#: Without these a positive feedback can run away: more aerosol -> less sun -> shallower
#: layer -> more aerosol. Real physics is limited by advection and entrainment that we
#: do not resolve, so we clip instead and flag when a clip binds.
MAX_DELTA_T = 3.0          # K, magnitude of the aerosol dimming temperature response
MAX_PBL_SUPPRESSION = 0.40 # fraction; PBL cannot fall below 60% of its uncoupled value
MIN_PBL_M = 30.0           # m, numerical floor - a zero mixing depth is a divide-by-zero
MAX_PBL_M = 5000.0         # m, physical ceiling - deep convection aside, the daytime
                           # mixed layer over the plains does not exceed this
COUPLING_OMEGA = 0.5       # relaxation factor for the damped fixed point
COUPLING_MAX_ITER = 12
COUPLING_TOL = 0.5         # ug m-3; convergence when successive PM2.5 differ by less

#: --- Wind response to aerosol cooling -----------------------------------------
#: The problem statement names temperature, WIND and PBL height as the meteorological
#: side of the loop. Aerosol cooling weakens the surface heat flux that drives turbulent
#: mixing, and weaker mixing transports less momentum down from aloft, so the surface
#: wind slackens.
#:
#: Calibrated from the ratio in the literature rather than invented: Xing et al. report
#: wind falling 1.6-4.3% while PBL falls 13.0-20.9% in the same experiments, so the
#: response is roughly a fifth of the boundary-layer suppression. A Yangtze Delta episode
#: gives the same order (PBL -276 m, T -1 C, wind -0.33 m/s).
#:
#: This is deliberately a SMALL term. It is here because the PS names it and because the
#: loop is incomplete without it, not because it drives skill - and that is what we say.
WIND_RESPONSE_RATIO = 0.20      # fractional wind change per unit fractional PBL change
MAX_WIND_SUPPRESSION = 0.15     # hard cap; the published range tops out near 4%

#: --- Acceptance bounds from published Delhi studies ---------------------------
#: The solver is considered WRONG, not merely surprising, if it lands outside these.
#: Ranges span the values reported for Delhi winter aerosol radiative effects.
EXPECT_SW_REDUCTION = (0.05, 0.35)   # fraction of surface shortwave lost to aerosol
EXPECT_DT_COOLING = (0.1, 2.5)       # K daytime near-surface cooling
EXPECT_PBL_SUPPRESSION = (0.05, 0.35)  # fractional reduction in mixing depth
EXPECT_PM_AMPLIFICATION = (0.02, 0.30)  # fractional PM2.5 increase from the feedback
EXPECT_WIND_REDUCTION = (0.005, 0.06)   # fractional surface wind slackening (1.6-4.3% reported)


# ─── Dispersion thresholds ───────────────────────────────────────────────────
#: Ventilation coefficient = mixing depth x mean wind speed through the layer.
#: The classic operational thresholds for "poor" and "severe stagnation".
VC_POOR = 6000.0     # m2 s-1
VC_SEVERE = 3000.0   # m2 s-1


# ─── HTTP ────────────────────────────────────────────────────────────────────
HTTP_TIMEOUT = 45.0
HTTP_RETRIES = 3
HTTP_BACKOFF = 1.7
USER_AGENT = "VayuChakra/0.1 (coupled weather-chemistry research prototype)"

#: Cache lifetimes. Forecast products update on a 6-hourly cycle upstream, so polling
#: faster than hourly only burns quota.
CACHE_TTL_FORECAST = 3600      # s
CACHE_TTL_OBSERVATION = 600    # s
CACHE_TTL_ARCHIVE = 30 * 86400  # archive data for a past date never changes
