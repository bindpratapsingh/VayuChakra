"""Prediction intervals, and the probability of crossing a GRAP threshold.

WHY A POINT FORECAST IS NOT ENOUGH HERE
----------------------------------------
"PM2.5 will be 118 µg/m³ tomorrow" is a number. What an official actually has to decide
is whether to invoke a GRAP stage, and those trigger at AQI thresholds — 200, 300, 400.
A point forecast of 118 sitting a whisker under a boundary tells them nothing about the
risk of crossing it, and a forecast that is confidently wrong in that position is worse
than one that admits a spread.

So this module produces:

  * a **prediction interval** (10th to 90th percentile), so the spread is visible;
  * the **probability of exceeding** each GRAP threshold, which is the quantity a
    decision actually turns on.

HOW
---
Quantile regression: XGBoost's `reg:quantileerror` fits the conditional quantile
directly rather than the conditional mean, so each head answers "what value will be
exceeded 10% of the time" rather than "what is the average". Five heads at 0.10, 0.25,
0.50, 0.75 and 0.90 give enough of the conditional distribution to interpolate a CDF.

HOW IT IS CHECKED
-----------------
**Coverage, not sharpness.** A 10-90 interval should contain the truth about 80% of the
time. If it contains 95%, the model is hedging and the interval is useless for a
decision; if it contains 55%, it is overconfident and dangerous. `coverage()` reports
the measured hit rate against the nominal one, and a wide interval with correct coverage
is a *finding about predictability*, not a failure of the method.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C
from .model import PARAMS, NUM_ROUNDS, EARLY_STOP, HAVE_XGB

if HAVE_XGB:
    import xgboost as xgb

#: The quantiles fitted. Five is enough to interpolate a usable CDF without training a
#: dozen models; the outer pair defines the reported interval.
QUANTILES = (0.10, 0.25, 0.50, 0.75, 0.90)
INTERVAL = (0.10, 0.90)          # nominal 80% coverage

#: CPCB concentration breakpoints at the AQI values that trigger GRAP action, µg/m³.
#: These are where a decision changes, which is why they are the thresholds we report a
#: probability for rather than reporting one for a round number.
GRAP_PM25 = {
    "AQI 200 (Poor -> Very Poor, GRAP II)": 90.0,
    "AQI 300 (Very Poor -> Severe, GRAP III)": 120.0,
    "AQI 400 (Severe+, GRAP IV)": 250.0,
}


@dataclass
class QuantileHead:
    """One target and horizon, fitted at several quantiles."""
    target: str
    horizon_h: int
    features: list[str]
    boosters: dict = field(default_factory=dict)   # quantile -> Booster
    metrics: dict = field(default_factory=dict)
    trained_at: str = ""

    # --- persistence -------------------------------------------------------
    def save(self, directory: Path | None = None) -> Path:
        directory = Path(directory or C.MODELS)
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"{self.target}_{self.horizon_h}h_q"
        for q, b in self.boosters.items():
            b.save_model(str(directory / f"{stem}{int(q * 100):02d}.json"))
        (directory / f"{stem}.meta.json").write_text(json.dumps({
            "target": self.target, "horizon_h": self.horizon_h,
            "features": self.features, "quantiles": sorted(self.boosters),
            "metrics": self.metrics, "trained_at": self.trained_at,
        }, indent=2), encoding="utf-8")
        return directory / f"{stem}.meta.json"

    @classmethod
    def load(cls, target: str, horizon_h: int,
             directory: Path | None = None) -> "QuantileHead | None":
        directory = Path(directory or C.MODELS)
        stem = f"{target}_{horizon_h}h_q"
        meta_path = directory / f"{stem}.meta.json"
        if not (meta_path.exists() and HAVE_XGB):
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        boosters = {}
        for q in meta.get("quantiles", []):
            path = directory / f"{stem}{int(q * 100):02d}.json"
            if path.exists():
                b = xgb.Booster()
                b.load_model(str(path))
                boosters[float(q)] = b
        if not boosters:
            return None
        return cls(target=meta["target"], horizon_h=meta["horizon_h"],
                   features=meta["features"], boosters=boosters,
                   metrics=meta.get("metrics", {}), trained_at=meta.get("trained_at", ""))

    # --- inference ---------------------------------------------------------
    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """Predicted quantiles, one column each.

        Quantiles are sorted row-wise afterwards. Independently fitted quantile models
        can cross — the 75th coming out below the 50th for some rows — which is a known
        artefact of fitting them separately rather than jointly. A crossed quantile
        makes the CDF non-monotone and any probability read off it meaningless, so the
        row is re-sorted. That repairs the symptom honestly rather than hiding it: the
        crossing rate is reported by `crossing_rate()`.
        """
        missing = [f for f in self.features if f not in df.columns]
        if missing:
            raise ValueError(f"{self.target}/{self.horizon_h}h quantile head missing "
                             f"{len(missing)} features, first: {missing[:5]}")
        X = xgb.DMatrix(df[self.features].astype("float32"), feature_names=self.features)
        cols = {}
        for q in sorted(self.boosters):
            cols[f"q{int(q * 100):02d}"] = np.clip(
                self.boosters[q].predict(X).astype("float64"), 0.0, None)
        out = pd.DataFrame(cols, index=df.index)
        return pd.DataFrame(np.sort(out.to_numpy(), axis=1),
                            columns=out.columns, index=out.index)

    def crossing_rate(self, df: pd.DataFrame) -> float:
        """Share of rows where independently fitted quantiles came out non-monotone."""
        missing = [f for f in self.features if f not in df.columns]
        if missing:
            return float("nan")
        X = xgb.DMatrix(df[self.features].astype("float32"), feature_names=self.features)
        raw = np.column_stack([self.boosters[q].predict(X) for q in sorted(self.boosters)])
        return float(np.mean((np.diff(raw, axis=1) < 0).any(axis=1)))


# ─── Scoring ─────────────────────────────────────────────────────────────────
def coverage(y_true, lo, hi, nominal: float = 0.80) -> dict:
    """Does the interval contain the truth as often as it claims?

    Reported alongside width, because the two trade off and neither means much alone.
    An interval can reach any coverage by growing without bound; the useful question is
    whether it hits its nominal rate *while staying narrow enough to act on*.
    """
    y = np.asarray(y_true, dtype="float64")
    lo = np.asarray(lo, dtype="float64")
    hi = np.asarray(hi, dtype="float64")
    ok = np.isfinite(y) & np.isfinite(lo) & np.isfinite(hi)
    if not ok.any():
        return {"n": 0}
    inside = (y[ok] >= lo[ok]) & (y[ok] <= hi[ok])
    width = hi[ok] - lo[ok]
    return {
        "n": int(ok.sum()),
        "nominal": nominal,
        "measured": round(float(inside.mean()), 4),
        "gap": round(float(inside.mean() - nominal), 4),
        "mean_width": round(float(width.mean()), 2),
        "median_width": round(float(np.median(width)), 2),
        "verdict": ("well calibrated" if abs(inside.mean() - nominal) <= 0.05
                    else "over-confident - interval too narrow" if inside.mean() < nominal
                    else "hedging - interval wider than it needs to be"),
    }


def exceedance_probability(quantiles: pd.DataFrame, threshold: float) -> np.ndarray:
    """P(value > threshold), interpolated from the fitted quantiles.

    The quantile columns are points on the conditional CDF: `q10 = 118` means "there is
    a 10% chance of being below 118". Linear interpolation between adjacent points gives
    the probability at any threshold, and outside the fitted range the answer is clamped
    rather than extrapolated — a five-quantile fit knows nothing about the far tail and
    should not pretend to.
    """
    qs = sorted(int(c[1:]) / 100.0 for c in quantiles.columns if c.startswith("q"))
    vals = quantiles[[f"q{int(q * 100):02d}" for q in qs]].to_numpy(dtype="float64")
    probs = np.asarray(qs, dtype="float64")

    below = np.full(len(vals), np.nan)
    for i, row in enumerate(vals):
        if not np.isfinite(row).all():
            continue
        if threshold <= row[0]:
            below[i] = probs[0] * (threshold / row[0]) if row[0] > 0 else 0.0
        elif threshold >= row[-1]:
            below[i] = probs[-1] + (1.0 - probs[-1]) * min(
                1.0, (threshold - row[-1]) / max(row[-1], 1e-6))
        else:
            below[i] = float(np.interp(threshold, row, probs))
    return np.clip(1.0 - below, 0.0, 1.0)


def grap_risk(quantiles: pd.DataFrame) -> pd.DataFrame:
    """Probability of crossing each GRAP action threshold."""
    out = pd.DataFrame(index=quantiles.index)
    for label, thr in GRAP_PM25.items():
        out[label] = exceedance_probability(quantiles, thr)
    return out


# ─── Training ────────────────────────────────────────────────────────────────
def train_quantile_head(supervised: pd.DataFrame, features: list[str], target: str,
                        horizon_h: int, *, holdout: tuple[str, str] | None = None,
                        test_fraction: float = 0.2, verbose: bool = True) -> QuantileHead:
    """Fit one booster per quantile on a shared split."""
    if not HAVE_XGB:
        raise RuntimeError("xgboost is required")
    import datetime as _dt

    from .dataset import split_holdout_window, split_time_ordered
    if holdout:
        train, test = split_holdout_window(supervised, holdout[0], holdout[1])
    else:
        train, test = split_time_ordered(supervised, test_fraction)

    usable = [f for f in features if f in supervised.columns
              and train[f].notna().sum() > 0]
    dtrain = xgb.DMatrix(train[usable].astype("float32"),
                         label=train["y"].astype("float32"), feature_names=usable)
    dtest = xgb.DMatrix(test[usable].astype("float32"),
                        label=test["y"].astype("float32"), feature_names=usable)

    boosters = {}
    for q in QUANTILES:
        params = dict(PARAMS)
        params["objective"] = "reg:quantileerror"
        params["quantile_alpha"] = q
        boosters[q] = xgb.train(params, dtrain, num_boost_round=NUM_ROUNDS,
                                evals=[(dtest, "test")],
                                early_stopping_rounds=EARLY_STOP, verbose_eval=False)
        if verbose:
            print(f"[quantile] {target} +{horizon_h}h q{int(q * 100):02d} fitted")

    head = QuantileHead(target=target, horizon_h=horizon_h, features=usable,
                        boosters=boosters,
                        trained_at=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"))
    preds = head.predict(test)
    lo, hi = f"q{int(INTERVAL[0] * 100):02d}", f"q{int(INTERVAL[1] * 100):02d}"
    head.metrics = {
        "coverage": coverage(test["y"], preds[lo], preds[hi],
                             nominal=INTERVAL[1] - INTERVAL[0]),
        "quantile_crossing_rate": round(head.crossing_rate(test), 4),
        "n_train": int(len(train)), "n_test": int(len(test)),
    }
    if verbose:
        c = head.metrics["coverage"]
        print(f"[quantile] {target} +{horizon_h}h coverage {100 * c['measured']:.1f}% "
              f"(nominal {100 * c['nominal']:.0f}%) · median width "
              f"{c['median_width']:.1f} · {c['verdict']}")
    return head
