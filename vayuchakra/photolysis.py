"""Photolysis rates, and how aerosol suppresses them.

WHY THIS MODULE EXISTS
----------------------
Round 1 built the aerosol-radiation feedback (ARF): aerosol dims the sun, the surface
cools, the mixed layer shallows, concentration rises. Its magnitudes were right, but the
ablation was flat. The literature explains why. There are **two** aerosol pathways and we
built the weaker one, on the less responsive pollutant:

    ARF  aerosol -> radiation -> temperature -> boundary layer -> concentration
         effect on ozone: -0.9 to -2.9 ppb  (1-3%)

    API  aerosol -> ULTRAVIOLET -> photolysis rate -> ozone production
         effect on ozone: -8.5 to -11.4 ppb  (10-12%)

(Xing et al., ACP 22, 4101, 2022, which isolates the two with paired WRF-Chem runs.)

API is three to ten times stronger, and it acts directly on ozone rather than through a
chain of four intermediate steps. This module implements it.

WHY DELHI IS THE RIGHT PLACE FOR IT
-----------------------------------
The APHH-India campaign found Delhi's wintertime ozone production is "not only
VOC-limited but also **strongly radiation-limited**", and that a 50% reduction in AOD
would raise ozone by about 25% (Nelson et al., Faraday Discussions 226, 2021). Radiation
is a first-order control on Delhi's winter ozone. A forecast that ignores it is missing
the dominant term.

Our own panel already shows the signal before any modelling: ozone runs 18 µg/m³ at
night against 69 at midday, peaks in April-May, and correlates +0.349 with shortwave
radiation and -0.097 with NO2 (titration).

THE ONE SUBTLETY WORTH KNOWING
------------------------------
Photolysis is driven by **actinic flux** - photons arriving from every direction -
not by irradiance on a horizontal surface. Light scattered by aerosol still reaches a
molecule and can still break it. So photolysis is attenuated *less* than direct beam
irradiance, and applying a Beer-Lambert extinction to J would overstate the effect badly.
The scattering bracket below is what keeps this honest, exactly as in `feedback.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

from .feedback import optical_airmass, solar_zenith_deg

# ─── Clear-sky photolysis: the MCM parameterisation ──────────────────────────
#: J = l * cos(SZA)**m * exp(-n * sec(SZA)), SZA in radians.
#: Coefficients from the Master Chemical Mechanism v3.3.1 (University of York), fitted
#: to a two-stream isotropic scattering model with the proper cross-sections and quantum
#: yields. These are published constants, not anything we tuned.
MCM = {
    #  reaction                     l          m       n
    "no2":  (1.165e-2, 0.244, 0.267),   # NO2 -> NO + O(3P)   ... makes ozone
    "o1d":  (6.073e-5, 1.743, 0.474),   # O3  -> O(1D) + O2   ... makes OH
    "o3p":  (4.775e-4, 0.298, 0.080),   # O3  -> O(3P) + O2
}

#: Angstrom exponent for urban aerosol, used to shift AOD from 550 nm to the UV.
#: Aerosol is optically thicker at shorter wavelengths, so the UV attenuation relevant
#: to photolysis is larger than the 550 nm figure CAMS reports. 1.2 is typical for the
#: fine, combustion-dominated aerosol of the Indo-Gangetic Plain in winter.
ANGSTROM = 1.2

#: Effective photolysis wavelength, nm. J(NO2) is driven by roughly 330-420 nm.
J_WAVELENGTH_NM = 380.0

#: Single-scattering albedo and the share of scattered light lost to the upward
#: hemisphere. Same physical reasoning as `feedback.py`, but the bracket is larger here:
#: actinic flux counts photons from all directions, so only absorption and true
#: backscatter remove a photon from the photolysis budget.
SSA_UV = 0.88          # Delhi's UV-absorbing brown/black carbon
UPSCATTER_UV = 0.18

#: Reported reductions in surface J(NO2) relative to an aerosol-free atmosphere:
#: 24% in summer and 30% in winter over Beijing (ACP 19, 9413, 2019).
#:
#: These are a REFERENCE RANGE to check our output against, NOT a fit target, and the
#: distinction matters. Beijing's aerosol peaks in winter; **Delhi's does not**. Measured
#: on our own panel, CAMS AOD averages 0.834 in April-June against 0.487 in
#: November-February - the pre-monsoon dust season is optically thicker than the winter
#: smoke season. Fitting a coefficient to reproduce Beijing's seasonal ORDER would have
#: forced Delhi's physics to match another city's climatology.
#:
#: So we fit nothing. The attenuation below is first-principles, and the reduction it
#: produces is reported for comparison against the 20-30% these studies span.
REFERENCE_REDUCTION = (0.20, 0.30)

#: Optical depth of a pristine atmosphere - the control, matching `feedback.py`.
AOD_BACKGROUND = 0.10


def _as_array(x) -> np.ndarray:
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype="float64", na_value=np.nan)
    return np.asarray(x, dtype="float64")


def clear_sky_j(zenith_deg, reaction: str = "no2") -> np.ndarray:
    """Clear-sky photolysis frequency, per second.

    Zero when the sun is below the horizon: there is no photolysis at night, and the
    MCM form would otherwise return a meaningless extrapolation past 90 degrees.
    """
    if reaction not in MCM:
        raise ValueError(f"unknown reaction {reaction!r}; have {sorted(MCM)}")
    l, m, n = MCM[reaction]
    z = np.clip(_as_array(zenith_deg), 0.0, 180.0)
    cos_z = np.cos(np.radians(z))
    lit = cos_z > 1e-3
    out = np.zeros_like(cos_z)
    cz = np.where(lit, cos_z, 1.0)          # placeholder to keep the power finite
    out = np.where(lit, l * cz ** m * np.exp(-n / cz), 0.0)
    return np.clip(out, 0.0, None)


def aod_at_uv(aod_550) -> np.ndarray:
    """Shift optical depth from CAMS's 550 nm to the photolysis-relevant UV.

    AOD(lambda) = AOD(550) * (lambda / 550) ** -angstrom. At 380 nm with an Angstrom
    exponent of 1.2 this multiplies the reported depth by about 1.55 - so using the
    550 nm value directly would understate UV attenuation by half.
    """
    factor = (J_WAVELENGTH_NM / 550.0) ** (-ANGSTROM)
    return np.clip(_as_array(aod_550), 0.0, 6.0) * factor


def attenuation(aod_550, zenith_deg, k: float = 1.0) -> np.ndarray:
    """Fraction of clear-sky photolysis that survives a given aerosol load.

    Extinction along the slant path, scaled by the share of that extinction which
    actually removes a photon from the actinic flux:

        loss     = (1 - exp(-tau_uv * m)) * [(1 - SSA) + SSA * upscatter]
        survives = 1 - k * loss

    `k` defaults to 1.0 and **nothing is fitted**. It exists only so a sensitivity test
    can vary the attenuation strength; every other term is fixed physics.
    """
    tau = aod_at_uv(aod_550)
    airmass = np.clip(optical_airmass(zenith_deg), 1.0, 20.0)
    extinction = 1.0 - np.exp(-tau * airmass)
    bracket = (1.0 - SSA_UV) + SSA_UV * UPSCATTER_UV
    loss = np.clip(k * extinction * bracket, 0.0, 0.95)
    return 1.0 - loss


def j_actual(zenith_deg, aod_550, reaction: str = "no2", k: float = 1.0) -> np.ndarray:
    """Photolysis frequency under a given aerosol load."""
    return clear_sky_j(zenith_deg, reaction) * attenuation(aod_550, zenith_deg, k)


# ─── Calibration ─────────────────────────────────────────────────────────────
@dataclass
class PhotolysisModel:
    """Attenuation strength and the reduction it produces.

    `k` is 1.0: the attenuation is first-principles and **nothing is fitted**. The field
    exists so a sensitivity test can vary it, not because it is tuned.
    """
    k: float
    summer_reduction: float
    winter_reduction: float
    overall_reduction: float
    n_summer: int
    n_winter: int
    in_reference_range: bool
    method: str = "first-principles-unfitted"

    def to_dict(self) -> dict:
        return {kk: (round(v, 4) if isinstance(v, float) else v)
                for kk, v in asdict(self).items()}


DEFAULT = PhotolysisModel(k=1.0, summer_reduction=float("nan"),
                          winter_reduction=float("nan"), overall_reduction=float("nan"),
                          n_summer=0, n_winter=0, in_reference_range=False,
                          method="first-principles-unfitted")


def _daytime_reduction(zen: np.ndarray, aod: np.ndarray, k: float) -> float:
    """Mean fractional reduction in J(NO2) over daylight hours, versus aerosol-free.

    Weighted by clear-sky J so bright hours count for more than twilight, which is what
    a "mean reduction in photolysis" means physically.
    """
    clear = clear_sky_j(zen, "no2")
    lit = clear > 1e-6
    if not lit.any():
        return float("nan")
    att = attenuation(aod[lit], zen[lit], k)
    w = clear[lit]
    ok = np.isfinite(att) & np.isfinite(w)
    if not ok.any():
        return float("nan")
    return float(1.0 - np.sum(w[ok] * att[ok]) / np.sum(w[ok]))


def describe(df: pd.DataFrame, *, aod_col: str = "cams_aod",
             k: float = 1.0) -> PhotolysisModel:
    """Report the reduction this model produces, for comparison with published values.

    Deliberately **not** a calibration. An earlier version fitted `k` so that the
    seasonal means reproduced Beijing's 24% summer / 30% winter split, and the fit could
    not converge on the right ORDER - because Delhi's aerosol seasonality is reversed
    (AOD 0.834 in AMJ against 0.487 in NDJF, measured on our panel). Forcing agreement
    would have imported another city's climatology into Delhi's physics.

    The honest arrangement: the optics stand on Beer-Lambert plus a scattering bracket,
    and this function simply states what reduction that yields so a reader can compare
    it to the 20-30% the literature spans.
    """
    need = {"time", "lat", "lon", aod_col}
    if df.empty or not need.issubset(df.columns):
        return DEFAULT
    work = df[["time", "lat", "lon", aod_col]].dropna()
    if len(work) < 500:
        return DEFAULT

    zen = solar_zenith_deg(work["time"], work["lat"], work["lon"])
    aod = work[aod_col].to_numpy(dtype="float64")
    month = pd.to_datetime(work["time"], utc=True).dt.tz_convert("Asia/Kolkata").dt.month
    summer = month.isin([4, 5, 6]).to_numpy()
    winter = month.isin([11, 12, 1, 2]).to_numpy()

    overall = _daytime_reduction(zen, aod, k)
    lo, hi = REFERENCE_REDUCTION
    return PhotolysisModel(
        k=k,
        summer_reduction=_daytime_reduction(zen[summer], aod[summer], k) if summer.any() else float("nan"),
        winter_reduction=_daytime_reduction(zen[winter], aod[winter], k) if winter.any() else float("nan"),
        overall_reduction=overall,
        n_summer=int(summer.sum()), n_winter=int(winter.sum()),
        in_reference_range=bool(overall == overall and lo <= overall <= hi))


# ─── What can and cannot validate this ──────────────────────────────────────
#
# THE VALIDATION THAT DID NOT WORK, AND WHY IT IS RECORDED HERE
# -------------------------------------------------------------
# The plan for this module was to check the modelled attenuation against a measured one:
# Open-Meteo serves `uv_index` and `uv_index_clear_sky`, and their ratio looked like an
# observed actinic attenuation factor. It is not. Three measurements killed it:
#
#   1. `uv_index_clear_sky` means CLOUD-free, not aerosol-free. At cloud cover below 5%
#      the ratio is 0.998 - no attenuation at all - while mean AOD over those same hours
#      is 0.41. Aerosol is already inside both the numerator and the denominator.
#   2. The ratio tracks cloud, not aerosol: it falls 0.998 -> 0.963 -> 0.925 -> 0.903 ->
#      0.841 across rising cloud bands, while within clear skies a threefold rise in AOD
#      moves it only from 0.998 to 0.955.
#   3. Open-Meteo's broadband radiation has the same problem. At a fixed sun angle
#      (zenith 35-45 degrees) in clear skies, surface shortwave reads 750, 761 and
#      762 W/m2 across AOD bands 0-0.4, 0.4-0.7 and 0.7-1.5. Flat. The radiation scheme
#      carries a CLIMATOLOGICAL aerosol, not the day's actual load.
#
# So no Open-Meteo radiation product can validate aerosol optics - there is no daily
# aerosol signal in any of them to compare against. Saying so is more useful than
# quietly dropping the check, and it also *confirms* the assumption `feedback.py` was
# built on: the driving shortwave contains a climatological aerosol that must be divided
# out before a real load is applied.
#
# WHAT DOES VALIDATE IT
# ---------------------
# The ozone response itself, against station observations: does adding photolysis terms
# improve the O3 forecast, and is the model-derived AOD-to-ozone sensitivity near the
# published Delhi figure of roughly -25% ozone per 50% AOD reduction? That is validation
# against measurements rather than against an intermediate quantity, and it is stronger.
# It lives in `validate.py`, not here.


def cloud_attenuation_check(df: pd.DataFrame, *,
                            uv_col: str = "cams_uv",
                            uv_clear_col: str = "cams_uv_clear_sky") -> dict:
    """Measure what `uv_index / uv_index_clear_sky` actually responds to.

    Kept, and deliberately renamed, because it is the evidence for the note above rather
    than a validation of this module. It reports the ratio's correlation with cloud and
    with AOD so anyone can re-run the check that ruled it out.
    """
    need = {uv_col, uv_clear_col, "cloud_cover", "cams_aod"}
    missing = need - set(df.columns)
    if missing:
        return {"available": False, "reason": f"missing columns: {sorted(missing)}"}

    work = df[list(need)].dropna()
    work = work[work[uv_clear_col] > 0.5]
    if len(work) < 100:
        return {"available": False, "reason": f"only {len(work)} usable hours"}

    ratio = (work[uv_col] / work[uv_clear_col]).clip(0.0, 1.0)
    clear = work["cloud_cover"] < 10.0
    out = {
        "available": True,
        "n": int(len(work)),
        "corr_with_cloud": round(float(ratio.corr(work["cloud_cover"])), 3),
        "corr_with_aod": round(float(ratio.corr(work["cams_aod"])), 3),
        "mean_ratio_clear_skies": round(float(ratio[clear].mean()), 3) if clear.any() else None,
        "verdict": ("measures CLOUD attenuation; aerosol is present in both the index and "
                    "its clear-sky reference, so this cannot validate aerosol optics"),
    }
    return out


# ─── Feature generation ──────────────────────────────────────────────────────
def add_features(df: pd.DataFrame, model: PhotolysisModel | None = None,
                 *, aod_col: str = "cams_aod") -> pd.DataFrame:
    """Attach photolysis features for the ozone and NO2 heads.

    `j_no2_ratio` is the important one: the fraction of clear-sky photolysis surviving
    the current aerosol load. It separates "dim because it is December" from "dim
    because the air is full of smoke", which a raw radiation feature cannot do.
    """
    out = df.copy()
    if not {"time", "lat", "lon"}.issubset(out.columns):
        return out
    m = model or DEFAULT

    zen = solar_zenith_deg(out["time"], out["lat"], out["lon"])
    out["solar_zenith_deg"] = zen
    out["j_no2_clear"] = clear_sky_j(zen, "no2")
    out["j_o1d_clear"] = clear_sky_j(zen, "o1d")

    if aod_col in out.columns:
        aod = pd.to_numeric(out[aod_col], errors="coerce").to_numpy()
        att = attenuation(np.nan_to_num(aod, nan=AOD_BACKGROUND), zen, m.k)
        att = np.where(np.isfinite(aod), att, np.nan)
        out["j_attenuation"] = att
        out["j_no2"] = out["j_no2_clear"] * att
        out["j_o1d"] = out["j_o1d_clear"] * att
        # The pristine counterfactual, so a model can see how much photolysis the
        # aerosol removed rather than only what is left.
        att_clean = attenuation(np.full(len(out), AOD_BACKGROUND), zen, m.k)
        out["j_no2_pristine"] = out["j_no2_clear"] * att_clean
        out["j_no2_deficit"] = out["j_no2_pristine"] - out["j_no2"]
        out["j_no2_ratio"] = np.where(out["j_no2_pristine"] > 1e-9,
                                      out["j_no2"] / out["j_no2_pristine"], np.nan)
    return out
