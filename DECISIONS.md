# VayuChakra — decision and assumption log

Every non-obvious choice, why it was made, and what would reverse it.
Append-only. Newest at the bottom of each section.

**Target:** MoES / NCMRWF — *Air Pollution–Weather Coupled Forecasting System (Delhi NCR Focus)*
**Mode:** local development only. Nothing hosted. Nothing pushed until explicitly asked.

---

## Standing constraints (from the user, verbatim intent)

- Do **not** host on Render or anywhere. Local only.
- Push only when explicitly asked.
- Self-contained new folder, not a branch edit of AirGrid. AirGrid must keep working.
- Omit what this problem statement does not need; add what it does.
- Must be **fully robust**.

---

## D-001 · Standalone folder, not a branch mutation
**Decision.** `VayuChakra/` is a self-contained project inside the AirGrid repo directory.
It imports nothing from AirGrid at runtime; reusable logic is **ported in**, not linked.
**Why.** The user asked for a separate folder and for AirGrid to stay untouched. A hard
copy means AirGrid's files are never edited, so its behaviour cannot regress. It also
makes promotion to its own repo a plain directory move.
**Cost.** Some duplicated code (CPCB AQI tables, IDW, haversine). Accepted deliberately:
duplication across two products with different lifecycles is cheaper than coupling.
**Reverses if.** We decide to ship one product instead of two.

## D-002 · No deployment, no hosting
**Decision.** No Render service, no keep-alive, no public URL. `uvicorn` on localhost only.
**Why.** Explicit user instruction.

## D-003 · CAMS via Open-Meteo, not ECMWF ADS, for v1
**Decision.** Take the coupled-model prior (PM2.5, PM10, O3, NO2, SO2, CO, AOD, dust)
from `air-quality-api.open-meteo.com`, which redistributes CAMS global.
**Why.** Verified working with **no API key** on 2026-09-04: 120 hourly steps,
AOD 0.33–0.76, O3 present as its own variable. ECMWF ADS gives native resolution but
needs registration and a slower async request model. Not worth blocking day one.
**Reverses if.** We need native CAMS resolution or fields Open-Meteo does not relay.

## D-004 · XGBoost native Booster API, no scikit-learn
**Decision.** Train and serve with `xgboost` directly.
**Why.** `sklearn` is not installed in this environment (checked 2026-09-04) and the
existing AirGrid production path already avoids it. Keeps the dependency list short and
the artefacts portable.

## D-005 · Domain is Delhi NCR, wider than AirGrid's
**Decision.** 27.6–29.4 N, 76.0–78.0 E.
**Why.** AirGrid's grid is Delhi only (28.4–28.9, 76.8–77.4). The PS says "Delhi NCR",
and the MoES DSS apportionment resolves 19 NCR districts — Panipat, Karnal, Meerut and
Bharatpur all sit outside AirGrid's box. Stubble plumes also arrive from beyond it.

## D-006 · Two-way coupling as a damped fixed-point iteration
**Decision.** Solve the aerosol feedback by iterating
`PM2.5 -> AOD -> shortwave -> dT -> PBL -> PM2.5` with relaxation factor omega,
rather than fitting one end-to-end model.
**Why.** It is the actual physics, each step is separately checkable against published
Delhi values, and it can be switched off for the ablation. An end-to-end model would
hide the feedback inside weights and make the central claim unverifiable.
**Rails.** dT clipped, PBL suppression clipped, iterations capped, divergence flagged and
surfaced rather than swallowed.

## D-007 · PM2.5 and O3 get separate models
**Decision.** Two heads, not one AQI scalar.
**Why.** The PS names both explicitly. They are governed by different physics — O3 peaks
in the afternoon when PM2.5 is diluted, and rises when NOx falls. A single scalar cannot
represent both, and AirGrid's single-AQI target is the main scientific gap to close.

## D-008 · Two-tier grid, fine over Delhi
**Decision.** 0.025 deg (~2.8 km) inside the Delhi NCT box, 0.1 deg (~11 km) over the
rest of NCR. 1,115 cells total: 420 fine + 695 coarse, no overlap.
**Why.** A uniform 0.1 deg grid put only **8 cells inside Delhi** — indefensible for a
PS that asks for "high-resolution". A uniform 0.025 deg grid over the whole NCR box
would be ~11,000 cells, mostly farmland whose only job is to advect a plume toward the
city. Resolution where the forecast is consumed, coverage where it only needs to
transport.

## D-009 · Exclude the 1000 hPa level over Delhi
**Decision.** The vertical profile uses 950 / 925 / 850 hPa only.
**Why.** Measured 2026-09-04: Delhi ground is ~225 m ASL and the 1000 hPa surface sits
at ~41 m ASL — **184 m below the terrain**. Open-Meteo still reports a temperature
there, by downward extrapolation, and it reads several degrees warmer than the 2 m
observation at night. Using it would have manufactured inversions that do not exist.
Every level is now checked for height-above-ground before use.

## D-010 · Wind requested in m/s
**Decision.** `wind_speed_unit=ms` on every Open-Meteo call.
**Why.** The default is km/h. Ventilation coefficient is m² s⁻¹ by definition; the
default would have inflated it 3.6x and silently moved every dispersion threshold.

## D-011 · Stagnation measured on two timescales
**Decision.** Keep the hourly flag, but define an *episode* on the rolling 24-hour
**maximum** ventilation coefficient, not the mean.
**Why.** Measured: the hourly flag fires on 88% of hours, because the boundary layer
collapses every night everywhere — no discriminating power, and "consecutive stagnant
hours" became a run of ordinary nights (88 h). The published VC thresholds are defined
on *afternoon* ventilation. Testing the 24 h maximum asks the physically meaningful
question: did the day ever clear out? A 24h-mean test flagged 96% of hours; the
maximum test gives 68% in a poorly-ventilated September cell, and will separate
properly in winter.
**Note.** Thresholds are for **display and labelling only**. The ML models consume the
continuous `ventilation_coeff`, `vc_24h_mean`, `vc_24h_max` — never the flags — so a
threshold choice cannot bias a prediction.

## D-012 · CAMS archive does not cover the DSS window — validate twice
**Measured 2026-09-04.** CAMS via Open-Meteo begins ~**mid-August 2022**. Requests for
Oct 2021 – Feb 2022 return a correct time axis with **all values null**. The MoES DSS
workbook covers exactly Oct 2021 – Feb 2022, so the chemistry prior is unavailable for
the one window we most want to compare against.
**Decision.** Two complementary validations rather than one compromised one.
 1. **DSS window (Oct 2021 – Feb 2022)** — run VayuChakra in a reduced configuration
    (meteorology + lags + persistence, **no chemistry prior**) and compare against the
    DSS `Model forecast` sheet. Like-for-like on information available at forecast time.
 2. **Production configuration** — validate the full model (with CAMS) on a recent
    winter where CAMS, ERA5 and station observations all exist, scored against CPCB.
**Reported honestly.** We say which configuration produced which number, always.
**Upgrade path.** ECMWF ADS serves the CAMS **EAC4 reanalysis back to 2003**. Getting
that key would let validation 1 include a chemistry prior. Flagged as the highest-value
optional registration.

## D-013 · Infinite mixing depth bug
**Found by** an SVD convergence failure in the AOD fit, not by inspection.
`np.fmin(NaN, inf)` is `inf`, so any hour with a missing PBL produced an **infinite**
mixing depth, which propagated into the ventilation coefficient and poisoned every
downstream regression.
**Fix.** Infinities are turned back into NaN (infinity is not a depth, it is a missing
value wearing a disguise) and the depth is clipped to `[30 m, 5000 m]`.
**Lesson kept.** A numerical failure in a fit is worth tracing to its data source
rather than working around with a filter.

