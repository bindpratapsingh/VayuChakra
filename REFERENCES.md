# References and attribution

Everything VayuChakra is built on, and what each thing is actually used for.

This is a disclosure document, so it errs toward listing too much rather than too
little. Where a source supplied a **number that appears in our results**, that is stated
explicitly, because those are the ones a reviewer should be able to check.

A note on precision: journal, volume and page are given for every paper. Direct links
are given only where we are confident of the canonical URL. Where we are not, the
publisher is named and the citation is left resolvable by search rather than risking a
link that does not go where it claims.

---

## 1. Live data sources

These are called at runtime. Every one is free, and the two that need a key are read
with keys held as environment variables and never committed.

| Source | What we take from it | Access | Link |
|---|---|---|---|
| **OpenAQ** | Ground truth. Hourly PM2.5, PM10, NO₂, O₃, SO₂ and CO from 159 CPCB and CAAQM stations across the NCR. Both the live `v3` API and the public S3 archive. | API key, free | [openaq.org](https://openaq.org) · [api.openaq.org/v3](https://api.openaq.org/v3) · [archive](https://openaq-data-archive.s3.amazonaws.com) |
| **Open-Meteo (forecast)** | The driving meteorology: temperature, wind at 10 m and 100 m, boundary layer height, radiation, humidity, pressure, and the 1000/950/925/850 hPa profile our inversion detection needs. | Keyless | [open-meteo.com](https://open-meteo.com) |
| **Open-Meteo (historical forecast)** | Archived **forecast** runs, used so the comparison against the MoES DSS is driven by forecast meteorology rather than reanalysis. | Keyless | [historical-forecast-api.open-meteo.com](https://historical-forecast-api.open-meteo.com) |
| **Open-Meteo (ERA5 archive)** | Reanalysis meteorology for building the multi-winter training panel. | Keyless | [archive-api.open-meteo.com](https://archive-api.open-meteo.com) |
| **Copernicus CAMS**, via Open-Meteo air-quality | The chemistry prior and, critically, **aerosol optical depth**, which is the variable the whole radiative feedback runs on. Also dust, separately from combustion aerosol. | Keyless via Open-Meteo | [atmosphere.copernicus.eu](https://atmosphere.copernicus.eu) · [air-quality-api.open-meteo.com](https://air-quality-api.open-meteo.com) |
| **NASA FIRMS** | Satellite fire detections (VIIRS S-NPP, VIIRS NOAA-20, MODIS) with fire radiative power, which is what the stubble plume model releases as puffs. | Map key, free | [firms.modaps.eosdis.nasa.gov](https://firms.modaps.eosdis.nasa.gov) |

**ERA5** underlies the Open-Meteo archive and is produced by ECMWF through the Copernicus
Climate Change Service: [cds.climate.copernicus.eu](https://cds.climate.copernicus.eu).

---

## 2. Third-party model output we consume or compare against

| Source | Role | Attribution |
|---|---|---|
| **CAMS global forecast (ECMWF IFS-COMPO)** | An operational **coupled** meteorology and chemistry model with online aerosol. This is how the project answers the problem statement's "or similar open-source coupled frameworks": we consume one that is already running rather than running our own. | Copernicus Atmosphere Monitoring Service, ECMWF |
| **MoES / IITM WRF-Chem Decision Support System** | Used two ways: its daily stubble-burning attribution is the **calibration target** for our plume model, and its operational PM2.5 forecasts are the **comparison** in our validation. Published in JAMES. | Ministry of Earth Sciences and IITM Pune |

> **We do not redistribute the DSS workbook.** It is third-party research output. It is
> read locally, cited, and its numbers are quoted as theirs. It is deliberately absent
> from this repository, which is why `/dss` and `/scenario` return 503 in CI and the
> snapshot retains the last good local capture instead.

---

## 3. Scientific literature we took numbers from

Listed by what it supplied. These are the citations behind values that appear in our
output, so they are the ones worth checking.

### 3.1 Aerosol, radiation and the feedback loop

- **Xing, J. et al. (2022).** *Impacts of aerosol–photolysis interaction and
  aerosol–radiation feedback on surface-layer ozone in North China.*
  **Atmos. Chem. Phys. 22, 4101.**
  [acp.copernicus.org/articles/22/4101/2022](https://acp.copernicus.org/articles/22/4101/2022/)
  → **Used for:** the separation of the two aerosol pathways. This is the source of our
  claim that the photolysis route moves ozone by 10 to 12 percent against 1 to 3 percent
  for the radiation route, which is why we built the photolysis pathway first. Also the
  wind-to-PBL response ratio (wind falls 1.6 to 4.3 percent while PBL falls 13 to 21
  percent) that sets `WIND_RESPONSE_RATIO`.

- **Photolysis frequencies and ozone production in Beijing, 2012–2015.**
  **Atmos. Chem. Phys. 19, 9413 (2019).**
  [acp.copernicus.org/articles/19/9413/2019](https://acp.copernicus.org/articles/19/9413/2019/)
  → **Used for:** the functional form of photolysis attenuation as a function of aerosol
  optical depth and solar zenith angle, and the reference seasonal J(NO₂) reductions of
  roughly 24 percent in summer and 30 percent in winter that our unfitted implementation
  is checked against.

- **Master Chemical Mechanism (MCM) v3.3.1**, University of York.
  [mcm.york.ac.uk](https://mcm.york.ac.uk/)
  → **Used for:** the clear-sky photolysis parameterisation
  `J = l·cos(SZA)^m·exp(−n·sec(SZA))` and its coefficients for J(NO₂) and J(O¹D). These
  are used directly in `vayuchakra/photolysis.py`.

- **Kasten, F. and Young, A. T. (1989).** *Revised optical air mass tables and
  approximation formula.* **Applied Optics 28, 4735.**
  → **Used for:** relative optical airmass. Plain `1/cos(z)` diverges at the horizon,
  where a large share of Delhi's winter daylight actually sits.

### 3.2 Delhi ozone chemistry

- **Nelson, B. S. et al. (2021).** *Avoiding high ozone pollution in Delhi, India.*
  **Faraday Discussions 226**, Royal Society of Chemistry. Part of the APHH-India
  programme. Publisher: [pubs.rsc.org](https://pubs.rsc.org)
  → **Used for:** the finding that Delhi's wintertime ozone production is both VOC-limited
  and strongly radiation-limited, and the published figure that a **50 percent reduction
  in aerosol optical depth raises ozone by about 25 percent**. Our model returns +12.79
  percent for the same perturbation, and that comparison is our strongest single
  validation because the number was never used in fitting.

- **APHH-India** (Atmospheric Pollution and Human Health in an Indian Megacity), NERC and
  MoES. → **Used for:** the campaign observations of elevated smoke layers over Delhi at
  500 to 1,500 m persisting overnight, which motivated the two-layer slab model.

### 3.3 Boundary layer and the two-layer model

- **Batchvarova, E. and Gryning, S.-E. (1991, 1994).** Slab-model formulations for
  boundary layer height, combining convective and mechanical growth.
  → **Used for:** the entrainment closure and the parameter values A = 0.20, B = 2.50,
  C = 8.00 in `vayuchakra/twolayer.py`, and the entrainment flux ratio β ≈ 0.2.

- **Vilà-Guerau de Arellano, J. et al.** — the **CLASS** model (Chemistry Land-surface
  Atmosphere Soil Slab). [classmodel.github.io](https://classmodel.github.io/)
  → **Used for:** the mixed-layer / residual-layer formulation our two-layer scheme
  follows, including the volume-weighted evening transition.

- **Tenekes, H. (1973).** Foundational mixed-layer model work that the slab family
  derives from.

### 3.4 Aerosol optics over the Indo-Gangetic Plain

Everything in this group feeds the bimodal optical depth model (decision D-062).

- **AERONET** (AErosol RObotic NETwork), NASA. [aeronet.gsfc.nasa.gov](https://aeronet.gsfc.nasa.gov/)
  → **Used for:** the seasonal fine-mode fraction climatology over Delhi and Kanpur that
  our two pre-factors were tuned to reproduce: fine mode carrying 50 to 80 percent of
  extinction in winter and 8 to 25 percent during pre-monsoon dust.

- **MISR** (Multi-angle Imaging SpectroRadiometer), NASA.
  → **Used for:** corroborating fine and coarse aerosol partitioning over the region.

- Regional literature on **mass extinction efficiency, single-scattering albedo and
  asymmetry parameter** for fine combustion aerosol and coarse mineral dust at 550 nm,
  and on **hygroscopic growth** over the IGP. These supplied every constant in the
  `Bimodal aerosol optics` block of `vayuchakra/config.py`: MEE 4.4 against 0.85 m²/g,
  SSA 0.855 against 0.95, asymmetry 0.625 against 0.725, and the fine-mode growth
  exponent γ of 0.40 to 0.60 against essentially unity for dust.

- **Assessing CAMS reanalysis AOD over India.** *Environmental Science and Pollution
  Research* (2025).
  → **Used for:** the validation of CAMS aerosol optical depth over the Indo-Gangetic
  Plain, mean bias +0.037 and r = 0.77, which is why we treat CAMS AOD as a trustworthy
  optical baseline while treating its surface concentrations as biased.

### 3.5 NOx chemistry under haze

- Literature on **heterogeneous N₂O₅ hydrolysis and direct NO₂ uptake** on aerosol
  surfaces under severe winter haze.
  → **Used for:** the correction of the photolytic loss share φ from 0.7 (clear-sky
  mid-latitude urban) to 0.48 (Delhi winter daytime), where heterogeneous sinks take 40
  to 50 percent of NO₂ loss. This correction *reduced* our headline NO₂ number from 20.2
  to 16.3 percent, and we applied it anyway.

### 3.6 Colour vision, for the interface

- **Viénot, F., Brettel, H. and Mollon, J. D.** — dichromat simulation in LMS space.
  → **Used for:** simulating protanopia and deuteranopia when choosing the chart series
  palette, so the three series remain distinguishable without colour vision. Documented
  with measured ΔE separations in `DESIGN.md` section 12.

---

## 4. Standards and official definitions

| Standard | Use | Source |
|---|---|---|
| **CPCB National Air Quality Index** | The breakpoint table, reproduced exactly and never recoloured or approximated. PM2.5 and ozone are predicted separately and combined into the index by the published formula rather than predicted as an index. | Central Pollution Control Board, India — [cpcb.nic.in](https://cpcb.nic.in) |
| **GRAP** (Graded Response Action Plan) | The AQI 200 / 300 / 400 trigger thresholds that our probability forecasts are built around, mapped to PM2.5 concentrations through the CPCB table. | Commission for Air Quality Management, NCR |

---

## 5. Software

| Library | Role | Link |
|---|---|---|
| **XGBoost** | The 12 forecast heads and 5 quantile heads. Native Booster API. | [xgboost.readthedocs.io](https://xgboost.readthedocs.io) |
| **pandas**, **NumPy**, **SciPy** | Data handling, numerics, spatial trees for field smoothing. | [pandas.pydata.org](https://pandas.pydata.org) · [numpy.org](https://numpy.org) · [scipy.org](https://scipy.org) |
| **PyArrow** | Parquet storage for the training panels. | [arrow.apache.org](https://arrow.apache.org) |
| **FastAPI** and **Uvicorn** | The API, which also serves the dashboard from the same origin. | [fastapi.tiangolo.com](https://fastapi.tiangolo.com) · [uvicorn.org](https://www.uvicorn.org) |
| **openpyxl** | Reading the MoES DSS workbook locally. | [openpyxl.readthedocs.io](https://openpyxl.readthedocs.io) |
| **pytest** | The 94-test suite, including the literature gates. | [pytest.org](https://docs.pytest.org) |
| **Leaflet 1.9.4** | The maps on the dashboard. | [leafletjs.com](https://leafletjs.com) |
| **Playwright** | Rendering the report PDF and taking dashboard screenshots. Development only. | [playwright.dev](https://playwright.dev) |

Deliberately **not** used, and why, is recorded in `requirements.txt`: scikit-learn,
requests and python-dotenv were all avoidable.

### Map tiles

**Esri World Light Gray Canvas**, base and reference layers, served keyless from
`server.arcgisonline.com`. Attribution "Tiles © Esri" is displayed on every map, as the
terms require. [esri.com](https://www.esri.com)

---

## 6. Infrastructure

| Service | Role |
|---|---|
| **Render** | Hosts the web service on the free tier. [render.com](https://render.com) |
| **GitHub Actions** | Runs the full pipeline every six hours on a 16 GB runner, because the 512 MB web tier cannot. [github.com/features/actions](https://github.com/features/actions) |

---

## 7. Research reports commissioned for this project

Five deep-research reports were produced during development and are kept in
[`docs/Research/`](docs/Research/). They are secondary sources: they synthesise published
literature, and **their own bibliographies contain 178 further citations** to the primary
papers, which is where a reader should go to verify any specific number.

| Report | What it settled | Where it landed |
|---|---|---|
| *Aerosol Radiative Feedback Delhi* | The bimodal optical depth model, mode-specific optics, hygroscopic growth, and the NO₂ photolytic share | D-062, `config.py`, `feedback.py` |
| *Air Quality Box Model Upgrade* | The two-layer slab formulation, entrainment closure, and morning fumigation timing | D-063, `twolayer.py` |
| *Delhi Chemical Transport Modeling* | That WRF-Chem, CMAQ and CAMx are all infeasible under our compute, with measured figures, and what the viable alternative is | The honest answer on clause 1 |
| *Delhi Ozone FNR Integration Recipe* | How a satellite formaldehyde to NO₂ ratio could make ozone regime-aware | Roadmap, not yet built |
| *Air Quality Data Assimilation Strategies* | What assimilation is worth doing for a statistical surrogate | Roadmap, not yet built |

---

## 8. What we deliberately do not use or redistribute

Stated because a disclosure is incomplete without it.

- **The MoES DSS workbook** is never redistributed. Cited only.
- **SAFAR-Delhi** emissions inventory is restricted and requires an institutional request.
  We evaluated it and did not use it.
- **No proprietary or paid data source** is used anywhere in this project.
- **No scraped data.** Every source above is an official API, a public archive, or a
  published dataset accessed on its own terms.

---

## 9. Where our own numbers live

Every figure we publish is read from a file in this repository, not typed by hand.
`models/metrics_multiwinter.json`, `models/loso.json`, `models/validation.json`,
`models/ozone_sensitivity.json`, `models/plume_calibration_octnov.json`,
`models/uncertainty_pm25_24h.json` and `data/snapshot/coupling.json`.

`DECISIONS.md` records 63 decisions with the measurement behind each, including the
negative results.
