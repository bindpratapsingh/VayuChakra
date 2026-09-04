# VayuChakra · वायु चक्र

**Coupled weather–chemistry forecasting for Delhi NCR**

> Built for: Ministry of Earth Sciences / NCMRWF —
> *Air Pollution–Weather Coupled Forecasting System (Delhi NCR Focus)*

---

## The problem, in one paragraph

Every operational AQI forecast treats weather as an input: wind disperses, rain
scavenges, a shallow boundary layer concentrates. That is one direction only. The real
atmosphere runs a loop — dense aerosol blocks sunlight, the surface heats less, the
mixed layer grows shallower, and the same emissions end up more concentrated, which
blocks more sunlight. The problem statement calls ignoring that loop a source of
"significant inaccuracies".

**VayuChakra closes the loop and measures whether closing it helps.**

---

## What it does

| | |
|---|---|
| **Two-way coupling** | An explicit five-step solver: PM2.5 → optical depth → shortwave → temperature → boundary layer → PM2.5, iterated to convergence |
| **Separate PM2.5 and O₃** | Two model heads, because their physics and seasons are opposite — ozone peaks on bright afternoons and *rises when NOx falls* |
| **Inversion tracking** | Strength in kelvin, lid height, mixing depth, ventilation coefficient, stagnation run length |
| **Plume dispersion** | Lagrangian puffs released from satellite fire detections, advected on forecast wind, gated by the inversion lid |
| **72-hour outlook** | 1,115 cells — ~2.8 km over Delhi, ~11 km across the wider NCR |
| **Validated against the MoES DSS** | Head-to-head with the ministry's own operational system on identical observations |

---

## The coupled solver

Five steps, each separately checkable against published values. None is a fitted black
box.

```
1. PM2.5  → AOD          elasticity fitted on paired CAMS output
2. AOD    → shortwave    Beer–Lambert, minus forward-scattered light that still arrives
3. ΔSW    → ΔT           surface energy balance
4. ΔT     → ΔPBL         encroachment: h ∝ √(accumulated heat)
4b. ΔPBL  → Δwind        less mixing carries less momentum down from aloft
5. ΔPBL   → ΔPM2.5       box model: same mass, shallower layer

  plus, in parallel and stronger for ozone:
   AOD → ultraviolet → photolysis rate → ozone production
```

All three meteorological variables the problem statement names — **temperature, wind and
PBL height** — now respond, and NO₂ and O₃ enter the loop through photolysis.

Step 5 feeds step 1, so it is **solved**, not evaluated — damped fixed-point iteration
with clipped responses, an iteration cap, and a divergence flag that falls back to the
uncoupled answer rather than shipping a number it could not solve for.

**Measured against published Delhi ranges** (high-aerosol daylight hours, Nov–Dec 2024,
5,856 hours, converged in 6 iterations, 0 diverged):

| | measured | published |
|---|---|---|
| Shortwave reduction | 13.5% | 5–35% |
| Daytime cooling | −0.74 K | 0.1–2.5 K |
| PBL suppression | 7.0% | 5–35% |
| PM2.5 amplification | 7.5% | 2–30% |
| **Surface wind slackening** | **1.46%** | 0.5–6.0% |

Five for five, on 13,109 high-aerosol daylight hours.

---

## Results

**All twelve forecast heads beat persistence.** Persistence — "tomorrow looks like
today" — is the baseline that matters and is embarrassingly hard to beat at 24 hours.
Trained on 536,670 station-hours from 40 stations, Feb 2025 to Aug 2026, chronological
hold-out.

| head | RMSE | persistence | improvement | r² |
|---|---|---|---|---|
| **PM2.5** +24 / +48 / +72 h | 26.22 / 26.69 / 26.47 | 31.96 / 34.01 / 35.36 | **+18.0 / +21.5 / +25.1%** | 0.19 / 0.16 / 0.17 |
| **O₃** +24 / +48 / +72 h | 17.58 / 18.55 / 19.01 | 22.01 / 23.18 / 23.42 | **+20.1 / +20.0 / +18.8%** | 0.61 / 0.56 / 0.54 |
| PM10 +24 / +48 / +72 h | 90.90 / 97.02 / 89.69 | 99.27 / 108.66 / 115.28 | +8.4 / +10.7 / +22.2% | 0.21 / 0.10 / 0.23 |
| NO₂ +24 / +48 / +72 h | 16.09 / 16.62 / 17.18 | 20.55 / 21.91 / 22.79 | +21.7 / +24.1 / +24.6% | 0.54 / 0.51 / 0.48 |

The margin **widens with lead time**, which is the expected shape: persistence decays
faster than a physics-informed model as the horizon grows.

### The same models, evaluated on a winter they never saw