## D-014 · Dual-path inversion: profile where possible, surface proxy otherwise
**Measured 2026-09-04.** The Open-Meteo **forecast** API serves pressure levels; the
**ERA5 archive never does** — `temperature_925hPa` returned 0/24 non-null on every
archive date tested from 2021 to 2026, while `boundary_layer_height` returned 24/24.
`soil_temperature_0cm` (skin) is unavailable; `soil_temperature_0_to_7cm` exists but is
a damped layer average running warm at night and cool at midday — the opposite phase to
a skin temperature, so it is **not** an inversion proxy and is kept only as a predictor.
**Decision.** `indices.inversion()` dispatches on what the data contains and stamps
`inversion_method` = `profile` | `surface` on every row.
 - **profile** — true inversion strength in K, lid height from the temperature profile.
 - **surface** — `inversion_strength_k` left **NaN, never zero**. A collapsed boundary
   layer (< 250 m) while the sun is down is the surface signature of a radiative
   inversion, and the PBL height is then the lid.
**Why NaN and not zero.** A model trained where the feature is absent must not use it,
and NaN enforces that. Zero would quietly teach it that no hindcast hour had an
inversion — a fabricated fact, and exactly the kind of silent corruption that is
impossible to find later.
**Verified.** Forecast and archive frames have **identical schemas**, so they
concatenate cleanly. Nov 2021 Delhi from the archive path reproduces the expected
diurnal cycle: PBL 26 m at midnight rising to 1074 m at 15:00 IST, inversion 100% of
night hours and 0% at midday, VC 72 → 4540.

## D-015 · Absolute AOD is not predictable from surface PM2.5 — use elasticity instead
**Measured** on 26,496 hours of paired CAMS output across six NCR points, 2024:
| model for log(AOD) | r² |
|---|---|
| log PM2.5 alone | 0.095 |
| log column mass (PM2.5 × mixing depth) | 0.050 |
| log column + relative humidity | **0.356** |
| + hygroscopic growth term | 0.358 |
| + log dust | 0.383 |
**Reading.** Humidity dominates — aerosol swells as it takes up water, so the same mass
has very different optical depth at 30% and 90% RH. Even so, r² = 0.38 is too weak to
*predict* AOD, because AOD is a column quantity that also sees aerosol above the
boundary layer which surface PM2.5 cannot know about.
**Decision.** Do not predict absolute AOD. Take **CAMS's own AOD as the baseline** — it
comes from an actual radiative-transfer model — and use the fitted **elasticity**
∂ln(AOD)/∂ln(PM2.5) only to *perturb* it when our predicted PM2.5 differs from CAMS's:
`AOD = AOD_cams × (PM_ours / PM_cams) ** b`.
**Why this is better.** The feedback loop never needed absolute AOD; it needed the
*sensitivity* of AOD to a change in PM2.5. Estimating only that quantity uses the data
where it is strong and avoids leaning on it where it is weak.

## D-016 · The coupling reference must be a PRISTINE atmosphere, not CAMS
**The bug this fixes was conceptual, not mechanical.** The first solver expressed the
feedback as a perturbation *relative to CAMS's own state*. It converged in one
iteration with **exactly zero effect** — correctly, because when our PM2.5 equals
CAMS's PM2.5 there is no perturbation to respond to. It answered "how does the feedback
differ from CAMS's feedback?" when the question is "what IS the feedback?"

**Decision.** Three distinct optical states, never conflated:
| state | meaning |
|---|---|
| `AOD_BACKGROUND` = 0.10 | pristine atmosphere — the ablation's control |
| `aod_climatology` | what the weather model already assumed, per cell per month |
| `aod_actual` | the real load, iterated because PM2.5 depends on it |

The driving shortwave is **not** clear-sky — Open-Meteo's radiation scheme has already
dimmed it with a climatological aerosol. So the climatological loss is divided out to
recover clear-sky irradiance before any load is applied. Skipping that step would count
the climatological aerosol twice.

**Second bug found by the same fix.** `pbl_response` clipped its ratio at 1.0, which
silently forbade the pristine control from ever having a DEEPER boundary layer than the
baseline — zeroing out the effect being measured. Now bounded both ways.

**Result — measured, Nov–Dec 2024, Delhi, 5,856 hours, all four gates PASS:**
| quantity | all hours | daytime | published Delhi range |
|---|---|---|---|
| shortwave reduction | 10.3% | 11.1% | 5–35% |
| near-surface cooling | — | **−0.59 K** | 0.1–2.5 K |
| PBL suppression | 5.1% | 5.7% | 5–35% |
| PM2.5 amplification | 2.5% | **6.1%** | 2–30% |

Converged in **6 iterations**, 0 diverged rows, max residual 0.38 µg/m³.
Fitted AOD elasticity b = 0.702 (r² = 0.463, n = 5,856).

**Why the values sit at the low end.** CAMS is known to underestimate Delhi aerosol, and
the all-hours means include nights when the radiative feedback is correctly zero. The
daytime figures are the representative ones and are quoted as such.

## D-017 · Radiative diagnostics are daylight-only
**Decision.** `sw_reduction_frac` and `pbl_suppression_frac` are NaN when the pristine
shortwave is below 1 W/m².
**Why.** A "percentage reduction of zero shortwave" is not a number. Filling it with 0
would drag every reported mean toward zero in proportion to the length of the night —
an artefact of the season, not a property of the aerosol.

## D-018 · CORRECTION — the DSS validation window IS coverable by observations
**This reverses an earlier conclusion of mine, which was wrong.**

I first sampled OpenAQ S3 coverage using station IDs 235 (Anand Vihar), 17 (R K Puram)
and 50 (Punjabi Bagh), found years 2015-2018 and 2025-2026 on all three, and concluded
the archive had a systemic **2019-2024 gap** that made the DSS window unscoreable.

Those are **legacy duplicate location IDs**. The live records for the same physical
sites are 5509, 7044 and 6357. Scanning all 161 NCR stations rather than three:

| coverage | stations |
|---|---|
| 2021 in archive | **89** |
| 2022 in archive | **91** |
| both 2021 and 2022 | **88** |
| both, within 60 km of Delhi | **66** |

The DSS window (Oct 2021 - Feb 2022) is covered by 66 Delhi-area stations, including
**IITM sites** (Lodhi Road 11607, Chandni Chowk 11603) — the same institute that
built the DSS — plus IMD and CPCB.

**Consequence — the validation gets stronger than planned.** We can now score
VayuChakra *and* the MoES DSS against the **same observations** over the **same
window**: a genuine head-to-head, not a structural comparison.

**Verified end to end.** Pulled 10 Delhi stations for 1-14 Nov 2021: 3,178 hours,
PM2.5 97% complete. City-mean by day reproduces the documented episode —
111-150 µg/m³ on 1-3 Nov, **414 on 4 Nov (Diwali 2021)**, decaying 358 → 331, then the
mid-month stubble-and-stagnation peak at 306-343. The data is real and correctly
timestamped.

**What still stands from D-012.** CAMS remains unavailable before mid-Aug 2022, so the
DSS-window run is still a reduced configuration (no chemistry prior). That limitation
is real; the observations limitation was not.

**Lesson kept.** Three samples is not a survey. The systemic-sounding conclusion came
from a biased sample of exactly the stations that happened to be stale.

