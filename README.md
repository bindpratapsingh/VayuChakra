# VayuChakra · वायु चक्र

*Vayu chakra* means "the air cycle", and the cycle is the whole point.

### ▶ [vayuchakra.onrender.com](https://vayuchakra.onrender.com)

> **Give it a minute on the first click.** It sleeps on a free instance and wakes
> slowly. There is no keep-alive pinging it awake, on purpose: that is what burned
> through the free allowance and got a sibling project's account suspended.

---

## Why this exists

Ask any air quality forecast what tomorrow looks like and it will tell you about the
weather: the wind will disperse, the rain will scavenge, a shallow boundary layer will
trap. All true, and all one direction. Weather happens *to* pollution.

Except it does not, quite. On a bad Delhi winter day the smog is thick enough to dim the
sun measurably. Less sunlight reaches the ground, so the ground warms less, so the
column of air that mixes over the city grows shallower and the breeze through it
slackens. The same emissions are now packed into less air. Which makes the smog thicker.
Which dims the sun further.

That is a loop, and it is running right now over Delhi. Most operational systems cut it
after the first step, because closing it means solving something rather than evaluating
it. The MoES problem statement calls leaving it out a source of "significant
inaccuracies", and it is right.

**VayuChakra closes the loop, and then measures whether closing it actually helped.**
It did not, much, on forecast error. That answer is in here too, in section
[Does the coupling help?](#does-the-pm25-coupling-help-a-negative-result), because a
system that only reports its wins has not been validated.

---

## What you are looking at

A 72-hour air quality forecast for Delhi and the wider NCR, on 1,120 grid cells, about
2.8 km across the city and 11 km out to Alwar and Karnal. Four pollutants: PM2.5, PM10,
NO₂ and ozone, combined into the CPCB National AQI. Underneath it:

- **A coupled solver** that runs the loop above to convergence, with every response
  clipped to a physically defensible range and checked against published Delhi values
  the model has never been fitted to. Eight of eight land inside.
- **An inversion tracker**, because the lid over the city is the single most important
  thing about a Delhi winter night and almost nothing displays it. Strength in kelvin,
  lid height in metres, and a time-height cross-section you can actually read.
- **A stubble plume model** that takes satellite fire detections in Punjab and Haryana,
  carries them on the forecast wind, and works out whether that smoke arrives at
  breathing height or passes overhead. A thousand fires with the wrong wind are
  somebody else's problem that day, and the model says so.
- **Twelve forecast heads**, all of which beat persistence on a winter they were never
  trained on. Persistence is the baseline that matters and it is unglamorously hard to
  beat.

Everything on the site is read from a result file. Nothing is typed in by hand, and the
things that failed are on screen next to the things that worked.

The full write-up is a 26 page PDF:
**[docs/VayuChakra-Report.pdf](docs/VayuChakra-Report.pdf)**. It takes the problem
statement apart clause by clause and says exactly which ones are met, which are not, and
why. It also downloads from the dashboard itself.

---

## About the hosted version

It serves a **precomputed forecast**, and every view says so rather than quietly
presenting stale numbers as live.

The reason is arithmetic. The pipeline peaks around 1.1 GB and a free instance has
512 MB, so it cannot run there at any grid resolution. Instead a GitHub Actions runner
with 16 GB runs the real pipeline every six hours, at full resolution, and commits the
result; Render picks it up and serves it. What a free deployment gives up is freshness,
not resolution and not physics. Run it locally for a live forecast, which is two
commands and they are further down.

## The interface

The dashboard is deliberately not a ward map. A ward choropleth answers "should I go
outside", which is a good question and a different product. This problem statement is
about the vertical structure of the atmosphere and about transport across a region, so
the views are named for the physics rather than for pages.

| view | what it answers |
|---|---|
| **Domain** | Where the air comes from. The full 27.0 to 29.9 N extent, the stubble belt running off the northern edge, live fire detections, and an arrow from today's fire centroid to the city. |
| **Vertical** | What the lid is doing. A time and height cross-section: hours on x, metres above ground on y, static stability as the fill, mixing depth as a line, and the inversion lid marked where one exists. |
| **Coupling** | The loop, step by step, with each step's live value and each one checked against a published Delhi range. |
| **Transport** | Whether the smoke actually arrives, and how the model scores against the MoES DSS attribution. |
| **Forecast** | The surface product. CPCB AQI per cell, and the probability of breaching each GRAP stage. |
| **Evidence** | Every validation number, negative results included. |
| **About** | What the system is, the problem statement quoted, and all eleven clauses of it with the status of each. The species clause is not asserted: it is checked against what the running solver reports it coupled, so the table cannot drift into claiming something the live system no longer does. |

The cross-section is the one that did not exist before. Inversion lid, mixing depth and
the temperature profile at 950, 925 and 850 hPa were all being computed and then
flattened into three line charts of surface scalars. On a 168-hour window the lid is
present in 95 hours and absent in 73, and absence is drawn as absence rather than joined
through: "no lid" and "a lid at ground level" are opposite statements about the
atmosphere and must not share a pixel.

Screenshots are in [docs/shots/](docs/shots/).

---

## The coupled solver

Five steps, each separately checkable against published values. None is a fitted black
box.

```
1. PM + dust → AOD       two modes: fine mass and coarse mass, own elasticities
2. AOD    → shortwave    Beer–Lambert, minus forward-scattered light that still arrives
3. ΔSW    → ΔT           surface energy balance
4. ΔT     → ΔPBL         encroachment: h ∝ √(accumulated heat)
4b. ΔPBL  → Δwind        less mixing carries less momentum down from aloft
5. ΔPBL   → ΔPM2.5       box model: same mass, shallower layer

  plus, in parallel and stronger for ozone:
   AOD → ultraviolet → photolysis rate → ozone production
```

All three meteorological variables the problem statement names, **temperature, wind and
PBL height**, respond. So do **all four chemical species it names**.

The return path used to run through fine mass alone, and that was a real hole rather than
a tidy simplification. Over the Indo-Gangetic Plain a PM2.5-only optical depth
underestimates the column by 15 to 25 percent in winter and **60 to 75 percent in the
pre-monsoon**, when Thar dust owns the sky and the fine mode carries under a fifth of the
extinction. So optical depth is now built from two modes that are genuinely different
objects: mass extinction efficiency 4.4 against 0.85 m²/g, and a soluble fine mode that
swells with humidity against mineral dust that does not. A dust column and a smoke column
of equal optical depth no longer dim the surface by the same amount, because dust
scatters forward and barely absorbs while soot does the opposite.

NO₂ and ozone still do not close a loop back to the radiation budget, and that is
physics rather than a shortcut: neither moves the shortwave balance appreciably at these
concentrations. They respond to the meteorology the solver produces.

Step 5 feeds step 1, so it is **solved**, not evaluated. Damped fixed-point iteration
with clipped responses, an iteration cap, and a divergence flag that falls back to the
uncoupled answer rather than shipping a number it could not solve for.

**Measured against published Delhi ranges** (high-aerosol daylight hours,
67,458 cell-hours of the shipped run, converged in 5
iterations, 0 diverged):

| | measured | published |
|---|---|---|
| Shortwave reduction | 11.708% | 5-35% |
| Daytime cooling | -0.628 K | 0.1-2.5 K |
| PBL suppression | 6.045% | 5-35% |
| Surface wind slackening | 1.267% | 0.5-6.0% |
| PM2.5 amplification | 6.251% | 2-30% |
| **PM10 amplification** | **5.323%** | 1-25% |
| **NO₂ amplification** | **19.904%** | 2-35% |
| **O₃ response** | **-0.061%** | must be negative |

**Eight for eight.** PM10 moves less than PM2.5, as it must: it is fine plus a coarse
excess, and coarse dust sediments out of a collapsing layer instead of accumulating in it.
Ozone is checked on **direction**, not magnitude: the solver applies only the closure term
the trained head could not see, so its size is small by construction, but attenuated
ultraviolet cannot produce more ozone and a positive value there would mean the pathway is
wired backwards.

---

## Results

**All twelve forecast heads beat persistence.** Persistence, meaning "tomorrow looks like
today", is the baseline that matters and is embarrassingly hard to beat at 24 hours.
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

The table above uses a **recency** split, and on this panel the most recent 20% is
May–August 2026, which contains **no winter at all**. Delhi's defining pollution season
was going unevaluated. Retraining with Nov 2025 – Feb 2026 held out entirely gives a
sharply different picture, and both are reported because they answer different questions.

**All twelve heads beat persistence** on the unseen winter. The table below holds
Nov 2025 to Feb 2026 out entirely and compares two training sets on that identical
window, against the identical persistence baseline.

| head | trained on **one** winter | trained on **four** winters | change |
|---|---|---|---|
| PM2.5 +24 h | +4.5% · r² 0.30 | **+19.2%** · RMSE 75.1 · r² **0.50** | **+14.7 pts** |
| PM2.5 +48 h | +13.8% · r² 0.26 | **+26.0%** · r² **0.45** | **+12.2 pts** |
| PM2.5 +72 h | +18.8% · r² 0.30 | **+28.9%** · r² **0.46** | **+10.1 pts** |
| O₃ +24 h | +23.9% · r² 0.76 | +19.3% · r² 0.73 | −4.6 pts |
| O₃ +48 h | +24.0% · r² 0.72 | +19.9% · r² 0.70 | −4.1 pts |
| O₃ +72 h | +25.5% · r² 0.70 | +21.2% · r² 0.67 | −4.3 pts |
| PM10 +24 / +48 / +72 h | +8.8 / +17.2 / +22.4% | **+17.2 / +24.8 / +27.6%** | +8.4 / +7.6 / +5.2 |
| NO₂ +24 / +48 / +72 h | +11.8 / +14.5 / +13.7% | **+15.0 / +17.5 / +18.1%** | +3.2 / +3.0 / +4.4 |

**PM2.5 in winter was the weakest number in the project and it is now the most
improved.** On one winter the 24-hour margin over persistence nearly vanished, at +4.5%,
because winter Delhi is episode-driven (boundary-layer collapse, multi-day accumulation,
festival and burning spikes) and persistence is strongest exactly when concentrations
are high and slowly varying. Given three more winters to learn those episodes from, the
margin quadruples and the explained variance rises from 0.30 to 0.50.

**Ozone moves the other way, and the reason is known rather than mysterious.** The
multi-winter panel cannot carry CAMS: the chemistry prior begins in August 2022, and
keeping it would let a tree use "the prior is not missing" as a proxy for "this row is
recent". So the combined panel drops it, and the ozone heads lose both the CAMS prior
and the daily aerosol optical depth, which is replaced by a monthly climatology. Ozone
was the head that leaned on those hardest. The cost is about four points and it buys
fourteen on PM2.5.

That trade is why **both configurations are kept and reported side by side** rather than
blended: the recent-panel models keep CAMS and are better at ozone, the multi-winter
models are much better at everything else.

**The physics is doing work, not decorating.** By gain, three of the top seven features
are indices this project derives, and the coupled-model prior is third:

| rank | feature | what it is |
|---|---|---|
| 1–2 | `pm25_lag_1h`, `pm25_roll_72h` | persistence and trend, as expected |
| **3** | `target_cams_pm25` | the CAMS coupled-model prior |
| **4** | `target_is_episode` | our stagnation index |
| 6–7 | `vc_24h_mean`, `ventilation_coeff` | our ventilation indices |

### Against the MoES Decision Support System

Identical hours, identical ground truth (Delhi city-mean CPCB PM2.5), Oct 2021 to Feb
2022. The multi-winter panel now *contains* that window, so scoring it with the
production models would be measuring memorisation. A second set of heads is trained with
winter 2021-22 held out entirely and used only here.

| lead | hours | MoES DSS | VayuChakra | persistence |
|---|---|---|---|---|
| +24 h | 2,363 | 98.78 | **64.26** | 93.98 |
| +48 h | 2,363 | 108.34 | **68.91** | 108.78 |
| +72 h | 2,363 | 118.95 | **72.82** | 115.00 |

Those held-out heads beat persistence by +23.2 / +30.6 / +29.8% on the 2021-22 winter
they never saw.

**Read the caveat before quoting the table.** The DSS forecasts were issued
*operationally*: it had to predict the weather as well as the chemistry, days ahead.
Our hindcast is driven by ERA5 *reanalysis*, the meteorology as it actually turned out.
That is a material advantage and it is **not a fair comparison of forecast skill**.

The table supports: *the statistical layer maps meteorology to PM2.5 competitively.*
It does **not** support: *"we forecast better than the MoES DSS."*

### Stubble plume, scored against the MoES DSS attribution

Round 1 tested the plume against one four-day episode and got r = −0.12, an
uninformative comparison, because transported smoke is a minority additive term against
a signal dominated by local emissions. The DSS workbook contains a far better reference:
a **daily stubble attribution in µg/m³ for 147 days**.

Scored over the 6 Oct – 30 Nov 2021 burning season, **229,709 archived FIRMS detections**:

| vertical treatment | r | RMSE | peak (scaled) | DSS peak |
|---|---|---|---|---|
| **A**, injection height fixed | **+0.596** | 8.28 | 27.7 | 38.0 |
| C, entrained plus residual layer | +0.525 | 8.90 | 24.5 | 38.0 |
| B, entrained, no residual | +0.369 | 9.95 | 22.4 | 38.0 |

Only a **single scale factor** is fitted, absorbing emission-factor uncertainty
(5–8 g/kg for cereal straw), satellite detection limits and burn-duration assumptions.
Correlation cannot be improved by scaling, so the ranking measures physics, not magnitude.

**This overturned a Round 1 decision.** We had shipped C on the argument that its
vertical treatment is the most physically complete, having rejected A from a single
episode. Over a full season against the operational reference, A has the best day-to-day
timing, so A is now the default. The caveat: the DSS attribution is *daily*, so it
settles day-to-day timing and nothing finer, and cannot discriminate the variants on
their diurnal behaviour, which is where A remains questionable.

### Aerosol and ozone: a counterfactual, validated

Explicit photolysis features did **not** improve the ozone forecast (17.61 vs 17.58 RMSE
a wash). But a statistical model can only interpolate conditions it has seen; it cannot
answer *"what would ozone be if Delhi's aerosol halved?"* A mechanism can.

Trained with Nov 2025 – Feb 2026 held out entirely:

| AOD reduction | modelled ozone change (winter daytime) |
|---|---|
| −25% | +6.23% |
| **−50%** | **+12.79%** |
| −75% | +24.29% |

The published Delhi figure is **+25% ozone for a 50% AOD cut** (Nelson et al., Faraday
Discussions 226, 2021). Ours gives +12.79%: same sign, monotonic, **within a factor of
two of a number the model was never fitted to and never saw**.

The seasonal split corroborates the mechanism: the same experiment on a *summer* hold-out
gives only +4.03%. Winter is threefold stronger, exactly as the radiation-limited
explanation predicts. We did not build that seasonality in.

The remaining factor of two is the expected direction: the published figure comes from a
box model with full VOC chemistry, where reduced photolysis also slows OH production and
the whole oxidation chain. We have no VOC measurements and model only the direct pathway.

### Does it work where there is no monitor?

The forecast serves 1,120 cells and about 40 contain an instrument. Every score above is
temporal, different hours and the same stations. Leave-one-station-out removes a station from
training entirely and predicts a place the model has never seen.

| target | stations | RMSE | persistence | vs persistence | beat |
|---|---|---|---|---|---|
| **PM2.5 +24 h** | 10 | 56.07 | 81.31 | **+31.6%** | **10/10** |
| **O₃ +24 h** | 10 | 22.92 | 27.65 | **+17.2%** | 9/10 |

The margin is larger than it looks, because the comparison is deliberately unfair to us:
persistence uses the held-out station's **own recent history**, which the model is denied.
A model that has never seen a location still beats a baseline that has, so producing a
value for a cell with no instrument is defensible rather than decorative.

The absolute errors are higher than the single-winter run reported, and the percentages
lower, because this is measured on the four-winter panel: 44 stations instead of 40 and
four winters of episodes instead of one. It is a harder test on more data, not a
regression. **One ozone station out of ten now fails to beat persistence**, and that is
reported rather than rounded away.

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

The feedback's *magnitudes* are right, and all four literature checks pass. But switching it
on does **not** measurably improve PM2.5 against observations, except marginally where
aerosol is high. The most interesting candidate explanation is that the trained model
already receives mixing depth, ventilation coefficient, shortwave and the stagnation
indices, and may be learning the feedback's effect implicitly, in which case adding it
explicitly is double-counting rather than new information. See D-036.

---

## What this is, and what it is not

**It is** a coupled *surrogate*: driven by CAMS (ECMWF's operational coupled
chemistry model), calibrated against CPCB ground truth, validated against the MoES DSS.

**It is not** WRF-Chem. There is no radiative transfer solve, no vertical layering, no
aerosol microphysics, no chemistry en route. The feedback is parameterised.

We never claim to have built or run WRF-Chem. The `DSS Paper related/` workbook is
third-party research output from IITM / NCMRWF / TERI / NCAR. **Cited, never
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
  grid.py        two-tier NCR grid, 20 DSS districts, geometry
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
  photolysis.py  MCM clear-sky J, aerosol attenuation of ultraviolet
  uncertainty.py quantile heads, interval coverage, GRAP exceedance probability
api/main.py      local FastAPI
dashboard/       the seven-view interface, one file, no build step
scripts/         build_dataset.py, train.py, run_all.sh, and the validators
tests/           76 offline tests
```

---

## Reproducing this

Two free API keys are needed: OpenAQ and NASA FIRMS. Copy `.env.example` to `.env` and
fill them in. Everything else (Open-Meteo forecast, ERA5 archive, CAMS chemistry) is
keyless. Without the keys the system still runs and reports which stages could not.

```bash
pip install -r requirements.txt
python -m pytest tests/ -q                      # 76 offline tests, no network

# Data. The recent panel takes about 45 minutes, the historical one about 20. Both
# cache to parquet, and the raw observation archive caches separately, so a failed
# assembly no longer costs another download.
python scripts/build_dataset.py --start 2025-02-01 --end 2026-08-31     --stations 40 --name train_panel
python scripts/build_dataset.py --start 2020-10-01 --end 2022-03-31     --stations 20 --name winters_panel --no-chem

# Everything else, in dependency order: combine, train, quantiles, LOSO, DSS.
bash scripts/run_all.sh

uvicorn api.main:app --port 8100                # then open http://127.0.0.1:8100
```

Individual experiments:

| script | question it answers |
|---|---|
| `ozone_sensitivity.py` | what would ozone be if the aerosol halved? |
| `plume_calibrate.py` | which vertical treatment matches the MoES DSS? |
| `photolysis_ablation.py` | does explicit photolysis improve the forecast? |
| `loso.py` | does it work where there is no instrument? |
| `case_study.py` | replay a past burning episode |

The dashboard is served by the API itself at `/`, so one process gives you both:
open <http://127.0.0.1:8100> once uvicorn is up.

### Running it live, without building anything

The trained boosters are not in this repository (they are 43 MB of XGBoost JSON and
they are reproducible), so a fresh clone has no models. To see the interface against
real data immediately, serve the committed snapshot instead:

```bash
pip install -r requirements.txt
VAYUCHAKRA_SNAPSHOT=1 uvicorn api.main:app --port 8100    # then open localhost:8100
```

That is exactly what the hosted instance does.

---

## Deployment

One service on Render's free tier, serving both the API and the dashboard it drives.

| | |
|---|---|
| URL | <https://vayuchakra.onrender.com> |
| Config | [`render.yaml`](render.yaml) |
| Mode | `VAYUCHAKRA_SNAPSHOT=1`, replaying [`data/snapshot/`](data/snapshot/) |
| Memory | about 130 MB resident against a 512 MB limit |
| Cold start | Render spins a free instance down after 15 minutes idle; the next request pays the wake-up, typically well under a minute. Not measured here, so treat it as Render's documented behaviour rather than a benchmark. |
| Secrets | `OPENAQ_API_KEY` and `FIRMS_MAP_KEY` are set in Render, never in git |

Three decisions are worth stating, because each of them was learned by getting it
wrong first.

**No `healthCheckPath`.** With one configured on a free service, Render's edge
intermittently dropped the instance from routing: 20 to 37 percent of requests returned
404 with `x-render-routing: no-server`, and those never reached uvicorn, so the
application log showed only the successes and looked perfectly healthy. Clearing it
took the failure rate to zero.

**One service, not two.** Two free services cost roughly 1,440 instance-hours a month
against a 750-hour allowance. Mounting the dashboard on the API process halves that and
removes the cross-origin hop.

**Snapshot rather than a coarser grid.** The obvious way to fit a 512 MB tier is to
shrink the domain. Measured, that does not work:

| Delhi cells | rows | peak RSS |
|---|---|---|
| 420 (2.8 km) | 211,680 | 1,083 MB |
| 182 (4.4 km) | 91,728 | 701 MB |

A line through those two points gives a fixed cost of about 283 MB before a single cell
is forecast, on top of a 126 MB floor for Python, pandas, XGBoost and the boosters. Even
a grid coarse enough to be useless would not have fit, so coarsening the domain would
have cost real resolution and bought nothing. Serving a full-resolution bundle keeps
everything the model actually knows and gives up only the clock.

**The bundle refreshes itself, so the deployment is no longer stale.** The constraint is
that the *web service* has 512 MB. Nothing required the pipeline to run on the web
service. [`.github/workflows/refresh-snapshot.yml`](.github/workflows/refresh-snapshot.yml)
runs it on a GitHub-hosted runner instead, which has 16 GB against a measured 1.1 GB
peak, writes the bundle, and commits it; Render auto-deploys on push. Public
repositories get unlimited Actions minutes, so a six-hourly refresh costs nothing.

That is not an approximation of real-time operation. No operational forecast system
re-solves its physics when someone loads a page: NWP runs on a cycle and serves the most
recent cycle, and a scheduled refresh is that same arrangement. What remains is that a
free instance sleeps after 15 minutes idle, so the first request after a quiet period is
slow. That is a cold start, not a stale forecast, and the two should not be confused.

The workflow refuses to commit a bundle whose manifest contains a failed route, a
suspiciously small payload, or a missing required one. Replacing a stale-but-correct
forecast with a broken one is strictly worse than doing nothing.

### Which commits redeploy

Every push to `main` used to build and deploy, and the deploy is the risky half: on
5 Sep the zero-downtime swap stalled on the 512 MB instance, sat for eighteen minutes
and timed out, even though the new process had already bound `$PORT` and answered
Render's own probe with a 200. The build had succeeded; only the handover failed.

So `render.yaml` now carries a build filter. A commit that touches only `README.md`,
`DECISIONS.md`, `DESIGN.md`, `docs/report/**`, `docs/shots/**`, `tests/**`,
`scripts/**` or `.github/**` does not deploy, because none of it is read by the running
container. `docs/VayuChakra-Report.pdf` is **not** on that list: the dashboard links it
and it is served from the image.

`data/snapshot/**` is deliberately not on the list either. The bundle is baked into the
image and read off disk at import, so a snapshot commit has to deploy or the six-hourly
refresh never reaches anyone. Filtering it would leave the schedule running and the site
frozen, which is a worse failure than the deploys it would save. Removing those deploys
needs the service to fetch the bundle at runtime instead, which is a different change.

Two routes are expected to be **retained** rather than refreshed on every run.
`/dss` and `/scenario` read the MoES DSS workbook, which is third-party research output
we cite and deliberately do not redistribute, so it exists on a developer machine and
never on a runner. Those routes answer 503 there by design; the exporter keeps the last
good capture, records it as retained with its age, and the service goes on serving it.
The nine routes carrying the forecast itself must be freshly captured, because a retained
forecast is exactly the staleness this workflow exists to remove.

To refresh by hand instead:

```bash
uvicorn api.main:app --port 8100                 # live, full resolution
python scripts/export_snapshot.py                # 20 routes -> data/snapshot/
git commit -am "Refresh snapshot" && git push    # autoDeploy picks it up
```

---

## Where this is still weak

The gaps are listed because a reviewer will find them anyway, and finding them first is
the only version of this that is worth anything.

| gap | status |
|---|---|
| **We do not run a chemical transport model** | Structural. WRF-Chem needs an HPC cluster and a district emission inventory we do not have. We consume CAMS instead and call it a surrogate. |
| **No VOC chemistry** | Delhi ozone is VOC-limited and we have no VOC measurements. TROPOMI HCHO/NO₂ could give a regime map (threshold FNR ≈ 3.1) but needs NetCDF orbit processing. |
| **Single layer** | No vertical discretisation. The largest remaining simplification. |
| **PM2.5 winter skill** | Was the weakest number in the project (+4.5% over persistence at 24 h). Four winters of training take it to +19.2% and r² from 0.30 to 0.50. Still the hardest of the four pollutants. |
| **Six winters do not fit on the development machine** | Measured, not assumed. The 2018 to 2022 panel at 40 stations is 1.22 million rows by 130 columns, about 1.4 GB in float32 before pandas takes a working copy. The machine has **3.8 GB of RAM and 150 MB physically available**, so assembly failed on an allocation of 3 MB. The historical panel was cut to two winters at 20 stations, giving **four winters in total** and 571,037 rows, which is what fits. More winters need more RAM, not more code. |
| **Ozone pays for the multi-winter panel** | The combined panel cannot carry CAMS, so the ozone heads lose the chemistry prior and their daily aerosol optical depth, and give up about four points against persistence. Both configurations are trained and reported rather than blended. |
| **The training panel has no pressure levels** | The ERA5 archive path returns surface fields only, so `inversion_strength_k` in kelvin is all-NaN in training and the heads use the surface-derived stability indices instead. The forecast path *does* return 950, 925 and 850 hPa, which is why the Vertical view can draw a real cross-section that the training data never saw. That asymmetry is stamped into every model's metadata as `inversion=surface`. |
| **Plume validated only at daily resolution** | The DSS attribution is daily, so it cannot discriminate the vertical treatments on their behaviour through the night. |
| **No operational run cycle** | The API caches for an hour but nothing schedules a refresh. |
| **The interval is slightly narrow** | The 80% prediction interval contains the truth 75.6% of the time, up from 66.7% on one winter, and the validator now calls it well calibrated. Still narrow, and the residual gap is the same cause in smaller form. |

---

## Design decisions

Every non-obvious choice, the measurement behind it, and what would reverse it is
logged in [DECISIONS.md](DECISIONS.md), including the bugs found along the way and how
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
- **The DSS comparison is not like-for-like**: reanalysis versus operational forecast.
- **Spatial resolution is 6 km, not 2.8 km.** The display grid is finer than the inputs,
  so predicted fields are smoothed to the resolution the drivers actually carry. Without
  it the map rendered tree-leaf quantisation as though it were a pollution gradient.
