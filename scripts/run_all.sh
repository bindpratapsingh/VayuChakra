#!/usr/bin/env bash
# Full re-validation on the multi-winter panel, in dependency order.
#
# Run sequentially and never in parallel: two of these hold a 500k-row frame with ~190
# columns, and running them together has already killed one training run with an
# out-of-memory error.
#
#   1. combine   join the 2018-2022 winters onto the 2025-2026 panel
#   2. train     production heads, holding out the most recent winter
#   3. train     a SECOND set holding out 2021-22, so the DSS comparison stays
#                out of sample - the multi-winter panel contains the DSS window,
#                and scoring against it with a model that trained on it would be
#                measuring memorisation
#   4. quantiles prediction intervals and GRAP exceedance probabilities
#   5. loso      does it work where there is no instrument
#   6. validate  DSS head-to-head using the held-out model from step 3
set -u
cd "$(dirname "$0")/.."
log() { echo ""; echo "=== $* ==="; }

log "1/6 combine panels"
python -u scripts/combine_panels.py --panels winters_panel,train_panel --out combined_panel

log "2/6 train production heads (hold out winter 2025-26)"
python -u scripts/train.py --panel combined_panel --targets pm25,o3,pm10,no2 \
  --horizons 24,48,72 --holdout-start 2025-11-01 --holdout-end 2026-02-28 \
  --out metrics_multiwinter.json

log "3/6 train DSS-holdout heads (hold out winter 2021-22)"
python -u scripts/train.py --panel combined_panel --targets pm25 --horizons 24,48,72 \
  --holdout-start 2021-10-01 --holdout-end 2022-03-31 \
  --model-dir models/dss_holdout --out metrics_dss_holdout.json

log "4/6 prediction intervals and GRAP risk"
python -u scripts/train_uncertainty.py --panel combined_panel --targets pm25 \
  --horizons 24 --holdout-start 2025-11-01 --holdout-end 2026-02-28 \
  --out uncertainty_pm25_24h.json

log "5/6 leave-one-station-out"
python -u scripts/loso.py --panel combined_panel --targets pm25,o3 --horizon 24 \
  --stations 10 --out loso.json

log "6/6 DSS head-to-head, out of sample"
python -u scripts/validate.py --skip-ablation --dss-model-dir models/dss_holdout

log "done"