## D-019 · Plume model: Lagrangian puffs, not an upwind fire count
**Decision.** Each fire detection becomes a discrete parcel, advected hour by hour on
the forecast wind, spreading as it travels, contributing to a cell only when it
actually arrives.
**Why not the upwind-count approach** (what AirGrid does): it has no notion of time.
Smoke from a fire 250 km away arrives six to fifteen hours later, through a wind field
that turned and a boundary layer that collapsed at dusk. Traced a real puff: it moved
256 km → 119 km toward Delhi in 24 h at 1-3 m/s, mass decaying 210 → 72 kg. An
upwind count would have credited Delhi with that smoke at hour zero.

**Emission factors are citable, not invented.** GFAS dry-matter conversion
0.368 kg/MJ (Kaiser et al., 2012) × 6.26 g PM2.5 per kg cereal straw = **2.30 g/s per
MW** of fire radiative power.

**Dispersion combines two regimes in quadrature.** Pasquill-Gifford was fitted below
10 km and badly under-predicts a 200 km transport, so near-field turbulence is combined
with a far-field shear term proportional to distance travelled. Gives σ ≈ 1.1 km at
1 h, 12 km at 6 h, 30 km at 15 h — the right order for a regional smoke plume.

**Verified magnitudes.** A modelled burn night (3,000 fires × 165 kg/h over 6 h,
σ = 40 km) gives **490 µg/m³ under a 300 m layer, 196 µg/m³ under 1500 m** — correct
order for a severe episode, and correctly inverse in mixing depth.

**The inversion gate works in both directions** (this is the PS requirement):
| puff height | 400 m lid | contribution |
|---|---|---|
| 200 m | below | 1.31 µg/m³ — trapped |
| 450 m | above | 0.98 µg/m³ — decoupling |
| 700 m | above | **0.00** — decoupled |
Smoke can sit overhead while monitors read clean, then land abruptly when morning
convection reconnects it. That is real, observed Delhi behaviour and it falls out of
the model rather than being scripted.

## D-020 · Two bugs found by testing magnitudes rather than eyeballing output
**Broadcasting bug, and it was physical.** `_contribution` used one wind dict for both
the puff population and the receptor cells. Whether smoke is coupled to the ground is
set by the lid **where the puff is**; the volume it dilutes into is set by the mixing
depth **at the receptor**. Conflating them raised a shape error here — but had the
array lengths happened to match, it would have silently returned wrong numbers.

**Unit bug.** Puff mass is in grams and volume in m³, so the Gaussian quotient is
**g/m³**, while everything else in the project is µg/m³. The missing factor of 10⁶ made
a genuine 0.66 µg/m³ print as `0.00`. It was invisible until magnitudes were checked
against a physical expectation instead of being read as "looks like zero, probably
off-season".
**Lesson kept.** "It returned zero" is not evidence of correct off-season behaviour
until a case that *should* be non-zero has been shown to be non-zero.

## D-021 · CPCB index computed from concentrations, never predicted directly
**Decision.** Models predict PM2.5, O3, PM10 and NO2 concentrations; `aqi.py` applies
the published breakpoint table afterwards.
**Why.** AQI is a max-of-sub-indices over piecewise-linear breakpoints — discontinuous
and non-monotone in any single pollutant. Asking a regressor to learn that lookup table
*on top of* atmospheric physics wastes capacity on arithmetic we can do exactly. It is
also **auditable**: anyone can check our breakpoints against CPCB's published table;
nobody can check a number that emerged from a tree ensemble.
**PM10 and NO2 are carried purely for index validity** — CPCB requires ≥3 pollutants
including a particulate, and with only PM2.5 and O3 every AQI correctly came back NaN.
**Verified** against the published table at every breakpoint, plus the two traps:
 - **Shared endpoints.** Bands abut (0-30, then 30-60), so a value landing exactly on
   one matches both. The FIRST match must win — CPCB puts PM2.5 = 30 at index 50, not
   51. Filling only where unset fixed an off-by-one at every single breakpoint.
 - **Averaging windows.** A 400 µg/m³ hourly spike gives a naive AQI of 500 but a
   correct CPCB AQI of 218, because the standard is defined on a 24-hour mean.

## D-022 · Three bugs in the assembled pipeline, all found by checking outputs
1. **AQI grouped by cell alone** while the forecast frame stacks three horizons per
   cell. Every rolling mean averaged *across* horizons, so the 24 h AQI was a blend of
   the 24/48/72 h predictions. `horizon_h` is now added to the grouping key
   automatically, because forgetting to pass it is silent.
2. **NaN PM2.5 coerced to zero** by a `fillna(0)` before adding the plume term. That
   converts "we cannot predict this hour" into "the air is perfectly clean" — the most
   dangerous direction to be wrong in, and entirely plausible-looking on a map. NaN is
   now preserved end to end.
3. **Fallback picked a column, not a value.** `_persistence_fallback` returned the
   first column with *any* data; `pm25_lag_1h` exists but is populated only in the
   past, so the forecast came out **2% populated** while the CAMS prior sat unused.
   Now coalesced row by row: 2% → **93%**.

## D-023 · The literature gate is evaluated in the regime the literature describes
**Problem.** `pbl_suppression_pct` failed at 4.69% against a 5-35% bound — while the
model was behaving correctly. The published Delhi figures come from **winter haze
episodes at high aerosol loading, in daylight**. Our average included clean September
afternoons and nights, when the radiative feedback is correctly *zero*.
**Decision.** Gate on high-aerosol daylight hours (AOD ≥ 0.5, shortwave ≥ 50 W/m²) and
report the all-conditions figure alongside, clearly labelled, rather than judging it.
**Result — all four now pass, and the distinction is itself informative:**
| quantity | in-regime | all conditions | published |
|---|---|---|---|
| shortwave reduction | **11.4%** | 9.8% | 5-35% |
| daytime cooling | **−0.58 K** | −0.50 K | 0.1-2.5 K |
| PBL suppression | **5.9%** | 4.7% | 5-35% |
| PM2.5 amplification | **6.1%** | 2.8% | 2-30% |
**Why this is not moving the goalposts.** Comparing a season-wide average against a
winter-episode measurement compares two different quantities. Both numbers are
reported; only the like-for-like one is judged. Returns `ok: None` rather than a pass
when fewer than 20 in-regime hours exist.

## D-024 · One request per location, not per sensor
**Measured.** `fetch_latest` issued one request per sensor — roughly 800 for the NCR
network — and earned HTTP 429 partway through, leaving a partial picture that reads
like a quiet day rather than a throttled one. `/locations/{id}/latest` returns every
sensor at a location in one response: ~130 requests, no throttling, 93 stations
returned.
**The dangerous part was not the failure, it was its shape.** A rate-limited pull does
not look like an error downstream; it looks like clean air.

## D-025 · VayuChakra gets its own design system, not AirGrid's
**Decision.** `VayuChakra/DESIGN.md` documents a separate system: atmospheric indigo
chrome, its own seven-step type ramp, a validated three-colour chart series palette.
**Why.** They are siblings, not the same product. AirGrid speaks to Delhi residents on a
phone (a public-health bulletin, warm). VayuChakra speaks to a forecaster at NCMRWF and
to a jury: an instrument, denser and more numeric, whose job is to let a reviewer judge
whether the physics underneath is sound. A dense instrument has more distinct text roles
than a chat interface, so forcing it onto the citizen app's ramp would be wrong.
**Inherited unchanged:** the CPCB AQI band scale. That is a public standard, not a brand
asset, and it is reproduced exactly in both products.
**Scene sentence that forced the choices** (light, dense, tabular): *a reviewer at a desk
indoors under office light, reading a 72-hour outlook and deciding whether to trust it —
or the same screen projected in a lit jury room.*

