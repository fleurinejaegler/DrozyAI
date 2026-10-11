"""Gradient boosting baseline for the DrozyAI wearable model.

Reads the sliding-window feature table produced by
src.features.watch_features and trains a HistGradientBoostingClassifier
with 5-fold stratified cross-validation.

Note on validation choice:
    The original PDF plan called for leave-one-subject-out (LOSO) as
    the more rigorous evaluation. In practice, LOSO does not produce
    meaningful results on UL-DD because each subject contributes one
    awake session and one drowsy session, so the model cannot learn
    to generalize across subjects from a single pair of sessions.
    We follow the original UL-DD paper and use 5-fold stratified
    cross-validation instead. This is documented in the README.

    RMSSD is available only in windows with at least two valid IBI
    values (~69% of windows). Rows with NaN in any feature are dropped
    before training; this still leaves 11376 windows.

Metrics reported:
    AUC                    : ROC AUC on the held-out fold
    missed_drowsy_rate     : fraction of true drowsy windows predicted alert
    false_alarms_per_hour  : alert windows predicted drowsy, per hour

Saves per-window predicted probabilities (raw + calibrated) to
data/processed/baseline_scores.parquet for the fusion stage (Person 3).

Usage:
    python -m src.models.baseline
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import RobustScaler


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
FEATURE_COLUMNS = [
    "hr_mean",
    "rmssd",
    "temp_trend",
    "motion_var",
]

N_SPLITS = 5
STEP_SECONDS = 5
WINDOWS_PER_HOUR = 3600 // STEP_SECONDS  # 720
RANDOM_STATE = 42


# ----------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------
def missed_drowsy_rate(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Fraction of truly drowsy windows predicted alert."""
    drowsy = y_true == 1
    if drowsy.sum() == 0:
        return float("nan")
    missed = (y_pred[drowsy] == 0).sum()
    return float(missed) / float(drowsy.sum())


def false_alarms_per_hour(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """False alarms (alert predicted drowsy) per hour of driving."""
    alert = y_true == 0
    if alert.sum() == 0:
        return float("nan")
    false_alarms = (y_pred[alert] == 1).sum()
    hours = len(y_true) / WINDOWS_PER_HOUR
    if hours == 0:
        return float("nan")
    return float(false_alarms) / hours


# ----------------------------------------------------------------------
# Model pipeline
# ----------------------------------------------------------------------
def _build_pipeline() -> Pipeline:
    """RobustScaler + HistGradientBoostingClassifier."""
    return Pipeline(
        [
            ("scaler", RobustScaler()),
            (
                "clf",
                HistGradientBoostingClassifier(
                    max_iter=200,
                    learning_rate=0.05,
                    max_depth=None,
                    early_stopping=True,
                    validation_fraction=0.15,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


# ----------------------------------------------------------------------
# 5-fold cross-validation
# ----------------------------------------------------------------------
def train_5fold(
    features_df: pd.DataFrame,
    threshold: float = 0.5,
) -> tuple[pd.DataFrame, dict]:
    """Train and evaluate with 5-fold stratified cross-validation.

    Returns
    -------
    (predictions_df, summary)
    """
    # Drop rows with NaN in any feature
    clean = features_df.dropna(subset=FEATURE_COLUMNS).reset_index(drop=True)
    print(f"  {len(features_df)} windows total, {len(clean)} after dropna")

    X = clean[FEATURE_COLUMNS].to_numpy()
    y = clean["label"].to_numpy()

    skf = StratifiedKFold(
        n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE
    )

    all_preds = []
    aucs = []
    missed_rates = []
    fa_rates = []

    for fold, (train_idx, test_idx) in enumerate(skf.split(X, y), start=1):
        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]

        pipe = _build_pipeline()
        pipe.fit(X_train, y_train)

        proba = pipe.predict_proba(X_test)[:, 1]
        pred = (proba >= threshold).astype(int)

        auc = roc_auc_score(y_test, proba) if len(np.unique(y_test)) > 1 else float("nan")
        missed = missed_drowsy_rate(y_test, pred)
        fa = false_alarms_per_hour(y_test, pred)
        aucs.append(auc)
        missed_rates.append(missed)
        fa_rates.append(fa)

        print(
            f"  Fold {fold}: AUC={auc:.4f}  missed={missed:.3f}  "
            f"FA/h={fa:.1f}  (test n={len(y_test)})"
        )

        fold_df = clean.iloc[test_idx].copy()
        fold_df["proba"] = proba
        fold_df["pred"] = pred
        fold_df["fold"] = fold
        all_preds.append(fold_df)

    predictions = pd.concat(all_preds, ignore_index=True)

    # Calibrate probabilities with isotonic regression
    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(predictions["proba"].to_numpy(), predictions["label"].to_numpy())
    predictions["proba_calibrated"] = iso.predict(predictions["proba"].to_numpy())

    summary = {
        "auc_mean": float(np.nanmean(aucs)),
        "auc_std": float(np.nanstd(aucs)),
        "missed_drowsy_rate_mean": float(np.nanmean(missed_rates)),
        "false_alarms_per_hour_mean": float(np.nanmean(fa_rates)),
        "n_folds": N_SPLITS,
        "n_windows_total": int(len(predictions)),
        "n_features": len(FEATURE_COLUMNS),
    }
    return predictions, summary


# ----------------------------------------------------------------------
# CLI entry point
# ----------------------------------------------------------------------
def main() -> None:
    in_path = Path("data/processed/window_features.parquet")
    out_path = Path("data/processed/baseline_scores.parquet")
    model_path = Path("data/processed/baseline_model.pkl")     # ← 新增

    print(f"Loading {in_path} ...")
    features = pd.read_parquet(in_path)
    print(f"  {features.shape}")

    print(f"\nTraining with {N_SPLITS}-fold stratified CV ...")
    predictions, summary = train_5fold(features)

    print("\n==========================================")
    print(" Summary")
    print("==========================================")
    for k, v in summary.items():
        if isinstance(v, float):
            print(f"  {k}: {v:.4f}")
        else:
            print(f"  {k}: {v}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(out_path, index=False)
    print(f"\nWrote {out_path} ({len(predictions)} rows)")

    print("\nTraining final model on all clean data ...")
    clean = features.dropna(subset=FEATURE_COLUMNS).reset_index(drop=True)
    X_all = clean[FEATURE_COLUMNS].to_numpy()
    y_all = clean["label"].to_numpy()

    final_pipe = _build_pipeline()
    final_pipe.fit(X_all, y_all)

    import joblib
    joblib.dump(final_pipe, model_path)
    print(f"Saved model to {model_path}")


if __name__ == "__main__":
    main()