The table above uses a **recency** split — and on this panel the most recent 20% is
May–August 2026, which contains **no winter at all**. Delhi's defining pollution season
was going unevaluated. Retraining with Nov 2025 – Feb 2026 held out entirely gives a
sharply different picture, and both are reported because they answer different questions.

**All twelve heads still beat persistence** on the unseen winter, but the margins are
very different from the summer numbers above.

| head | recency split (summer) | **winter hold-out** | winter r² |
|---|---|---|---|
| PM2.5 +24 h | +18.0% · RMSE 26.2 | **+4.5%** · RMSE 88.7 | 0.30 |
| PM2.5 +48 h | +21.5% | +13.8% | 0.26 |
| PM2.5 +72 h | +25.1% | +18.8% | 0.30 |
| O₃ +24 h | +20.1% · r² 0.61 | **+23.9%** · RMSE 20.1 | **0.76** |
| O₃ +48 h | +20.0% | +24.0% | 0.72 |
| O₃ +72 h | +18.8% | **+25.5%** | 0.70 |
| PM10 +24 / +48 / +72 h | +8.4 / +10.7 / +22.2% | +8.8 / +17.2 / +22.4% | 0.31 / 0.27 / 0.31 |
| NO₂ +24 / +48 / +72 h | +21.7 / +24.1 / +24.6% | +11.8 / +14.5 / +13.7% | 0.64 / 0.57 / 0.52 |

**PM2.5 in winter is a much harder problem**, and the 24-hour margin over persistence
nearly disappears. Winter Delhi is episode-driven — boundary-layer collapse, multi-day
accumulation, festival and burning spikes — and persistence is strongest exactly when
concentrations are high and slowly varying. The margin recovers at longer leads.

**Ozone goes the other way**, improving in winter at every horizon. That is consistent
with the radiation-limited regime: when production is controlled by available sunlight,
radiation and photolysis features have more to work with.

**The physics is doing work, not decorating.** By gain, three of the top seven features
are indices this project derives, and the coupled-model prior is third:

| rank | feature | what it is |
|---|---|---|
| 1–2 | `pm25_lag_1h`, `pm25_roll_72h` | persistence and trend, as expected |
| **3** | `target_cams_pm25` | the CAMS coupled-model prior |
| **4** | `target_is_episode` | our stagnation index |
| 6–7 | `vc_24h_mean`, `ventilation_coeff` | our ventilation indices |

### Against the MoES Decision Support System

Identical hours, identical ground truth (Delhi city-mean CPCB PM2.5), Oct 2021 – Feb
2022. Our models were trained on Feb 2025 – Aug 2026, so this window is genuinely out of
sample in time.

| lead | hours | MoES DSS | VayuChakra | persistence |
|---|---|---|---|---|
| +24 h | 2,363 | 98.78 | **81.28** | 93.98 |
| +48 h | 2,363 | 108.34 | **91.77** | 108.78 |
| +72 h | 2,363 | 118.95 | **101.22** | 115.00 |

**Read the caveat before quoting the table.** The DSS forecasts were issued
*operationally* — it had to predict the weather as well as the chemistry, days ahead.
Our hindcast is driven by ERA5 *reanalysis*, the meteorology as it actually turned out.
That is a material advantage and it is **not a fair comparison of forecast skill**.

The table supports: *the statistical layer maps meteorology to PM2.5 competitively.*
It does **not** support: *"we forecast better than the MoES DSS."*

### Stubble plume, scored against the MoES DSS attribution

Round 1 tested the plume against one four-day episode and got r = −0.12 — an
uninformative comparison, because transported smoke is a minority additive term against
a signal dominated by local emissions. The DSS workbook contains a far better reference:
a **daily stubble attribution in µg/m³ for 147 days**.

Scored over the 6 Oct – 30 Nov 2021 burning season, **229,709 archived FIRMS detections**:

| vertical treatment | r | RMSE | peak (scaled) | DSS peak |
|---|---|---|---|---|
| **A** — injection height fixed | **+0.596** | 8.28 | 27.7 | 38.0 |
| C — entrained + residual layer | +0.525 | 8.90 | 24.5 | 38.0 |
| B — entrained, no residual | +0.369 | 9.95 | 22.4 | 38.0 |

Only a **single scale factor** is fitted, absorbing emission-factor uncertainty
(5–8 g/kg for cereal straw), satellite detection limits and burn-duration assumptions.
Correlation cannot be improved by scaling, so the ranking measures physics, not magnitude.

**This overturned a Round 1 decision.** We had shipped C on the argument that its
vertical treatment is the most physically complete, having rejected A from a single
episode. Over a full season against the operational reference, A has the best day-to-day
timing — so A is now the default. The caveat: the DSS attribution is *daily*, so it
settles day-to-day timing and nothing finer, and cannot discriminate the variants on
their diurnal behaviour, which is where A remains questionable.