## D-026 · Palettes are validated, not eyeballed
**CPCB AQI bands, measured:** CVD separation **passes** (worst adjacent ΔE 8.2, protan),
normal-vision floor passes (16.7). But Satisfactory, Moderate and Poor all fall **below
3:1** against a light surface. That result is not dismissable, and it sets two hard rules
that are now enforced everywhere:
 1. every band-coloured element carries its band **name and number** as visible text;
 2. every map cell carries a **hairline border**, so a pale yellow cell is still a cell.
Text on bands: dark ink on the four light bands, white on the two dark ones. White on
Good is only 3.65:1 — large-text-only — so ink is used there too.
**Chart series:** `#3b62d4 → #c2701c → #0f9b8e`. Two earlier candidates failed (indigo
too dark at L 0.35 and below the chroma floor; teal↔purple at CVD ΔE 7.2). The shipped
set passes all five checks with margin (CVD ΔE 14.0 protan, normal-vision ΔE 21.7).
**Contrast, measured:** white on chrome 12.54:1, ink on surface 16.52:1, muted ink 6.83:1.

## D-027 · Never a dual axis — three panels instead
The inversion tracker shows strength (K), mixing depth (m) and ventilation coefficient
(m²·s⁻¹). One pair of axes would need two or three y-scales, which lets whoever draws the
chart choose the story by choosing the scaling. Three panels sharing one x-axis compare
honestly, and the dashboard says so on the page rather than only in a commit message.

## D-028 · Four bugs found by rendering the dashboard and looking at it
The validator checks colour, not layout. Screenshotting each view found four defects
that no amount of code review had surfaced:

1. **`isFinite(null)` is `true`.** The global `isFinite` coerces, and `Number(null)` is
   0 — so every missing hour was plotted as **zero**, drawing a cliff to the floor at the
   end of every forecast, exactly where CAMS stops supplying a prior. *The data was
   honest; the chart was lying.* Now `Number.isFinite` throughout, which does not coerce.
2. **The forecast endpoint returned `tail(1)`** — the last row of a frame that runs five
   days forward — landing precisely on those same sparse hours. Every one of 420 cells
   came back with a null AQI and the map rendered entirely grey. It now selects the row
   **valid at issue time + horizon**, which is the question the control is asking.
3. **`reduce` on an empty array throws.** When no cell had a usable index, the summary
   panel died mid-render and sat on its loading skeleton forever, looking like a slow
   network rather than a crash.
4. **A 640-wide viewBox in a 370 px panel** scaled 10 px axis text down to about 6 px.
   The viewBox now tracks the container's real width, so 10 px means 10 px.

**Lesson kept.** Three of these four produced output that looked plausible: a flat map, a
clean-looking zero, a loading state. None raised an error. Rendering the thing and
looking at it is a distinct test from running the code.

## D-029 · Outstanding: 28 detector findings are false positives
`detect.mjs` resolves DESIGN.md from the repository root, so it checks VayuChakra against
**AirGrid's** design system and reports every VayuChakra token as drift (17 font sizes,
6 colours, 5 radii). All are documented in `VayuChakra/DESIGN.md`.
**Not suppressed.** Silencing them needs the user's explicit confirmation, and the honest
record is more useful than a clean report. The em-dash finding in the same run was real
and was fixed.

## D-030 · First end-to-end training result (smoke panel)
5 stations, Jan–Apr 2026, 13,658 rows. Small and out of season, but it proves the path.

| head | RMSE | persistence | vs persistence | verdict |
|---|---|---|---|---|
| pm25 +24 h | **36.28** | 45.91 | **+20.97%** | beats persistence |
| o3 +24 h | 31.91 | 27.36 | −16.63% | **loses to persistence** |

**PM2.5 at 24 h is the headline.** AirGrid's equivalent head *lost* to persistence by
4.2%; this beats it by 21%. The most likely cause is exactly the missing physics that
motivated the project, and the feature importances support that reading:

| rank | feature | what it is |
|---|---|---|
| 1 | `pm25_lag_1h` | persistence, as expected |
| 2 | `pm25_roll_72h` | three-day trend |
| **3** | `target_cams_pm25` | **the CAMS coupled-model prior** |
| **4** | `target_is_episode` | **our stagnation index** |
| 6–7 | `vc_24h_mean`, `ventilation_coeff` | **our ventilation indices** |

Three of the top seven are indices this project derived, and the coupled-model prior is
third. The physics is doing work rather than decorating.

**The ozone head fails and is reported as failing.** Four months of Jan–Apr with O3 only
54% populated is close to the worst possible window for it: ozone is photochemical and
peaks in summer, so the training set contains almost none of the behaviour being asked
for. To be retrained on the full 19-month panel and re-reported either way.

## D-031 · Coverage threshold scales with the requested window
A fixed `min_months = 8` made a 4-month request unsatisfiable, so the builder rejected
every station and printed "nothing to do" for what was a misconfigured threshold rather
than absent data. Now `max(2, 60% of the window)`.

## D-032 · Full training run — all 12 heads beat persistence
Panel: 536,670 rows, 40 stations, Feb 2025 – Aug 2026. Chronological hold-out.

| head | RMSE | persistence | vs persistence | r² |
|---|---|---|---|---|
| pm25 +24 / +48 / +72 h | 26.22 / 26.69 / 26.47 | 31.96 / 34.01 / 35.36 | **+18.0 / +21.5 / +25.1%** | 0.19 / 0.16 / 0.17 |
| o3 +24 / +48 / +72 h | 17.58 / 18.55 / 19.01 | 22.01 / 23.18 / 23.42 | **+20.1 / +20.0 / +18.8%** | 0.61 / 0.56 / 0.54 |
| pm10 +24 / +48 / +72 h | 90.90 / 97.02 / 89.69 | 99.27 / 108.66 / 115.28 | +8.4 / +10.7 / +22.2% | 0.21 / 0.10 / 0.23 |
| no2 +24 / +48 / +72 h | 16.09 / 16.62 / 17.18 | 20.55 / 21.91 / 22.79 | +21.7 / +24.1 / +24.6% | 0.54 / 0.51 / 0.48 |

**Acceptance criterion V1 met.** AirGrid's 24 h head lost to persistence by 4.2%; every
head here beats it, and the margin *widens* with lead time, which is the expected shape
— persistence degrades faster than a physics-informed model as the horizon grows.

**The ozone head is the clearest vindication of a diagnosis.** On the 4-month smoke
panel it *lost* by 16.6%, and the stated reason was that Jan–Apr contains almost no
photochemistry and O3 was only 54% populated. On the full 19-month panel, with O3 at
83.2%, it beats persistence by 20% at r² = 0.61 — the best-fitting head in the set.
The earlier failure was the training window, not the model.

**Memory fix that made this possible.** `make_supervised` on 537k rows × 130 columns
built a ~250-column float64 frame and pandas copied it several times, exceeding memory
and killing the first run after the 43-minute build. Now it carries only feature-eligible
columns, drops unlabelled rows before assembling, and stores float32 — 466 MB, 17 s.
XGBoost casts to float32 internally, so the precision costs nothing.

## D-033 · The plume case study: three physics variants, and why I stopped
Replay of 5–8 Nov 2021 with archived FIRMS detections (52,453 fires, 476,804 MW),
archived ERA5 meteorology and archived CPCB observations.

| variant | peak plume | corr vs residual | verdict |
|---|---|---|---|
| A · injection height fixed forever | 15.6 µg/m³ | +0.249 | **backwards** — largest contribution in the deep afternoon layer |
| B · entrained, no residual layer | 153.5 µg/m³ | +0.180 | **over-corrected** — implies stubble is ~69% of Delhi PM2.5 |
| C · entrained with residual layer | 9.3 µg/m³ | −0.122 | most defensible physics, weakest correlation |

