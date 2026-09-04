"""The two-way coupling — chemistry acting back on meteorology.

This module is the reason the project exists. Every AQI forecaster treats weather as an
input: wind disperses, rain scavenges, a shallow boundary layer concentrates. That is
one direction only. The problem statement asks for the other one as well —

    "dense concentrations of aerosols (PM2.5) block sunlight, altering local
     temperatures, wind patterns, and planetary boundary layer (PBL) heights"

— and calls ignoring it a source of "significant inaccuracies".

THE MECHANISM, IN FIVE STEPS
-----------------------------
Each step is a separate, individually checkable piece of physics. None is a fitted
black box, and each carries the published Delhi range it must land inside.

    1. PM2.5  -> AOD          aerosol mass becomes optical depth
    2. AOD    -> shortwave    Beer-Lambert extinction; less sun reaches the ground
    3. dSW    -> dT           surface energy balance; less sun means less heating
    4. dT     -> dPBL         encroachment; less heating grows a shallower mixed layer
    5. dPBL   -> dPM2.5       box model; a shallower layer concentrates the same mass

Step 5 feeds step 1. That circularity is the whole point, and it is why this cannot be
evaluated in a single pass — it has to be **solved**.

HOW IT IS SOLVED
----------------
Damped fixed-point iteration. A naive loop can run away: more aerosol dims more sun,
which lowers the lid, which raises concentration, which dims more sun. Real atmospheres
are held in check by advection and entrainment that a single-column model does not
resolve, so we impose that restraint explicitly — a relaxation factor, hard clips on
every response, an iteration cap, and a divergence flag that is **surfaced rather than
swallowed**. A run that fails to converge reports the uncoupled answer and says so.

WHAT THIS IS NOT
----------------
It is not radiative transfer. There is no spectral integration, no vertical layering,
no aerosol microphysics. It is a parameterised surrogate for the dominant feedback,
calibrated against an operational coupled model and bounded by published observations.
Saying so plainly is not a weakness in the pitch; claiming otherwise would be.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd

from . import config as C

# ─── Optical properties of Delhi's aerosol ───────────────────────────────────
#: Single-scattering albedo. 1.0 is purely scattering; lower means more absorbing.
#: Delhi's winter aerosol carries a lot of black carbon from combustion, so it absorbs
#: appreciably — reported values for the Indo-Gangetic Plain cluster around 0.85-0.92.
SSA = 0.90

#: Upscatter fraction: the share of scattered light sent back to space rather than
#: forward to the ground. Forward scattering dominates for particles of this size, so
#: most scattered light still arrives — only the backscattered part is lost.
UPSCATTER = 0.15

#: Aerodynamic resistance near the surface, s/m. Sets how much a change in sensible
#: heat flux moves the 2 m temperature. ~50 s/m is typical for daytime conditions.
AERO_RESISTANCE = 50.0


def _as_array(x, index=None) -> np.ndarray:
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype="float64", na_value=np.nan)
    return np.asarray(x, dtype="float64")


# ─── Step 0: where is the sun ────────────────────────────────────────────────
def solar_zenith_deg(times, lat, lon) -> np.ndarray:
    """Solar zenith angle in degrees. Needed for optical airmass.

    A standard low-precision solar position algorithm — accurate to a fraction of a
    degree, which is far finer than anything else in this chain. Times must be UTC.
    """
    t = pd.to_datetime(pd.Series(times), utc=True)
    doy = t.dt.dayofyear.to_numpy(dtype="float64")
    hour = (t.dt.hour + t.dt.minute / 60.0).to_numpy(dtype="float64")
    lat_a = _as_array(lat)
    lon_a = _as_array(lon)

    # Declination and the equation of time.
    g = np.radians(357.529 + 0.98560028 * (doy - 1))
    decl = np.radians(23.44) * np.sin(np.radians(360.0 / 365.24 * (doy - 80.0)))
    eot = 4.0 * (1.9148 * np.sin(g) + 0.02 * np.sin(2 * g))  # minutes, approximate

    solar_time = hour + lon_a / 15.0 + eot / 60.0
    hour_angle = np.radians(15.0 * (solar_time - 12.0))

    phi = np.radians(lat_a)
    cos_z = np.sin(phi) * np.sin(decl) + np.cos(phi) * np.cos(decl) * np.cos(hour_angle)
    return np.degrees(np.arccos(np.clip(cos_z, -1.0, 1.0)))


def optical_airmass(zenith_deg) -> np.ndarray:
    """Relative optical airmass — the path length through the atmosphere, 1.0 overhead.

    Kasten & Young's formula rather than plain ``1/cos(z)``, which diverges at the
    horizon where a large share of winter Delhi's daylight hours actually sit.
    """
    z = np.clip(_as_array(zenith_deg), 0.0, 90.0)
    cz = np.cos(np.radians(z))
    return 1.0 / (cz + 0.50572 * (96.07995 - z) ** -1.6364)


# ─── Step 1: PM2.5 -> AOD ────────────────────────────────────────────────────
@dataclass
class AODModel:
    """How optical depth responds to a change in surface PM2.5.

    Deliberately only an **elasticity**, not an absolute predictor. Measured on 26,496
    paired CAMS hours, absolute AOD is barely predictable from surface PM2.5
    (r² = 0.10, rising only to 0.38 with humidity and dust) because AOD integrates the
    whole column including aerosol above the boundary layer. But the *sensitivity* —
    how much AOD moves when surface mass moves — is exactly what the feedback needs,
    and that is well determined.
    """
    b: float                  # elasticity dln(AOD)/dln(PM2.5)
    r2: float
    n: int
    method: str = "cams-paired-elasticity"

    def perturb(self, aod_base, pm_new, pm_ref) -> np.ndarray:
        """Scale a baseline AOD to a new PM2.5, holding everything else fixed."""
        base = _as_array(aod_base)
        new = np.clip(_as_array(pm_new), 0.1, None)
        ref = np.clip(_as_array(pm_ref), 0.1, None)
        out = base * (new / ref) ** self.b
        return np.clip(out, 0.01, 5.0)

    def to_dict(self) -> dict:
        return asdict(self)


#: Used when calibration is impossible (no CAMS coverage for the window). Value is the
#: mid-point of the fitted elasticities we measured; flagged so it is never mistaken
#: for a fit.
DEFAULT_AOD = AODModel(b=0.45, r2=float("nan"), n=0, method="literature-default")


def calibrate_aod(df: pd.DataFrame) -> AODModel:
    """Fit the AOD elasticity on CAMS's own paired PM2.5 and AOD output.

    Humidity and dust are included as controls, not because we want to predict them but
    because leaving them out biases the PM2.5 coefficient: humid hours have both higher
    AOD and (through hygroscopic growth) different mass, so an uncontrolled regression
    attributes humidity's effect to mass. Only the PM2.5 coefficient is kept.
    """
    need = ["cams_pm25", "cams_aod", "relative_humidity_2m"]
    if any(c not in df.columns for c in need):
        return DEFAULT_AOD
    sub = df[need + (["cams_dust"] if "cams_dust" in df.columns else [])].dropna()
    sub = sub[(sub["cams_pm25"] > 1.0) & (sub["cams_aod"] > 0.01)]
    if len(sub) < 500:
        return DEFAULT_AOD

    y = np.log(sub["cams_aod"].to_numpy())
    cols = [np.log(sub["cams_pm25"].to_numpy()),
            sub["relative_humidity_2m"].to_numpy() / 100.0]
    if "cams_dust" in sub.columns:
        cols.append(np.log(np.clip(sub["cams_dust"].to_numpy(), 0.1, None)))
    X = np.column_stack([np.ones(len(y))] + cols)

    ok = np.isfinite(X).all(axis=1) & np.isfinite(y)
    X, y = X[ok], y[ok]
    if len(y) < 500:
        return DEFAULT_AOD
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ coef
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float(((y - pred) ** 2).sum()) / ss_tot if ss_tot > 0 else 0.0

    # An elasticity outside [0.05, 1.2] is not physical: below it aerosol would be
    # optically inert, above it optical depth would grow faster than the mass causing
    # it. Refuse rather than propagate a bad fit.
    b = float(coef[1])
    if not (0.05 <= b <= 1.2):
        return DEFAULT_AOD
    return AODModel(b=b, r2=float(r2), n=int(len(y)))


# ─── Step 2: AOD -> surface shortwave ────────────────────────────────────────
def shortwave_loss_fraction(aod, airmass) -> np.ndarray:
    """Fraction of surface shortwave removed by aerosol.

    Beer-Lambert gives the total extinction along the slant path,
    ``1 - exp(-tau * m)``. But extinction is not all *loss to the surface*: light that
    is scattered forward still arrives, just from a different direction. Only the
    absorbed part and the back-scattered part are genuinely lost:

        loss = (1 - exp(-tau*m)) * [ (1 - SSA) + SSA * upscatter ]

    With SSA 0.90 and an upscatter fraction of 0.15 that bracket is 0.235, so a
    typical Delhi winter AOD of 0.6 at airmass 2 removes about 16% of surface
    shortwave — squarely inside the 15-30% reported for the Indo-Gangetic Plain.
    Using raw Beer-Lambert instead would have claimed 70%, which is wildly wrong.
    """
    tau = np.clip(_as_array(aod), 0.0, 5.0)
    m = np.clip(_as_array(airmass), 1.0, 20.0)
    extinction = 1.0 - np.exp(-tau * m)
    surface_bracket = (1.0 - SSA) + SSA * UPSCATTER
    return np.clip(extinction * surface_bracket, 0.0, 0.9)


#: Optical depth of a pristine atmosphere — the counterfactual the ablation compares
#: against. This is the "no aerosol radiative effect" state: not a real Delhi day, but
#: exactly the control the problem statement's premise needs, and the reference the
#: published Delhi feedback magnitudes are themselves quoted against.
AOD_BACKGROUND = 0.10

#: Fallback for the aerosol load the weather model's own radiation scheme assumed, used
#: only when a climatology cannot be computed from data.
AOD_CLIMATOLOGY_DEFAULT = 0.45


def climatological_aod(df: pd.DataFrame) -> np.ndarray:
    """The aerosol load the driving meteorology implicitly already contains.

    This matters for a reason that is easy to miss and fatal to get wrong. The
    shortwave radiation Open-Meteo hands us is **not** clear-sky: its radiation scheme
    already dims the sun using a climatological aerosol. If we applied the full
    present-day aerosol dimming on top of that number, we would count the
    climatological part twice.

    So we recover the true clear-sky value by removing the climatological loss first,
    then re-apply whichever load the scenario calls for. The climatology is estimated
    per cell and calendar month from CAMS's own AOD, which is the closest thing
    available to what a global model would have assumed.
    """
    if "cams_aod" not in df.columns:
        return np.full(len(df), AOD_CLIMATOLOGY_DEFAULT)
    aod = pd.to_numeric(df["cams_aod"], errors="coerce")
    if aod.notna().sum() < 24:
        return np.full(len(df), AOD_CLIMATOLOGY_DEFAULT)
    key = [df["cell_id"], pd.to_datetime(df["time"], utc=True).dt.month] \
        if "cell_id" in df.columns else [pd.to_datetime(df["time"], utc=True).dt.month]
    clim = aod.groupby(key).transform("median")
    return clim.fillna(aod.median()).clip(0.05, 2.0).to_numpy()


def attenuate_shortwave(sw_baseline, aod_target, aod_climatology, airmass):
    """Surface shortwave under a given aerosol load.

    Three optical depths are in play and conflating any two of them produces nonsense:

      * ``aod_climatology`` — what the driving weather model already assumed, and
        therefore what is already baked into ``sw_baseline``;
      * ``aod_target``      — the load we want to evaluate;
      * :data:`AOD_BACKGROUND` — a pristine atmosphere, the ablation's control.

    We divide out the climatological loss to recover clear-sky irradiance, then apply
    the target loss. Returns both, because the clear-sky value is what makes the
    coupled and uncoupled runs comparable.
    """
    sw = np.clip(_as_array(sw_baseline), 0.0, None)
    loss_clim = shortwave_loss_fraction(aod_climatology, airmass)
    # Guard the division: as the climatological loss approaches 1 the implied clear-sky
    # irradiance would explode.
    sw_clear = sw / np.clip(1.0 - loss_clim, 0.15, 1.0)
    loss_target = shortwave_loss_fraction(aod_target, airmass)
    return np.clip(sw_clear * (1.0 - loss_target), 0.0, None), sw_clear


# ─── Step 3: shortwave -> temperature ────────────────────────────────────────
def delta_temperature(d_sw) -> np.ndarray:
    """Near-surface temperature response to a change in absorbed shortwave.

    Surface energy balance. A shortwave deficit reduces the energy available at the
    surface; the fraction (1 - albedo) is absorbed, of which a Bowen-ratio share
    becomes sensible heat, and that change in heat flux moves the air temperature
    through the aerodynamic resistance:

        dT = dSW * (1 - albedo) * f_sensible * r_a / (rho * cp)

    A 100 W/m² deficit gives about 1.2 K of cooling — inside the 0.5-2 K reported for
    Delhi's winter aerosol dimming. Signed so a shortwave DEFICIT returns a NEGATIVE dT.
    """
    dsw = _as_array(d_sw)
    dt = (dsw * (1.0 - C.SURFACE_ALBEDO) * C.SENSIBLE_HEAT_FRACTION
          * AERO_RESISTANCE / (C.RHO_AIR * C.CP_AIR))
    return np.clip(dt, -C.MAX_DELTA_T, C.MAX_DELTA_T)


# ─── Step 4: temperature -> boundary layer ───────────────────────────────────
def pbl_response(pbl_base, sw_base, sw_new) -> np.ndarray:
    """New mixing depth after a change in surface heating.

    The convective boundary layer grows by encroachment: it deepens as the accumulated
    surface heat flux erodes the stable air above it. For a constant lapse rate the
    classical result is h proportional to the square root of accumulated heat, so

        h_new / h_old = sqrt( H_new / H_old )

    A 20% cut in heating therefore gives sqrt(0.8) = 0.89, an 11% shallower layer —
    inside the 10-30% suppression reported for Delhi.

    At night there is no convective growth to suppress: the layer is mechanically
    driven, so heating changes barely touch it. The response is faded out as the sun
    goes down rather than applied to a nocturnal layer it does not govern.
    """
    h = _as_array(pbl_base)
    s0 = np.clip(_as_array(sw_base), 0.0, None)
    s1 = np.clip(_as_array(sw_new), 0.0, None)

    with np.errstate(divide="ignore", invalid="ignore"):
        # Not clipped at 1.0 here: the pristine control run has MORE sun than the
        # baseline and must be allowed to produce a deeper layer.
        ratio = np.where(s0 > 1.0, np.sqrt(np.clip(s1 / s0, 0.0, 4.0)), 1.0)
    ratio = np.where(np.isfinite(ratio), ratio, 1.0)

    # Fade the effect out below ~50 W/m²: no convective growth, nothing to suppress.
    daylight = np.clip(s0 / 50.0, 0.0, 1.0)
    ratio = 1.0 - (1.0 - ratio) * daylight

    # Bounded BOTH ways. Less sun gives a shallower layer, but more sun (the pristine
    # counterfactual) legitimately gives a deeper one, and clipping the ratio at 1.0
    # would silently forbid the control run from ever differing from the baseline —
    # which would zero out the very effect being measured.
    ratio = np.clip(ratio, 1.0 - C.MAX_PBL_SUPPRESSION, 1.0 + C.MAX_PBL_SUPPRESSION)
    return np.clip(h * ratio, C.MIN_PBL_M, C.MAX_PBL_M)


# ─── Step 4b: boundary layer -> wind ─────────────────────────────────────────
def wind_response(wind_ms, pbl_base, pbl_new) -> np.ndarray:
    """Surface wind under a suppressed boundary layer.

    The chain the problem statement names is temperature, **wind** and PBL height, and
    Round 1 modelled only two of the three. The missing link is momentum: surface wind is
    sustained partly by turbulent transport of momentum down from the faster air aloft.
    Aerosol cooling weakens the heat flux that drives that turbulence, so less momentum
    reaches the surface and the wind slackens.

    Scaled from the published ratio rather than fitted: wind falls 1.6-4.3% in the same
    experiments where the boundary layer falls 13-21%, so the response is about a fifth
    of the PBL suppression. Capped, because the relationship is linearised around a small
    perturbation and has no business extrapolating to a calm.

    **This is a small term and is presented as one.** It completes the loop rather than
    improving the forecast, and conflating those two would be overclaiming.
    """
    u = np.clip(_as_array(wind_ms), 0.0, None)
    h0 = np.clip(_as_array(pbl_base), C.MIN_PBL_M, None)
    h1 = np.clip(_as_array(pbl_new), C.MIN_PBL_M, None)

    # Two-sided, deliberately. A SHALLOWER layer mixes down less momentum and the wind
    # slackens; a DEEPER one mixes down more and it freshens. Clipping this to the
    # suppression side only was the same mistake made once already in `pbl_response`,
    # and it had the same consequence: the pristine control could not differ from the
    # baseline, so the measured wind response came out at 0.46% against a published
    # 1.6-4.3% and failed its own literature gate.
    change = (h0 - h1) / np.maximum(h0, 1e-6)
    factor = np.clip(1.0 - C.WIND_RESPONSE_RATIO * change,
                     1.0 - C.MAX_WIND_SUPPRESSION, 1.0 + C.MAX_WIND_SUPPRESSION)
    return u * factor


# ─── Step 5: boundary layer -> concentration ─────────────────────────────────
def concentration_response(pm_base, depth_base, depth_new) -> np.ndarray:
    """Box model: the same emitted mass in a shallower layer is more concentrated.

    C_new / C_old = h_old / h_new, capped. The cap matters — as the mixing depth
    approaches its floor the ratio would diverge, and a 30 m nocturnal layer is already
    at the edge of what a bulk box model can honestly describe.
    """
    pm = _as_array(pm_base)
    h0 = np.clip(_as_array(depth_base), C.MIN_PBL_M, None)
    h1 = np.clip(_as_array(depth_new), C.MIN_PBL_M, None)
    return pm * np.clip(h0 / h1, 1.0, 1.0 / (1.0 - C.MAX_PBL_SUPPRESSION))


# ─── The solver ──────────────────────────────────────────────────────────────
@dataclass
class CouplingResult:
    frame: pd.DataFrame
    iterations: int
    converged: bool
    diverged_rows: int
    max_residual: float
    aod_model: dict = field(default_factory=dict)

    def summary(self) -> dict:
        f = self.frame
        if f.empty:
            return {"available": False}
        def _m(col):
            s = pd.to_numeric(f.get(col), errors="coerce")
            return float(s.mean()) if s.notna().any() else float("nan")
        day = f[pd.to_numeric(f.get("shortwave_radiation"), errors="coerce") > 50]
        return {
            "available": True,
            "rows": int(len(f)),
            "iterations": self.iterations,
            "converged": self.converged,
            "diverged_rows": self.diverged_rows,
            "max_residual_ugm3": round(self.max_residual, 3),
            "mean_sw_reduction_pct": round(100 * _m("sw_reduction_frac"), 2),
            "mean_dT_daytime_k": round(
                float(pd.to_numeric(day.get("delta_t_k"), errors="coerce").mean())
                if len(day) else float("nan"), 3),
            "mean_pbl_suppression_pct": round(100 * _m("pbl_suppression_frac"), 2),
            "mean_pm_amplification_pct": round(100 * _m("pm_amplification_frac"), 2),
            "mean_wind_reduction_pct": round(100 * _m("wind_reduction_frac"), 2),
            "aod_model": self.aod_model,
        }


def solve(
    df: pd.DataFrame,
    *,
    pm_col: str = "pm25_uncoupled",
    aod_model: AODModel | None = None,
    omega: float = C.COUPLING_OMEGA,
    max_iter: int = C.COUPLING_MAX_ITER,
    tol: float = C.COUPLING_TOL,
) -> CouplingResult:
    """Run the coupled system to convergence.

    Input frame needs: ``time``, ``lat``, ``lon``, ``shortwave_radiation``,
    ``mixing_depth_m``, the uncoupled PM2.5 in ``pm_col``, and ideally ``cams_aod`` and
    ``cams_pm25`` for the optical baseline.

    Returns the original frame plus the coupled state and, just as importantly, the
    per-step diagnostics — ``aod_coupled``, ``sw_reduction_frac``, ``delta_t_k``,
    ``pbl_suppression_frac``, ``pm_amplification_frac``. Those are what let a reviewer
    check each piece of physics separately instead of taking the output on trust, and
    what the ablation and the dashboard both read.
    """
    if df.empty or pm_col not in df.columns:
        return CouplingResult(df, 0, False, 0, float("nan"), {})

    out = df.copy().reset_index(drop=True)
    model = aod_model or DEFAULT_AOD

    pm0 = _as_array(out[pm_col])          # prediction WITHOUT the radiative feedback
    depth0 = _as_array(out["mixing_depth_m"])
    sw0 = _as_array(out["shortwave_radiation"])

    zen = solar_zenith_deg(out["time"], out["lat"], out["lon"])
    airmass = optical_airmass(zen)

    # Three optical states, per the module docstring. `aod_clim` is what the driving
    # meteorology already assumed and must be divided out; AOD_BACKGROUND is the
    # pristine control; `aod_actual` is iterated because it depends on the PM2.5 that
    # depends on it.
    aod_clim = climatological_aod(out)
    aod_cams = _as_array(out["cams_aod"]) if "cams_aod" in out.columns else np.full(len(out), np.nan)
    aod_cams = np.where(np.isfinite(aod_cams), aod_cams, aod_clim)
    pm_ref = _as_array(out["cams_pm25"]) if "cams_pm25" in out.columns else np.full(len(out), np.nan)
    pm_ref = np.where(np.isfinite(pm_ref) & (pm_ref > 1.0), pm_ref, pm0)

    # --- the control run: a pristine atmosphere, computed once ---
    sw_pristine, sw_clear = attenuate_shortwave(sw0, AOD_BACKGROUND, aod_clim, airmass)
    depth_pristine = pbl_response(depth0, sw0, sw_pristine)

    pm = pm0.copy()
    residual = np.full(len(out), np.nan)
    iterations = 0
    aod_actual = aod_cams.copy()
    sw_actual = sw0.copy()
    depth_actual = depth0.copy()
    d_t = np.zeros(len(out))

    for iterations in range(1, max_iter + 1):
        # 1. mass -> optical depth (CAMS baseline, scaled by how far our PM2.5 differs)
        aod_actual = model.perturb(aod_cams, pm, pm_ref)
        # 2. optical depth -> surface shortwave
        sw_actual, _ = attenuate_shortwave(sw0, aod_actual, aod_clim, airmass)
        # 3. shortwave deficit -> temperature response
        d_t = delta_temperature(sw_actual - sw_pristine)
        # 4. heating -> mixing depth
        depth_actual = pbl_response(depth0, sw0, sw_actual)
        # 5. mixing depth -> concentration, measured against the pristine control
        pm_target = concentration_response(pm0, depth_pristine, depth_actual)

        pm_next = pm + omega * (pm_target - pm)   # damped update
        residual = np.abs(pm_next - pm)
        pm = pm_next
        if np.nanmax(residual) < tol:
            break

    finite = np.isfinite(residual)
    max_res = float(np.nanmax(residual)) if finite.any() else float("nan")
    diverged = int(np.sum(residual > tol)) if finite.any() else 0
    converged = bool(finite.any() and max_res < tol)

    # Any row that did not settle falls back to its uncoupled value. A number we could
    # not solve for is worse than no number at all, and silently shipping it would put
    # an unbounded error into the very result the project is judged on.
    if diverged:
        bad = residual > tol
        pm = np.where(bad, pm0, pm)
        depth_actual = np.where(bad, depth_pristine, depth_actual)
        d_t = np.where(bad, 0.0, d_t)

    # --- wind, the third meteorological variable the PS names -----------------
    if "layer_wind_ms" in out.columns or "wind_speed_10m" in out.columns:
        base_col = "layer_wind_ms" if "layer_wind_ms" in out.columns else "wind_speed_10m"
        u0 = _as_array(out[base_col])
        u_pristine = wind_response(u0, depth0, depth_pristine)
        u_actual = wind_response(u0, depth0, depth_actual)
        out["wind_coupled_ms"] = u_actual
        out["wind_pristine_ms"] = u_pristine
        out["wind_reduction_frac"] = np.where(
            u_pristine > 0.05, np.clip((u_pristine - u_actual) / np.maximum(u_pristine, 1e-6), 0, 1),
            np.nan)
        # The ventilation coefficient is depth x wind, so both coupled terms feed it.
        out["ventilation_coeff_coupled"] = depth_actual * u_actual

    out["pm25_coupled"] = pm
    out["aod_coupled"] = aod_actual
    out["sw_coupled"] = sw_actual
    out["sw_pristine"] = sw_pristine
    out["sw_clear_sky"] = sw_clear
    out["mixing_depth_pristine_m"] = depth_pristine
    out["mixing_depth_coupled_m"] = depth_actual
    out["delta_t_k"] = d_t

    # Diagnostics are all measured against the PRISTINE control, which is the reference
    # the published Delhi magnitudes use. Daylight only for the radiative ones: a
    # "percentage of zero shortwave" at midnight is not a number.
    lit = sw_pristine > 1.0
    out["sw_reduction_frac"] = np.where(
        lit, np.clip((sw_pristine - sw_actual) / np.maximum(sw_pristine, 1e-6), 0, 1), np.nan)
    out["pbl_suppression_frac"] = np.where(
        lit, np.clip((depth_pristine - depth_actual) / np.maximum(depth_pristine, 1e-6), 0, 1), np.nan)
    out["pm_amplification_frac"] = np.where(
        pm0 > 0.1, (pm - pm0) / np.maximum(pm0, 1e-6), np.nan)
    out["coupling_converged"] = (~(residual > tol)).astype("int8")

    return CouplingResult(out, iterations, converged, diverged, max_res, model.to_dict())


#: The regime the published figures actually describe. Delhi aerosol feedback studies
#: report winter haze episodes, where AOD routinely exceeds 0.5; a clean monsoon
#: afternoon at AOD 0.2 legitimately produces a smaller effect.
GATE_MIN_AOD = 0.5
GATE_MIN_SW = 50.0     # W m-2, daylight only


def check_against_literature(result: CouplingResult) -> dict:
    """Verdict on whether each step landed inside its published Delhi range.

    This is the acceptance gate: a physically absurd result should fail loudly during
    development rather than quietly on stage. A number outside these bounds means the
    model is WRONG, not merely surprising.

    **The comparison is restricted to the regime the literature describes.** Published
    Delhi values — 15-30% shortwave dimming, 10-30% boundary-layer suppression — come
    from *winter haze episodes* at high aerosol loading, in daylight. Averaging our
    output over clean monsoon afternoons and over nights (when the radiative feedback is
    correctly zero) and then comparing that to a winter-episode number compares two
    different quantities, and would fail a model that is behaving perfectly.

    So the gate evaluates high-AOD daylight hours, and the all-conditions figure is
    reported alongside it — clearly labelled — rather than being the thing judged.
    """
    f = result.frame
    if f.empty:
        return {"ok": False, "reason": "no rows"}

    s = result.summary()
    aod = pd.to_numeric(f.get("aod_coupled"), errors="coerce")
    sw = pd.to_numeric(f.get("sw_pristine"), errors="coerce")
    mask = (aod >= GATE_MIN_AOD) & (sw >= GATE_MIN_SW)
    sub = f[mask.fillna(False)]

    if len(sub) < 20:
        return {"ok": None, "reason": "too few high-aerosol daylight hours to judge",
                "n_in_regime": int(len(sub)), "all_conditions": s,
                "regime": {"min_aod": GATE_MIN_AOD, "min_sw_wm2": GATE_MIN_SW}}

    def _mean(col):
        v = pd.to_numeric(sub.get(col), errors="coerce")
        return float(v.mean()) if v.notna().any() else float("nan")

    values = {
        "sw_reduction_pct": 100 * _mean("sw_reduction_frac"),
        "dT_daytime_k": _mean("delta_t_k"),
        "pbl_suppression_pct": 100 * _mean("pbl_suppression_frac"),
        "pm_amplification_pct": 100 * _mean("pm_amplification_frac"),
    }
    values["wind_reduction_pct"] = 100 * _mean("wind_reduction_frac")
    bounds = {
        "wind_reduction_pct": (C.EXPECT_WIND_REDUCTION, 100),
        "sw_reduction_pct": (C.EXPECT_SW_REDUCTION, 100),
        "dT_daytime_k": (C.EXPECT_DT_COOLING, 1),
        "pbl_suppression_pct": (C.EXPECT_PBL_SUPPRESSION, 100),
        "pm_amplification_pct": (C.EXPECT_PM_AMPLIFICATION, 100),
    }
    checks = {}
    for name, value in values.items():
        (lo_f, hi_f), scale = bounds[name]
        lo, hi = lo_f * scale, hi_f * scale
        ok = bool(value == value and lo <= abs(value) <= hi)
        checks[name] = {"value": round(value, 3) if value == value else None,
                        "expected": [round(lo, 3), round(hi, 3)], "ok": ok}

    return {"ok": all(c["ok"] for c in checks.values()),
            "checks": checks,
            "n_in_regime": int(len(sub)),
            "regime": {"min_aod": GATE_MIN_AOD, "min_sw_wm2": GATE_MIN_SW,
                       "note": "high-aerosol daylight hours, matching the conditions "
                               "the published Delhi figures were measured in"},
            "all_conditions_for_reference": {
                "sw_reduction_pct": s["mean_sw_reduction_pct"],
                "dT_daytime_k": s["mean_dT_daytime_k"],
                "pbl_suppression_pct": s["mean_pbl_suppression_pct"],
                "pm_amplification_pct": s["mean_pm_amplification_pct"],
                "wind_reduction_pct": s.get("mean_wind_reduction_pct")},
            "converged": s["converged"], "iterations": s["iterations"]}