### Aerosol and ozone: a counterfactual, validated

Explicit photolysis features did **not** improve the ozone forecast (17.61 vs 17.58 RMSE
— a wash). But a statistical model can only interpolate conditions it has seen; it cannot
answer *"what would ozone be if Delhi's aerosol halved?"* A mechanism can.

Trained with Nov 2025 – Feb 2026 held out entirely:

| AOD reduction | modelled ozone change (winter daytime) |
|---|---|
| −25% | +6.23% |
| **−50%** | **+12.79%** |
| −75% | +24.29% |

The published Delhi figure is **+25% ozone for a 50% AOD cut** (Nelson et al., Faraday
Discussions 226, 2021). Ours gives +12.79% — same sign, monotonic, **within a factor of
two of a number the model was never fitted to and never saw**.

The seasonal split corroborates the mechanism: the same experiment on a *summer* hold-out
gives only +4.03%. Winter is threefold stronger, exactly as the radiation-limited
explanation predicts. We did not build that seasonality in.

The remaining factor of two is the expected direction: the published figure comes from a
box model with full VOC chemistry, where reduced photolysis also slows OH production and
the whole oxidation chain. We have no VOC measurements and model only the direct pathway.

### Does it work where there is no monitor?

The forecast serves 1,115 cells and about 40 contain an instrument. Every score above is
temporal — different hours, same stations. Leave-one-station-out removes a station from
training entirely and predicts a place the model has never seen.

| target | stations | RMSE | persistence | vs persistence | beat |
|---|---|---|---|---|---|
| **PM2.5 +24 h** | 10 | 32.16 | 57.16 | **+43.5%** | **10/10** |
| **O₃ +24 h** | 10 | 15.28 | 23.32 | **+32.6%** | **10/10** |

The margin is larger than it looks, because the comparison is deliberately unfair to us:
persistence uses the held-out station's **own recent history**, which the model is denied.
A model that has never seen a location still beats a baseline that has — so producing a
value for a cell with no instrument is defensible rather than decorative.

### Does the PM2.5 coupling help? A negative result

The problem statement asserts that ignoring the feedback "leads to significant
inaccuracies". We tested that rather than repeating it. Both arms are re-centred to zero
mean bias first, so this measures shape and timing rather than which arm was allowed to
fit an intercept.

| regime | n | uncoupled | coupled | change |
|---|---|---|---|---|
| overall | 48,181 | 82.76 | 82.85 | **−0.11%** |
| stagnant episode | 40,047 | 83.95 | 84.01 | −0.07% |
| well ventilated | 8,134 | 76.61 | 76.77 | −0.21% |
| high aerosol | 28,440 | 83.29 | 83.00 | **+0.35%** |

The feedback's *magnitudes* are right — all four literature checks pass. But switching it
on does **not** measurably improve PM2.5 against observations, except marginally where
aerosol is high. The most interesting candidate explanation is that the trained model
already receives mixing depth, ventilation coefficient, shortwave and the stagnation
indices, and may be learning the feedback's effect implicitly — in which case adding it
explicitly is double-counting rather than new information. See D-036.

---

## What this is, and what it is not

**It is** a coupled *surrogate*: driven by CAMS (ECMWF's operational coupled
chemistry model), calibrated against CPCB ground truth, validated against the MoES DSS.

**It is not** WRF-Chem. There is no radiative transfer solve, no vertical layering, no
aerosol microphysics, no chemistry en route. The feedback is parameterised.

We never claim to have built or run WRF-Chem. The `DSS Paper related/` workbook is
third-party research output from IITM / NCMRWF / TERI / NCAR — **cited, never
redistributed, never presented as ours**.

---

## Data sources

All free. No paid service anywhere.

| Source | Provides | Key |
|---|---|---|
| Open-Meteo Forecast | PBL height, pressure-level temperatures, radiation, wind | none |
| Open-Meteo Air Quality (CAMS) | PM2.5, PM10, **O₃**, NO₂, **aerosol optical depth** | none |
| Open-Meteo ERA5 Archive | Hindcast meteorology back to 2021 | none |
| OpenAQ v3 API + S3 archive | CPCB station observations, live and historical | free |
| NASA FIRMS | VIIRS/MODIS active fire detections | free |

---

## Layout