**Variant A was a real bug.** Comparing a parcel's *injection* height against the current
lid forever meant smoke injected at ~300 m sat "above" a 33 m nocturnal inversion and was
excluded from the surface all night. The model reported its biggest plume contributions
when the mixed layer was deepest — the exact opposite of the trapping mechanism the
problem statement asks about.

**Variant C is what ships.** When the layer collapses at dusk, smoke already spread
through a 1200 m daytime layer does not collapse with it: only `current_depth /
mixed_depth` of it stays coupled to the ground, and the rest is stranded aloft in the
residual layer until morning. That is standard boundary-layer treatment.

**I stopped here deliberately.** Variant B correlates better and looks more impressive.
Choosing it would be selecting physics to fit the demo. The honest position is that the
plume magnitude is uncertain to within an order of magnitude, the timing correlation
against a residual is weak, and **the case study is a limitation of this work rather than
a result of it.** It should be presented that way.

**Two rate-limit fixes came out of the same run.** Open-Meteo's archive limit is
per-minute, so the ordinary ~2 s backoff re-triggered it and burned the retry budget —
five requests failed and the advection silently ran on a wind field with holes in it.
HTTP 429 now honours `Retry-After` and waits out the window; the corridor was also
thinned from 1,115 to 835 cells, since nearest-neighbour wind lookup gains nothing from
2.8 km spacing.

## D-034 · One HTTP 502 destroyed a hindcast, and the error message pointed the wrong way
**What happened.** The coupling ablation reported *"chemistry prior unavailable"*. CAMS
was fine — tested standalone for the same window, 100% populated. The real cause was a
single **HTTP 502** on the meteorology request, which emptied the panel; the ablation's
error branch then attributed an empty panel to the chemistry prior.

**Three separate faults, all worth fixing:**
1. **Gateway errors got the short backoff.** 502/503/504 were retried on the same ~2 s
   schedule as a flaky socket. A server that is briefly overloaded needs to be given
   time, not asked again immediately. They now use the same long, `Retry-After`-aware
   wait as 429.
2. **A failed batch lost every cell in it.** Open-Meteo takes up to 100 points per
   request, so a 20-station hindcast is a *single* request — one failure and the entire
   run has no meteorology. Failed batches now split in half and retry, up to three
   levels, which isolates a bad cell or an oversized request instead of surrendering
   everything.
3. **The diagnosis was misdirected.** "Empty panel" and "no chemistry prior" are
   different failures and shared one message, sending debugging in the wrong direction
   for the first several minutes. They are now reported separately.

**Lesson kept.** An error message that names the wrong cause is worse than a generic
one: a vague message makes you look, a confident wrong one makes you look elsewhere.

## D-035 · DSS head-to-head — and the caveat that matters more than the table
A silent join bug hid this result entirely at first. The DSS sheet stores integer IST
hours; IST is UTC+5:30, so every converted timestamp landed at **:30 past the hour**
while every observation series is floored to :00. The merge matched **zero rows** and
printed an empty table rather than raising. Floored to the hour, matching observations.

**Result** — identical hours, identical ground truth (Delhi city-mean CPCB PM2.5):

| lead | hours | DSS RMSE | VayuChakra | persistence |
|---|---|---|---|---|
| +24 h | 2,363 | 98.78 | **81.28** | 93.98 |
| +48 h | 2,363 | 108.34 | **91.77** | 108.78 |
| +72 h | 2,363 | 118.95 | **101.22** | 115.00 |

Our models were trained on Feb 2025 – Aug 2026, so this window is genuinely out of
sample in time.

**The caveat is not a footnote, it is the headline.** The DSS forecasts were issued
**operationally**: it had to predict the weather as well as the chemistry, days ahead.
Our hindcast is driven by **ERA5 reanalysis** — the meteorology as it actually turned
out. That is a material advantage and makes this **not a fair comparison of forecast
skill**. The table supports "the statistical layer maps meteorology to PM2.5
competitively". It does **not** support "we forecast better than the MoES DSS", and that
sentence must never be said. The caveat now prints above the numbers, not below them.

## D-036 · The coupling ablation is a NEGATIVE result, reported as one
**First run was an unfair test, and I fixed the test before believing the answer.** The
uncoupled arm is CAMS plus a fitted bias, so its mean error is zero *by construction*;
the coupled arm is that series multiplied by ~1.075 and therefore *must* come out biased
high — it did, by +4.21 µg/m³. That comparison measures which arm was allowed to fit an
intercept, not whether the feedback helps. Both arms are now re-centred to zero mean
bias before scoring, in the overall and per-regime numbers alike.

**Result, Nov 2025 – Feb 2026, 48,181 hours:**

| regime | n | uncoupled RMSE | coupled RMSE | change |
|---|---|---|---|---|
| overall | 48,181 | 82.76 | 82.85 | **−0.11%** |
| stagnant episode | 40,047 | 83.95 | 84.01 | −0.07% |
| well ventilated | 8,134 | 76.61 | 76.77 | −0.21% |
| **high aerosol** | 28,440 | 83.29 | 83.00 | **+0.35%** |

**The honest reading.** The feedback's *magnitudes* are right — all four literature
checks pass (SW 13.5%, cooling −0.74 K, PBL 7.0%, PM 7.5%). But switching it on does
**not** measurably improve PM2.5 against observations. It helps only in the high-aerosol
regime, and by 0.35%, which is not a result to lean on.

**Three candidate explanations, none of them "the physics is wrong":**
1. The uncoupled baseline is weak (RMSE 82.76). A ~7% modulation is small against that
   much residual error — an unfavourable signal-to-noise ratio.
2. The ablation's baseline is CAMS-plus-bias, not the trained model.
3. **Most likely and most interesting:** the trained model already receives mixing
   depth, ventilation coefficient, shortwave and the stagnation indices, so it may be
   learning the feedback's *effect* implicitly. Adding it explicitly on top would then
   be double-counting rather than new information.

**What this means for the pitch.** The problem statement asserts that ignoring the
feedback "leads to significant inaccuracies". We tested that assertion rather than
repeating it, and on this window, with this baseline, we could not confirm it. Saying so
is worth more than a claim we cannot support — and explanation 3, if true, is a finding
in its own right: the physics matters, but it may enter through the features rather than
through an explicit solver.

## D-037 · The map was showing XGBoost leaf quantisation, not pollution
**Found by rendering the map and thinking the pattern looked wrong.** With the trained
models in place the Delhi grid rendered as salt-and-pepper noise. Measured rather than
assumed:

| | before | after |
|---|---|---|
| neighbour correlation (E–W) | **0.50** | 0.979 |
| neighbour correlation (N–S) | 0.51 | 0.983 |
| AQI standard deviation | 4.32 | 2.37 |

A real atmospheric field at 2.8 km spacing should exceed 0.9. The values were nearly
**bimodal**, clustering at ~108.8 and ~117.3.

**Cause.** Gradient-boosted trees are piecewise constant. PM2.5 varies by only
2.46 µg/m³ (standard deviation) across all 420 Delhi cells, so neighbouring cells land
on either side of a split threshold and flip between two leaf values. The map was
displaying an artefact of the estimator as though it were a pollution gradient.

**Fix.** Gaussian smoothing at 6 km, the effective resolution of the inputs — the
meteorology is ~11 km, the CAMS prior ~40 km, the station network ~5 km. Applied before
the plume and the coupling, since the plume carries genuine sharp gradients that must
not be blurred.

**This removes structure the model cannot justify; it does not invent structure.** A
2.8 km display grid fed by 11–40 km inputs was over-claiming resolution, and smoothing
states the honest claim: the forecast resolves what its drivers resolve, and no finer.

