"""Two-layer slab model: a mixed layer that breathes, and a residual layer that remembers.

WHY THIS EXISTS
---------------
The plume used to decide whether transported smoke reached the ground by comparing the
parcel's height against the lid. That is a *height* test, and the atmosphere does not
run one. Mixing is a rate, driven by turbulent kinetic energy, and a height test gets
two things wrong that matter over the Indo-Gangetic Plain:

  * **A numerical shock.** When the mixing height crosses the parcel height, the whole
    plume arrives at once. Real fumigation is a two to three hour process, and an
    instantaneous dump produces a spike that no monitor ever records.
  * **Missing dilution.** A growing boundary layer entrains polluted air from aloft AND
    grows the volume that air is diluted into. Those happen together. A gate models
    neither, so it mistimes the morning peak and overstates its amplitude.

Aircraft and lidar profiling during APHH-India found transported agricultural plumes
sitting in the residual layer over Delhi at 500 to 1500 m through the night, entirely
decoupled from a nocturnal boundary layer that can collapse below 50 m. That smoke
passes overhead without touching a monitor, and then arrives between 07:00 and 10:00
local time as the convective layer erodes the inversion and engulfs it. Delhi's
characteristic bimodal "W" diurnal PM2.5 profile is partly that fumigation, and a
single-layer model cannot produce it.

THE FORMULATION
---------------
Two control volumes. `Cm` is the mixed layer of depth `h`; `Cr` is the residual layer
filling from `h` up to a fixed domain top `Htop`.

    h dCm/dt = E - vd*Cm + Sm*h + we*(Cr - Cm)
      dCr/dt = Ar + Sr

`we = max(dh/dt, 0)` is the entrainment velocity: mass crosses the interface only while
the layer is growing. The elegance is in `we*(Cr - Cm)`, which is one term doing two
jobs. When the residual layer is dirtier it fumigates the surface; when it is cleaner it
dilutes it; when the layer is not growing it vanishes and the model degenerates to the
single box it replaces.

At sunset the layer collapses and the air abandoned above the new nocturnal height does
not disappear, it becomes residual layer. That transfer is a volume-weighted merge, and
forgetting it is how single-layer models lose mass across the diurnal transition.

Parameter values are the operational ones from the slab-model literature (Batchvarova
and Gryning; the CLASS family), listed in config with their ranges.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C


def entrainment_velocity(depth_m, dt_h: float = 1.0) -> np.ndarray:
    """we = max(dh/dt, 0), in m/s, from a diagnosed mixing-depth series.

    Entrainment happens only while the layer grows. On collapse the flux is not
    negative, it is zero: the mass goes to the residual layer through the evening
    transition instead, which is a different mechanism handled in `integrate`.

    Taking the derivative of the depth we already diagnose is preferable to the full
    Batchvarova-Gryning closure here, because that closure would re-derive a boundary
    layer height we have from the driving meteorology, and the two could disagree.
    """
    h = np.asarray(depth_m, dtype="float64")
    dh = np.zeros_like(h)
    dh[1:] = h[1:] - h[:-1]
    dh[0] = dh[1] if len(h) > 1 else 0.0
    return np.clip(dh / (dt_h * 3600.0), 0.0, C.MAX_ENTRAINMENT_MS)


def integrate(depth_m, into_mixed, into_residual, *, dt_h: float = 1.0,
              deposition_ms: float = C.DRY_DEPOSITION_MS,
              h_top_m: float = C.SLAB_TOP_M, substeps: int = 12) -> dict:
    """March the two-layer mass budget through a forecast.

    `depth_m` is (T,) mixing depth in metres. `into_mixed` and `into_residual` are
    (T, C) mass inputs per hour, already partitioned by whether the arriving smoke is
    inside the mixed layer or above it. Returns surface and residual concentration, both
    (T, C), plus the entrainment velocity actually used.

    Integrated with sub-hourly explicit steps because `we/h` becomes stiff right at
    sunrise, when the layer is shallow and growing fastest. Twelve substeps is a
    five-minute step, which the literature gives as the stable range, and `h` is floored
    so the term cannot blow up.
    """
    h = np.clip(np.asarray(depth_m, dtype="float64"), C.SLAB_MIN_DEPTH_M, h_top_m * 0.98)
    add_m = np.atleast_2d(np.asarray(into_mixed, dtype="float64"))
    add_r = np.atleast_2d(np.asarray(into_residual, dtype="float64"))
    if add_m.shape[0] != len(h):          # (C, T) handed in, transpose
        add_m, add_r = add_m.T, add_r.T
    n_t, n_c = add_m.shape

    we = entrainment_velocity(h, dt_h)
    cm = np.zeros(n_c)
    cr = np.zeros(n_c)
    out_m = np.zeros((n_t, n_c))
    out_r = np.zeros((n_t, n_c))
    dt = dt_h * 3600.0 / substeps

    for t in range(n_t):
        # Evening transition: the layer has collapsed, so the air between the old and
        # the new top is abandoned to the residual layer. Volume-weighted, because the
        # residual layer already holds air and this merges two reservoirs rather than
        # replacing one.
        if t > 0 and h[t] < h[t - 1]:
            old_r_depth = max(h_top_m - h[t - 1], 1.0)
            handed_over = h[t - 1] - h[t]
            new_r_depth = max(h_top_m - h[t], 1.0)
            cr = (cr * old_r_depth + cm * handed_over) / new_r_depth

        # Sources are spread across the hour rather than dropped in at its start, so a
        # single hour of heavy arrival cannot produce a spike the averaging would hide.
        src_m = add_m[t] / dt_h / substeps
        src_r = add_r[t] / dt_h / substeps

        for _ in range(substeps):
            exch = we[t] * (cr - cm) / max(h[t], C.SLAB_MIN_DEPTH_M)
            dep = deposition_ms * cm / max(h[t], C.SLAB_MIN_DEPTH_M)
            cm = np.clip(cm + dt * (exch - dep) + src_m, 0.0, None)
            cr = np.clip(cr + src_r, 0.0, None)
        out_m[t] = cm
        out_r[t] = cr

    return {"surface": out_m, "residual": out_r, "entrainment_ms": we}


def fumigation_diagnostics(times, surface, residual, entrainment_ms) -> dict:
    """What the two-layer scheme found that a lid gate could not report.

    The point of the upgrade is a claim about *timing*, so the diagnostic is about
    timing: when the residual layer discharges, how much of the surface load that
    morning came from aloft rather than from the ground, and whether the peak lands in
    the 07:00 to 10:00 local window the observations put it in.
    """
    t = pd.to_datetime(pd.Series(times), utc=True)
    local_hour = ((t.dt.hour + 5) % 24).to_numpy()      # IST is UTC+5:30
    surf = np.asarray(surface, dtype="float64")
    resid = np.asarray(residual, dtype="float64")
    if surf.ndim == 1:
        surf, resid = surf[:, None], resid[:, None]

    city = np.nanmean(surf, axis=1)
    aloft = np.nanmean(resid, axis=1)
    we = np.asarray(entrainment_ms, dtype="float64")

    window = (local_hour >= 7) & (local_hour <= 10)
    peak_i = int(np.nanargmax(city)) if np.isfinite(city).any() else 0
    reservoir_peak = float(np.nanmax(aloft)) if np.isfinite(aloft).any() else 0.0
    return {
        "available": True,
        "peak_local_hour": int(local_hour[peak_i]),
        "peak_in_fumigation_window": bool(window[peak_i]),
        "max_entrainment_ms": round(float(np.nanmax(we)), 4),
        "max_entrainment_m_per_h": round(float(np.nanmax(we) * 3600.0), 1),
        "residual_reservoir_peak_ugm3": round(reservoir_peak, 2),
        "mean_surface_in_window_ugm3": round(
            float(np.nanmean(city[window])) if window.any() else 0.0, 2),
        "mean_surface_overnight_ugm3": round(
            float(np.nanmean(city[(local_hour >= 22) | (local_hour <= 5)]))
            if ((local_hour >= 22) | (local_hour <= 5)).any() else 0.0, 2),
        "note": "Fumigation is rate-controlled by the entrainment velocity, so the "
                "residual layer discharges over hours rather than at the instant a lid "
                "is crossed. Observations over Delhi put that peak between 07:00 and "
                "10:00 local.",
    }