```
vayuchakra/
  config.py      domain, credentials, physical constants, acceptance bounds
  net.py         cached HTTP that never raises
  grid.py        two-tier NCR grid, 19 DSS districts, geometry
  met.py         meteorology ingestion, forecast and ERA5 archive
  indices.py     inversion strength, mixing depth, ventilation, stability class
  chem_prior.py  CAMS chemistry prior
  obs.py         CPCB observations via OpenAQ API and S3
  feedback.py    THE COUPLED SOLVER
  plume.py       Lagrangian stubble-smoke transport
  aqi.py         CPCB National AQI from concentrations
  dataset.py     supervised panel assembly
  model.py       dual-head XGBoost with a persisted feature contract
  forecast.py    the full pipeline
  validate.py    DSS head-to-head and the coupling ablation
  dss.py         MoES DSS workbook reader
api/main.py      local FastAPI
scripts/         build_dataset.py, train.py
tests/           66 offline tests
```

---

## Reproducing this

Two free API keys are needed — OpenAQ and NASA FIRMS. Copy `.env.example` to `.env` and
fill them in. Everything else (Open-Meteo forecast, ERA5 archive, CAMS chemistry) is
keyless. Without the keys the system still runs and reports which stages could not.

```bash
pip install -r requirements.txt
python -m pytest tests/ -q                      # 74 offline tests, no network

# Data. The recent panel is ~45 min; the multi-winter one ~75 min. Both cache to
# parquet, so this is a one-time cost.
python scripts/build_dataset.py --start 2025-02-01 --end 2026-08-31 --stations 40        --name train_panel
python scripts/build_dataset.py --start 2018-10-01 --end 2022-03-31 --stations 40        --name winters_panel --no-chem

# Everything else, in dependency order: combine, train, quantiles, LOSO, DSS.
bash scripts/run_all.sh

uvicorn api.main:app --port 8100                # then open dashboard/index.html
```

Individual experiments:

| script | question it answers |
|---|---|
| `ozone_sensitivity.py` | what would ozone be if the aerosol halved? |
| `plume_calibrate.py` | which vertical treatment matches the MoES DSS? |
| `photolysis_ablation.py` | does explicit photolysis improve the forecast? |
| `loso.py` | does it work where there is no instrument? |
| `case_study.py` | replay a past burning episode |

**Nothing here is deployed.** No hosting, no public URL, no keep-alive. The dashboard
talks to `127.0.0.1:8100` and nothing else.

---

## Where this is still weak

The gaps are listed because a reviewer will find them anyway, and finding them first is
the only version of this that is worth anything.

| gap | status |
|---|---|
| **We do not run a chemical transport model** | Structural. WRF-Chem needs an HPC cluster and a district emission inventory we do not have. We consume CAMS instead and call it a surrogate. |
| **No VOC chemistry** | Delhi ozone is VOC-limited and we have no VOC measurements. TROPOMI HCHO/NO₂ could give a regime map (threshold FNR ≈ 3.1) but needs NetCDF orbit processing. |
| **Single layer** | No vertical discretisation. The largest remaining simplification. |
| **PM2.5 winter skill** | The weakest number in the project, and the one most improved by the multi-winter data. |
| **Plume validated only at daily resolution** | The DSS attribution is daily, so it cannot discriminate the vertical treatments on their behaviour through the night. |
| **No operational run cycle** | The API caches for an hour but nothing schedules a refresh. |

---

## Design decisions

Every non-obvious choice, the measurement behind it, and what would reverse it is
logged in [DECISIONS.md](DECISIONS.md) — including the bugs found along the way and how
each was caught. Several were only visible because output magnitudes were checked
against physical expectations rather than eyeballed.

## Known limitations

Stated here rather than buried, because a reviewer will find them anyway.

- **The stubble plume case study is a limitation, not a result.** Three physics variants
  were tried on the 5–8 Nov 2021 episode. The most defensible one (entrainment with a
  residual layer) produces a plume magnitude uncertain to within an order of magnitude
  and a weak, slightly negative correlation against the observed residual. A variant
  that correlates better exists and was **not** chosen, because selecting it would be
  fitting physics to the demo. See D-033.
- **CAMS has no coverage before mid-August 2022**, so any run over the MoES DSS window
  (Oct 2021 – Feb 2022) is a reduced configuration without a chemistry prior, and is
  labelled as such wherever its numbers appear.
- **The ERA5 archive serves no pressure levels**, so hindcasts compute inversion from a
  surface proxy and leave inversion strength in kelvin genuinely missing rather than
  filling it with a zero.
- **The feedback is parameterised, not a radiative-transfer solve.** No spectral
  integration, no vertical layering, no aerosol microphysics.
- **The coupling ablation is a negative result** and is reported as one. See above.
- **The DSS comparison is not like-for-like** — reanalysis versus operational forecast.
- **Spatial resolution is 6 km, not 2.8 km.** The display grid is finer than the inputs,
  so predicted fields are smoothed to the resolution the drivers actually carry. Without
  it the map rendered tree-leaf quantisation as though it were a pollution gradient.