## D-038 · A second map scale, because the CPCB one can go blind
The September forecast spans AQI 104–121 — entirely inside "Moderate" — so the standard
palette painted 420 identical yellow squares and hid a real 17-point spread. The band
scale is correct and must stay the default, but it stops being informative when a whole
city sits in one band.

**Decision.** A *Relative* mode: one hue, light to dark, re-scaled across the values
actually present. Never the default; the CPCB legend dims to 35% while it is active and
the header reads "Relative scale, AQI 104–121 · not CPCB colours", so a reader can never
mistake which scale they are looking at. Deep-linkable via `?map=relative`.

## D-039 · Photolysis physics implemented from first principles, nothing fitted
Round 2 opened with a literature-backed diagnosis of Round 1's flat coupling ablation:
there are **two** aerosol pathways and we had built the weaker one, on the less
responsive pollutant.

| pathway | mechanism | effect on ozone |
|---|---|---|
| **API** — aerosol→photolysis | aerosol blocks UV, ozone production slows | **−8.5 to −11.4 ppb (10–12%)** |
| **ARF** — aerosol→radiation→PBL | what we built in Round 1 | −0.9 to −2.9 ppb (1–3%) |

*(Xing et al., ACP 22, 4101, 2022 — paired WRF-Chem runs isolating each.)*

**Implementation.** `vayuchakra/photolysis.py`: MCM v3.3.1 clear-sky rates
`J = l·cos(SZA)^m·exp(−n·sec(SZA))` with published coefficients, aerosol optical depth
shifted from CAMS's 550 nm to the photolysis-relevant 380 nm via an Ångström exponent
(×1.56), then attenuated by Beer-Lambert **scaled by the share of extinction that
actually removes a photon from the actinic flux**. That last bracket matters: photolysis
responds to photons arriving from every direction, so light scattered by aerosol still
counts. Applying raw Beer-Lambert to J would have overstated the effect several-fold —
the same trap avoided in `feedback.py`.

**Verified against known magnitudes:** J(NO₂) = 0.0089 s⁻¹ overhead (literature ~1e-2),
J(O¹D) = 3.78e-5 s⁻¹ (literature ~3e-5), both correctly zero below the horizon.

**Nothing is fitted.** With k = 1.0 the physics produces a **21.0%** mean reduction in
J(NO₂) at present-day Delhi aerosol — inside the 20–30% the literature spans, with no
tuning at all. That is a stronger position than a fitted coefficient.

## D-040 · The seasonal calibration target was Beijing's, and Delhi is the opposite
The first version fitted `k` so the seasonal means reproduced the published **24% summer
/ 30% winter** split. It could not converge on the right *order*, and the reason is a
real finding rather than a numerical problem.

**Measured on our own panel: CAMS AOD averages 0.834 in April–June against 0.487 in
November–February.** Delhi's optically thickest season is the pre-monsoon **dust**
season, not the winter **smoke** season. Beijing is the other way round. Fitting a
coefficient to reproduce Beijing's seasonal ordering would have forced another city's
climatology onto Delhi's physics.

**Decision.** Fit nothing; treat 20–30% as a reference range to report against, not a
target to hit. The seasonal ordering our model produces (summer 22.0%, winter 19.8%) now
follows Delhi's actual aerosol seasonality.

## D-041 · Both planned independent validators failed, and the reason is worth recording
The plan's headline check (V1) was to compare modelled `J/J_clear` against Open-Meteo's
`uv_index / uv_index_clear_sky`, which looked like a measured actinic attenuation. It is
not, and neither is any other Open-Meteo radiation product. Three measurements:

1. **`uv_index_clear_sky` means cloud-free, not aerosol-free.** At cloud cover below 5%
   the ratio is **0.998** — no attenuation — while mean AOD over those same hours is 0.41.
   Aerosol sits in both the numerator and the denominator.
2. **The ratio tracks cloud, not aerosol:** 0.998 → 0.963 → 0.925 → 0.903 → 0.841 across
   rising cloud bands, while within clear skies a threefold rise in AOD moves it only
   from 0.998 to 0.955.
3. **Broadband shortwave has the same problem.** At fixed sun angle (zenith 35–45°) in
   clear skies it reads **750, 761, 762 W/m²** across AOD bands 0–0.4, 0.4–0.7, 0.7–1.5.
   Flat. The radiation scheme carries a *climatological* aerosol, not the day's load.

**Consequence.** No Open-Meteo radiation product can validate aerosol optics — there is
no daily aerosol signal in any of them. The check was replaced, not dropped: validation
moved to the **ozone response against station observations**, which tests the mechanism
against measurements rather than against an intermediate.

**Silver lining.** Finding (3) independently *confirms* the assumption `feedback.py` was
built on (D-016): the driving shortwave contains a climatological aerosol that must be
divided out before a real load is applied.

## D-042 · Photolysis features do not improve the ozone forecast — a second negative result
Identical panel, identical splits, with and without the photolysis block:

| head | with J | without J | change |
|---|---|---|---|
| o3 +24 h | 17.61 | 17.58 | −0.17% |
| o3 +48 h | 18.48 | 18.55 | **+0.38%** |
| o3 +72 h | 19.05 | 19.01 | −0.21% |

A wash. This is the **second** time an explicit physics term has failed to improve
prediction, and it reinforces the D-036 explanation rather than contradicting it: the
model already receives shortwave, UV, AOD, hour and month, from which it can form the
photolysis relationship implicitly. Computing J explicitly is, for *prediction*,
redundant.

**But prediction is not the only thing physics buys.** A statistical model interpolates
conditions it has seen; it cannot answer *"what would ozone be if Delhi's aerosol
halved?"*, because that atmosphere is not in the training data. A mechanism can. That
counterfactual is the subject of the next entry, and it is the correct test of this work.

## D-043 · The chronological split contained no winter, and it was hiding the result
**Found by asking why a regime came back NaN.** The season-resolved sensitivity reported
`winter_daytime: nan`. The cause was not a bug in the mask:

> On a panel running Feb 2025 – Aug 2026, the last 20% by time is **May–August 2026**.
> Winter rows in the test set: **zero**.

**Consequences, both serious:**
1. **Every metric reported before this point is a summer/monsoon score.** All twelve
   heads, the persistence comparisons, the r² values — none of them had ever been
   evaluated on Delhi's defining pollution season.
2. **The photolysis effect was being tested in the one season where it is weakest.** The
   literature's claim is specifically that Delhi's ozone production is *radiation-limited
   in winter*. Measuring it on a summer-only hold-out was close to the worst possible
   test of the hypothesis.

**Fix.** `dataset.split_holdout_window()` and `model.train_head(holdout=...)`: hold out a
named season block instead of the most recent slice. Still strictly out of sample — the
window is absent from training entirely — but it chooses the window by season rather than
by recency.

**Both splits are now reported**, because they answer different questions: recency asks
"does it work next month", season-block asks "does it work in winter".

## D-044 · The counterfactual works, and it is what the photolysis module is for
Trained with **Nov 2025 – Feb 2026 held out entirely**, then asked a question no
statistical forecaster can answer: *what would ozone be if Delhi's aerosol were reduced?*

| AOD reduction | modelled ozone change (winter daytime) |
|---|---|
| −25% | **+6.23%** |
| −50% | **+12.79%** |
| −75% | **+24.29%** |

**Published Delhi figure: a 50% AOD reduction raises ozone by ~25%** (Nelson et al.,
Faraday Discussions 226, 2021, APHH-India). Ours gives **+12.79%** — same sign,
monotonic, accelerating, and within a factor of two of a number the model was **never
fitted to and never saw**.

