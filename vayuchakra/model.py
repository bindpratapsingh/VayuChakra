"""Forecast models — separate heads for PM2.5 and ozone.

WHY TWO MODELS AND NOT ONE
---------------------------
The problem statement names PM2.5 and ground-level ozone specifically, and they are not
two flavours of the same thing. PM2.5 accumulates when the atmosphere stops moving: it
peaks on still winter nights under a collapsed boundary layer. Ozone is manufactured by
sunlight acting on nitrogen oxides: it peaks on hot bright afternoons, and it *rises
when NOx falls*, because fresh nitric oxide destroys it. Their daily cycles are close to
opposite and their seasons are opposite too.

A single model predicting an AQI scalar has to average those two mechanisms into one set
of splits, and the summer ozone signal — a minority of the variance — loses. That is the
main scientific gap in the sibling AirGrid project, and it is closed here by simply
training two models.

WHAT IS BEING PREDICTED
-----------------------
Concentration, not index. AQI is a max-of-sub-indices over 24-hour windows: a
discontinuous, non-linear function of concentrations. Predicting it directly asks a
regressor to learn the shape of a lookup table on top of the atmospheric physics. We
predict the concentrations and apply the published CPCB formula afterwards, which is
both more accurate and auditable against the standard.

THE BASELINE THAT MATTERS
-------------------------
Persistence — "tomorrow looks like today". It is embarrassingly hard to beat at 24
hours, and the sibling project's 24 h model **lost to it by 4.2%**. Every score here is
reported against persistence, and a model that does not beat it is reported as not
beating it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C

try:
    import xgboost as xgb
    HAVE_XGB = True
except ImportError:                                     # pragma: no cover
    HAVE_XGB = False


#: Conservative defaults. Depth 6 with 400 rounds and early stopping is enough for a
#: few hundred thousand rows; going deeper mostly memorises individual episodes.
PARAMS = {
    "objective": "reg:squarederror",
    "max_depth": 6,
    "eta": 0.04,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 8,
    "reg_lambda": 1.5,
    "tree_method": "hist",
    "max_bin": 256,
    "seed": 42,
}
NUM_ROUNDS = 700
EARLY_STOP = 40


@dataclass
class Metrics:
    rmse: float
    mae: float
    bias: float
    r2: float
    n: int
    persistence_rmse: float = float("nan")
    improvement_pct: float = float("nan")

    def to_dict(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v)
                for k, v in asdict(self).items()}


def score(y_true, y_pred, persistence=None) -> Metrics:
    y = np.asarray(y_true, dtype="float64")
    p = np.asarray(y_pred, dtype="float64")
    ok = np.isfinite(y) & np.isfinite(p)
    y, p = y[ok], p[ok]
    if len(y) == 0:
        return Metrics(*( [float("nan")] * 4 ), 0)
    err = p - y
    rmse = float(np.sqrt(np.mean(err ** 2)))
    mae = float(np.mean(np.abs(err)))
    bias = float(np.mean(err))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(np.sum(err ** 2)) / ss_tot if ss_tot > 0 else float("nan")

    pr, imp = float("nan"), float("nan")
    if persistence is not None:
        q = np.asarray(persistence, dtype="float64")[ok]
        okq = np.isfinite(q)
        if okq.any():
            pr = float(np.sqrt(np.mean((q[okq] - y[okq]) ** 2)))
            imp = float(100.0 * (pr - rmse) / pr) if pr > 0 else float("nan")
    return Metrics(rmse, mae, bias, r2, int(len(y)), pr, imp)


@dataclass
class Head:
    """One trained model plus the contract it was trained under."""
    target: str
    horizon_h: int
    features: list[str]
    booster: object = None
    metrics: dict = field(default_factory=dict)
    n_train: int = 0
    trained_at: str = ""
    config_note: str = ""

    # --- persistence -------------------------------------------------------
    def save(self, directory: Path | None = None) -> Path:
        directory = Path(directory or C.MODELS)
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"{self.target}_{self.horizon_h}h"
        if self.booster is not None:
            self.booster.save_model(str(directory / f"{stem}.json"))
        meta = {"target": self.target, "horizon_h": self.horizon_h,
                "features": self.features, "metrics": self.metrics,
                "n_train": self.n_train, "trained_at": self.trained_at,
                "config_note": self.config_note}
        (directory / f"{stem}.meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return directory / f"{stem}.json"

    @classmethod
    def load(cls, target: str, horizon_h: int, directory: Path | None = None) -> "Head | None":
        directory = Path(directory or C.MODELS)
        stem = f"{target}_{horizon_h}h"
        model_path, meta_path = directory / f"{stem}.json", directory / f"{stem}.meta.json"
        if not (model_path.exists() and meta_path.exists() and HAVE_XGB):
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        booster = xgb.Booster()
        booster.load_model(str(model_path))
        return cls(target=meta["target"], horizon_h=meta["horizon_h"],
                   features=meta["features"], booster=booster,
                   metrics=meta.get("metrics", {}), n_train=meta.get("n_train", 0),
                   trained_at=meta.get("trained_at", ""),
                   config_note=meta.get("config_note", ""))

    # --- inference ---------------------------------------------------------
    def check_features(self, df: pd.DataFrame) -> dict:
        """Compare the frame against the training contract before predicting.

        Train/serve skew is the failure mode that does not announce itself: the model
        still returns numbers, they are just quietly wrong. Missing columns are fatal.
        A column that was entirely NaN in training but is populated now is reported as
        a warning, because the model cannot have learned to use it.
        """
        missing = [f for f in self.features if f not in df.columns]
        present = [f for f in self.features if f in df.columns]
        allnan = [f for f in present if df[f].notna().sum() == 0]
        return {"ok": not missing, "missing": missing, "all_nan_now": allnan,
                "n_expected": len(self.features), "n_present": len(present)}

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        if self.booster is None:
            raise RuntimeError(f"{self.target}/{self.horizon_h}h has no booster loaded")
        chk = self.check_features(df)
        if not chk["ok"]:
            raise ValueError(
                f"{self.target}/{self.horizon_h}h missing {len(chk['missing'])} trained "
                f"features, first few: {chk['missing'][:6]}")
        X = df[self.features].astype("float32")
        out = self.booster.predict(xgb.DMatrix(X, feature_names=self.features))
        # Concentrations cannot be negative. Clipping at zero rather than letting a
        # small negative through, because a negative PM2.5 propagates into the AQI
        # table as a nonsense sub-index.
        return np.clip(out.astype("float64"), 0.0, None)


def _persistence_column(df: pd.DataFrame, target: str) -> np.ndarray:
    """The naive forecast: the most recent observed value at prediction time."""
    for col in (f"{target}_lag_1h", target):
        if col in df.columns:
            return df[col].to_numpy(dtype="float64")
    return np.full(len(df), np.nan)


def train_head(
    supervised: pd.DataFrame,
    features: list[str],
    target: str,
    horizon_h: int,
    *,
    test_fraction: float = 0.2,
    config_note: str = "",
    holdout: tuple[str, str] | None = None,
    verbose: bool = True,
) -> Head:
    """Train one head, holding out either the most recent slice or a named window.

    `holdout=(start, end)` exists because the chronological split has a blind spot worth
    naming: on a panel running Feb 2025 to Aug 2026, its test set is May-August 2026 and
    contains **no winter at all**. Every score from it is a summer and monsoon score, and
    Delhi's defining pollution season goes unevaluated. Passing a winter window keeps the
    test strictly out of sample while measuring the season that matters.
    """
    if not HAVE_XGB:
        raise RuntimeError("xgboost is required to train")
    import datetime as _dt

    from .dataset import split_holdout_window, split_time_ordered
    if holdout:
        train, test = split_holdout_window(supervised, holdout[0], holdout[1])
    else:
        train, test = split_time_ordered(supervised, test_fraction)
    usable = [f for f in features if f in supervised.columns]

    # Drop features that are entirely missing in TRAINING. Keeping them would let the
    # contract advertise inputs the model provably never used, which is exactly the
    # confusion `check_features` exists to prevent.
    informative = [f for f in usable if train[f].notna().sum() > 0]
    dropped = sorted(set(usable) - set(informative))
    if dropped and verbose:
        print(f"[model] {target}/{horizon_h}h dropping {len(dropped)} all-NaN features"
              f"{': ' + ', '.join(dropped[:5]) if len(dropped) <= 5 else ''}")

    Xtr = train[informative].astype("float32")
    Xte = test[informative].astype("float32")
    ytr = train["y"].astype("float32")
    yte = test["y"].astype("float32")

    dtrain = xgb.DMatrix(Xtr, label=ytr, feature_names=informative)
    dtest = xgb.DMatrix(Xte, label=yte, feature_names=informative)
    booster = xgb.train(PARAMS, dtrain, num_boost_round=NUM_ROUNDS,
                        evals=[(dtest, "test")], early_stopping_rounds=EARLY_STOP,
                        verbose_eval=False)

    pred = booster.predict(dtest)
    m = score(yte, np.clip(pred, 0, None), _persistence_column(test, target))
    head = Head(target=target, horizon_h=horizon_h, features=informative,
                booster=booster, metrics=m.to_dict(), n_train=int(len(train)),
                trained_at=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                config_note=config_note)
    if verbose:
        print(f"[model] {target:5s} +{horizon_h:2d}h  RMSE {m.rmse:7.2f}  "
              f"persistence {m.persistence_rmse:7.2f}  "
              f"improvement {m.improvement_pct:+6.2f}%  r2 {m.r2:.3f}  n={m.n}")
    return head


def leave_one_station_out(
    supervised: pd.DataFrame,
    features: list[str],
    target: str,
    horizon_h: int,
    *,
    max_stations: int = 12,
    verbose: bool = True,
) -> dict:
    """Spatial generalisation: can the model predict a station it never saw?

    The chronological split answers "does it work next week"; this answers "does it
    work in a neighbourhood without a monitor", which is the whole point of producing a
    gridded forecast. Stations are sampled rather than exhausted because a full sweep
    over 130 stations is 130 trainings.
    """
    if not HAVE_XGB:
        return {"available": False}
    usable = [f for f in features if f in supervised.columns
              and supervised[f].notna().sum() > 0]
    counts = supervised["station_id"].value_counts()
    held_out = list(counts.index[:max_stations])

    rows = []
    for sid in held_out:
        tr = supervised[supervised["station_id"] != sid]
        te = supervised[supervised["station_id"] == sid]
        if len(te) < 50 or len(tr) < 500:
            continue
        dtr = xgb.DMatrix(tr[usable].astype("float32"), label=tr["y"].astype("float32"),
                          feature_names=usable)
        b = xgb.train(PARAMS, dtr, num_boost_round=250, verbose_eval=False)
        pred = np.clip(b.predict(xgb.DMatrix(te[usable].astype("float32"),
                                             feature_names=usable)), 0, None)
        m = score(te["y"], pred, _persistence_column(te, target))
        rows.append({"station_id": int(sid), **m.to_dict()})
        if verbose:
            print(f"[LOSO] station {sid:<8} RMSE {m.rmse:7.2f}  "
                  f"persistence {m.persistence_rmse:7.2f}  {m.improvement_pct:+6.2f}%")

    if not rows:
        return {"available": False}
    frame = pd.DataFrame(rows)
    return {"available": True, "stations": len(frame),
            "mean_rmse": round(float(frame["rmse"].mean()), 3),
            "mean_persistence_rmse": round(float(frame["persistence_rmse"].mean()), 3),
            "mean_improvement_pct": round(float(frame["improvement_pct"].mean()), 3),
            "per_station": rows}


def importance(head: Head, top: int = 25) -> list[tuple[str, float]]:
    """Gain-based feature importance — used to check the physics is being used."""
    if head.booster is None:
        return []
    gain = head.booster.get_score(importance_type="gain")
    return sorted(gain.items(), key=lambda kv: -kv[1])[:top]
