"""Gradient boosting baseline for the DrozyAI vision model.

Reads the facial feature table produced by src.features.video_features,
joins the drowsy label from the watch feature table, and trains a
HistGradientBoostingClassifier with 5-fold stratified cross-validation.

The 11 facial features come from the UL-DD pre-extracted landmarks:
    left_ear_mean, right_ear_mean, perclos, longest_closure_sec,
    blink_rate_per_min, blink_duration_mean, inter_blink_interval_mean,
    mar_mean, yawn_count, max_yawn_duration, tracking_coverage

Output:
    data/processed/video_scores.parquet
        One row per window, with columns [subject, session,
        window_start, label, proba, pred, fold, proba_calibrated]

Usage:
    python -m src.models.video_baseline
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
    "left_ear_mean",
    "right_ear_mean",
    "perclos",
    "longest_closure_sec",
    "blink_rate_per_min",
    "blink_duration_mean",
    "inter_blink_interval_mean",
    "mar_mean",
    "yawn_count",
    "max_yawn_duration",
    "tracking_coverage",
]

N_SPLITS = 5
STEP_SECONDS = 5
WINDOWS_PER_HOUR = 3600 // STEP_SECONDS  # 720
RANDOM_STATE = 42


# ----------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------
def missed_drowsy_rate(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    drowsy = y_true == 1
    if drowsy.sum() == 0:
        return float("nan")
    missed = (y_pred[drowsy] == 0).sum()
    return float(missed) / float(drowsy.sum())


def false_alarms_per_hour(y_true: np.ndarray, y_pred: np.ndarray) -> float:
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
# Data loading and alignment
# ----------------------------------------------------------------------
def load_aligned_data() -> pd.DataFrame:
    """Load video features and merge the drowsy label from watch features."""
    video_path = Path("data/processed/video_features.parquet")
    watch_path = Path("data/processed/window_features.parquet")

    video = pd.read_parquet(video_path)
    watch = pd.read_parquet(watch_path)

    # Only need subject, session, window_start, label from watch
    watch_labels = watch[["subject", "session", "window_start", "label"]]

    # Merge on the shared window key
    merged = video.merge(
        watch_labels,
        on=["subject", "session", "window_start"],
        how="inner",
    )

    # Fill NaN semantically:
    # - No yawn detected -> 0 seconds
    # - No blink detected -> 0 duration
    # - No inter-blink interval -> 0
    # - Otherwise -> per-subject median
    merged["max_yawn_duration"] = merged["max_yawn_duration"].fillna(0.0)
    merged["yawn_count"] = merged["yawn_count"].fillna(0.0)
    merged["blink_duration_mean"] = merged["blink_duration_mean"].fillna(0.0)
    merged["inter_blink_interval_mean"] = merged["inter_blink_interval_mean"].fillna(0.0)

    # Any remaining NaN -> per-subject median, then 0
    for col in FEATURE_COLUMNS:
        if merged[col].isna().any():
            merged[col] = merged.groupby("subject")[col].transform(
                lambda s: s.fillna(s.median())
            )
            merged[col] = merged[col].fillna(0.0)

    return merged


# ----------------------------------------------------------------------
# 5-fold cross-validation
# ----------------------------------------------------------------------
def train_5fold(
    features_df: pd.DataFrame,
    threshold: float = 0.5,
) -> tuple[pd.DataFrame, dict]:
    """Train and evaluate with 5-fold stratified cross-validation."""
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
    out_path = Path("data/processed/video_scores.parquet")
    model_path = Path("data/processed/video_model.pkl")

    print("Loading and aligning video + watch features ...")
    features = load_aligned_data()
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

    # Train final model on all clean data and save
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