**The seasonal split is itself corroboration.** The same experiment on the summer
hold-out gives only **+4.03%**; winter gives +12.79%, a threefold stronger response. That
is exactly the pattern the literature explains — winter ozone production in Delhi is
radiation-limited, summer is not. We did not build that seasonality in; it fell out.

**Why the remaining factor of two is expected, not a defect.** The published +25% comes
from a chemical box model with full VOC chemistry, where reduced photolysis also slows OH
production and therefore the whole VOC oxidation chain. We have no VOC measurements and
no chemical mechanism, so we capture the direct photolysis pathway and not the
amplification through radical chemistry. Under-predicting is the expected direction.

**And the winter model is better, not worse:** o3 +24 h scores RMSE 20.08 against
persistence 26.38 (**+23.9%**, r² 0.760) on the unseen winter, versus +20.1% and r² 0.609
on the summer split.

**This is the answer to D-042.** Explicit photolysis adds nothing to *forecast skill* —
the model already infers it from radiation features. What it adds is the ability to run a
**counterfactual**, which a statistical model structurally cannot: that atmosphere is not
in the training data. The problem statement asks for a system that "simulates real-time
interactions", not merely one that predicts. This is that capability, and it is validated
against a published Delhi result.

## D-045 · Winter is a different problem, and our headline number was a summer number
Retrained with **Nov 2025 – Feb 2026 held out entirely**. The contrast with the
recency split is large enough that reporting only one of them would have been misleading.

| head | summer split | **winter hold-out** | |
|---|---|---|---|
| PM2.5 +24 h | +18.0% (RMSE 26.2) | **+4.5%** (RMSE 88.7) | margin nearly gone |
| PM2.5 +48 h | +21.5% | +13.8% | |
| PM2.5 +72 h | +25.1% | +18.8% | |
| O₃ +24 h | +20.1% (r² 0.61) | **+23.9%** (r² 0.76) | *better* in winter |
| O₃ +48 h | +20.0% | +24.0% | |
| O₃ +72 h | +18.8% | **+25.5%** (r² 0.70) | |

**Two findings, opposite in direction:**

1. **PM2.5 in winter is far harder, and we were quoting the easy season.** RMSE rises
   from 26 to 89 µg/m³ and the margin over persistence at 24 h collapses from +18.0% to
   **+4.5%**. Winter Delhi is dominated by episode dynamics — boundary-layer collapse,
   multi-day accumulation, festival and burning spikes — and persistence is a strong
   baseline precisely when concentrations are high and slowly varying. The margin
   recovers at longer leads (+18.8% at 72 h), which is the expected shape: persistence
   decays faster than physics as the horizon grows.
2. **Ozone is the opposite: better in winter than summer**, at every horizon, reaching
   r² 0.76. Consistent with the radiation-limited regime — when ozone production is
   controlled by available sunlight, a model with radiation and photolysis features has
   more to work with.

**Both splits are now reported.** Quoting only the recency split would have advertised a
+18% PM2.5 result that does not hold in the season the problem statement is about.

## D-046 · Two memory-heavy jobs at once killed a training run
The full winter retrain died with `_ArrayMemoryError` after completing PM2.5 and O₃,
because the season-long plume calibration was running concurrently and holding
meteorology for 835 cells. Nothing wrong with either job; running them together was my
scheduling error. PM10 and NO₂ winter numbers still to be filled in.

## D-047 · The plume validation works now, and it overturns a Round 1 decision
**What changed: the target, not the model.** Round 1 correlated the plume against *total*
observed PM2.5 and got r = −0.12 — an uninformative comparison, because transported smoke
is an additive minority term against a signal dominated by local emissions and mixing
depth. Scoring instead against the **MoES DSS daily stubble attribution** (147 days,
season mean 8.6 µg/m³, peak 38.0) turns it into a real test.

**Season-long result** — 6 Oct to 30 Nov 2021, 229,709 archived FIRMS detections, 56 days:

| variant | r | scale | RMSE | peak (scaled) | DSS peak |
|---|---|---|---|---|---|
| **A** — injection height fixed | **+0.596** | 4.79 | 8.28 | 27.7 | 38.0 |
| C — entrained + residual layer | +0.525 | 2.73 | 8.90 | 24.5 | 38.0 |
| B — entrained, no residual | +0.369 | 0.11 | 9.95 | 22.4 | 38.0 |

All three are strongly positive where Round 1's best was negative. The change of
reference is what made validation possible at all.

**Variant A wins, and I had rejected it.** Round 1 shipped C after judging A "backwards"
from a single four-day episode. Over a full season against the operational reference, A
has the best day-to-day timing. **That earlier decision was made on physical reasoning
rather than measurement** — the exact failure this project keeps trying to avoid — and it
is now reversed. Default changed to A.

**A plausible reason A wins.** C carries a running maximum of the mixing depth the parcel
has experienced, which is a memory term. It decouples the contribution from the day's
actual fire load and smears day-to-day variation, which is precisely what a daily
correlation measures.

**The caveat that keeps this honest.** The DSS attribution is **daily**, so it can settle
day-to-day timing and nothing finer. It cannot discriminate the variants on their
*diurnal* behaviour, which is where A is most questionable — A produces its largest
contributions under the deepest afternoon layer, which remains physically odd. C is
retained in the code and is the better choice the moment a sub-daily reference exists.

**Only a scale factor is fitted**, by least squares through the origin, absorbing
emission-factor uncertainty (5-8 g/kg for cereal straw), satellite detection limits and
burn-duration assumptions. Correlation cannot be improved by scaling, so the ranking
above measures physics, not magnitude.

## D-048 · FIRMS fails on response size, not on the documented day limit
The season fetch initially returned **zero detections for every block**. The documented
maximum is 10 days per request; the binding limit is response SIZE. Measured against the
stubble bbox: a 4-day window on 5 Nov 2021 returns 24,004 detections and succeeds, while
7- and 10-day windows on the same dates fail outright. Blocks now start at 4 days and
halve on an empty response, because a genuinely quiet stretch and an over-large request
are indistinguishable from one empty reply. Total recovered: 229,709 detections with the
correct seasonal shape — 51,209 at the 7-10 Nov peak, 1,123 by late November.

## D-049 · Complete winter hold-out: all twelve heads still beat persistence
Nov 2025 – Feb 2026 held out of training entirely.

| head | RMSE | persistence | improvement | r² |
|---|---|---|---|---|
| PM2.5 +24 / +48 / +72 h | 88.66 / 91.14 / 88.97 | 92.80 / 105.74 / 109.62 | **+4.5 / +13.8 / +18.8%** | 0.30 / 0.26 / 0.30 |
| O₃ +24 / +48 / +72 h | 20.08 / 21.56 / 22.49 | 26.38 / 28.38 / 30.19 | **+23.9 / +24.0 / +25.5%** | 0.76 / 0.72 / 0.70 |
| PM10 +24 / +48 / +72 h | 131.13 / 135.29 / 131.59 | 143.81 / 163.38 / 169.53 | +8.8 / +17.2 / +22.4% | 0.31 / 0.27 / 0.31 |
| NO₂ +24 / +48 / +72 h | 24.36 / 26.52 / 27.89 | 27.63 / 31.01 / 32.33 | +11.8 / +14.5 / +13.7% | 0.64 / 0.57 / 0.52 |

**The claim survives the harder test**, which is the point of running it. Every head
beats persistence in the season the problem statement is actually about — but PM2.5 at
24 h beats it by 4.5%, not the 18.0% the summer split advertised, and that difference is
now stated wherever the figure appears.

**Both splits are legitimate and answer different questions.** Recency asks "does it work
next month"; season-block asks "does it work in Delhi's winter". Quoting only the first
would have been the more flattering choice and the less honest one.

## D-050 · Wind closes R6, and the literature gate caught the same bug a second time
The problem statement names **temperature, wind and PBL height**. Round 1 modelled two of
the three. `feedback.wind_response()` adds the missing one: aerosol cooling weakens the
heat flux that drives turbulent mixing, less momentum is transported down from aloft, and
the surface wind slackens.

**Scaled from the published ratio, not fitted.** Xing et al. report wind falling 1.6-4.3%
in the same experiments where PBL falls 13.0-20.9%, so the response is about a fifth of
the boundary-layer suppression. Verified across the range: 13% PBL suppression gives
2.60% wind, 21% gives 4.20% — inside the reported band at both ends.

**The gate caught a real bug, and it was a repeat offence.** The first implementation
clipped the response to the suppression side only, so the pristine control — which has a
*deeper* layer — could not differ from the baseline. Measured wind reduction came out at
**0.462%** against a 0.5-6.0% bound and failed. This is precisely the mistake already made
once in `pbl_response` (D-016): **clipping a two-sided response to one side**. Both are
now two-sided, and a test encodes the correct behaviour rather than the convenient one.

**All five gates now pass** on 13,109 high-aerosol daylight hours:

| quantity | measured | published bound |
|---|---|---|
| shortwave reduction | 13.50% | 5-35% |
| daytime cooling | −0.74 K | 0.1-2.5 K |
| PBL suppression | 7.00% | 5-35% |
| PM2.5 amplification | 7.50% | 2-30% |
| **wind reduction** | **1.46%** | 0.5-6.0% |

**R6 is now complete**: temperature, wind and PBL all respond on the meteorological side;
PM2.5 drives the loop, and NO₂ and O₃ enter it through photolysis (D-039).

## D-051 · Leave-one-station-out: the gridded product is justified
Every score before this was temporal — different hours, same stations. That answers "does
it work next week". It does not answer the question a **gridded** forecast rests on: we
serve 1,115 cells and about 40 contain an instrument, so for a thousand of them the model
is extrapolating in space and nothing had tested whether it can.

Each station removed from training entirely, model rebuilt on the rest, predicting a
place it has never seen:

| target | stations | RMSE | persistence | vs persistence | beat |
|---|---|---|---|---|---|
| **PM2.5 +24 h** | 10 | 32.16 | 57.16 | **+43.5%** | **10/10** |
| **O₃ +24 h** | 10 | 15.28 | 23.32 | **+32.6%** | **10/10** |

Per-station improvements ran +21.9% to +53.3% for PM2.5 and +12.8% to +42.9% for ozone.
Not one of the twenty station-target pairs failed.

**The margin is larger than it looks**, because the comparison is deliberately unfair to
us: persistence uses the held-out station's **own recent history**, which the model is
denied entirely. A model that has never seen a location still beats a baseline that has.

**What this licenses.** Producing a value for a cell with no instrument is defensible
rather than decorative. Had this failed, the honest description would have been "a
station interpolator wearing a map", and it would have had to be said that way.

## D-052 · Dashboard surfaces the two new results
- **Photolysis panel** on the Coupling view: clear-air versus with-aerosol J(NO₂) hour by
  hour, with the ozone counterfactual beside it and the published Delhi comparison
  stated in the caption rather than left implicit.
- **Wind** added to the loop as step 4b, so all three meteorological variables the PS
  names are visible in the chain.
- **Plume calibration panel** on the Plume view: the three vertical treatments ranked by
  correlation against the MoES DSS attribution, with the shipped one marked and the
  daily-resolution caveat printed underneath.

## D-053 · A train/serve gap that the safety net was hiding
The dashboard's new photolysis chart rendered "No values in this window", and the cause
was worse than a display bug: **`forecast.run` never computed the photolysis features**,
while the ozone and NO₂ heads had been trained with fourteen of them.

It did not raise. `Head.check_features` exists precisely to catch this, but the inference
loop contained a convenience line:

```python
for col in head.features:
    if col not in block.columns:
        block[col] = np.nan
```

That fills every absent trained feature with NaN and walks straight past the check. The
models were being served nulls for the physics we had just spent a day adding, and the
forecast reported `degraded: []` throughout.

**Two fixes, because one was not enough.** `photolysis.add_features` now runs on the
inference path, computed exactly as in training. And the fallback is no longer silent: an
absent trained feature is recorded in `notes` and flagged in `degraded`, because filling
one with NaN is a real degradation rather than a formality — the model was fitted
expecting a value there.

**The lesson.** A safety net that can be bypassed by ordinary convenience code is not a
safety net. The check was correct; the caller defeated it, and only a rendered chart
saying "no values" exposed it.

## D-054 · Gap analysis: the project had exactly ONE winter
A survey of every station within 60 km of Delhi against the OpenAQ S3 archive:

| year | stations with data |
|---|---|
| 2018 | 75 |
| 2019 | 58 |
| 2020 | 67 |
| 2021 | 66 |
| 2022 | 66 |
| 2023-2024 | 1-3 (the archive gap) |
| 2025 | 75 |
| 2026 | 89 |

**Seven usable winter seasons exist and we were training on one.** 2016-17, 2017-18,
2018-19, 2019-20, 2020-21, 2021-22 and 2025-26, the middle four with 47-65 stations each.

**This explains the weakest number in the project.** With only Nov 2025 - Feb 2026
available, the winter hold-out removed the *only* winter from training — so the model was
tested on winter having never seen one. PM2.5 at +24 h scored **+4.5%** over persistence
under that arrangement. Neither split reflected operational reality, which is *trained on
past winters, forecasting the current one*:

 - recency split: winter **in** training, tested on summer — winter never evaluated;
 - winter hold-out: winter tested, but **absent** from training — pessimistic by design.

**Fix.** A second panel covering Oct 2018 - Mar 2022 (four more winters, 40 stations,
47,984 station-days) to concatenate with the existing one. CAMS does not reach back that
far, so the multi-year model runs without a chemistry prior and is reported as such.

**A published Delhi study uses a decade of winters** for exactly this reason, which is
corroboration that one winter was never going to be enough.

## D-055 · Prediction intervals and GRAP exceedance probabilities
A point forecast of 118 µg/m³ sitting just under a GRAP boundary tells an official
nothing about the risk of crossing it, and GRAP stages are what a decision actually turns
on. `uncertainty.py` fits five quantiles with XGBoost's `reg:quantileerror` and
interpolates the conditional CDF to give the probability of breaching each stage.

**First run, on the winter-blind model** (the only winter held out):

| | |
|---|---|
| interval coverage | **66.7%** against 80% nominal — over-confident |
| quantile crossing rate | 5.7% (repaired by row-wise sorting, and reported) |

| GRAP threshold | observed | predicted | Brier | **skill vs climatology** |
|---|---|---|---|---|
| AQI 200 (Stage II) | 0.808 | 0.786 | 0.108 | **+0.304** |
| AQI 300 (Stage III) | 0.663 | 0.655 | 0.156 | **+0.304** |
| AQI 400 (Stage IV) | 0.208 | 0.168 | 0.130 | **+0.213** |

**The probabilities are well calibrated and beat climatology at every threshold**, which
is the useful result. **The interval is too narrow**, and that is the same one-winter
problem: a model that has never seen a winter is confidently wrong about one, and its
quantiles inherit the confidence without the accuracy.

**A Brier score alone is not interpretable** — 0.108 sounds good until you notice that
always predicting the base rate scores 0.155 on the same data. The skill score against
that climatological forecast is reported alongside, because it is the number that says
whether the model knows anything.
