"""Late fusion of watch and vision drowsiness scores.

Reads the calibrated probabilities from the watch model
(data/processed/baseline_scores.parquet) and the vision model
(data/processed/video_scores.parquet), aligns them on
(subject, session, window_start), and produces a fused score.

Fusion methods:
    - max        : max(watch, vision)          -- safety-first
    - weighted   : w * watch + (1-w) * vision  -- tunable
    - product    : watch * vision              -- conservative
    - mean       : (watch + vision) / 2        -- simple

Output:
    data/processed/fused_scores.parquet
        One row per window, with both raw scores, the fused score,
        the fused binary prediction, and the traffic-light state.

Usage:
    python -m src.features.fusion
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
STEP_SECONDS = 5
WINDOWS_PER_HOUR = 3600 // STEP_SECONDS  # 720

# Traffic-light thresholds
GREEN_MAX = 0.4
ORANGE_MAX = 0.7

# Default fusion method
FUSION_METHOD = "mean"
# Weight for the "weighted" method (watch_weight, vision_weight = 1 - watch_weight)
WATCH_WEIGHT = 0.4


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
# Fusion
# ----------------------------------------------------------------------
def fuse_scores(
    watch: np.ndarray,
    vision: np.ndarray,
    method: str = FUSION_METHOD,
    watch_weight: float = WATCH_WEIGHT,
) -> np.ndarray:
    """Fuse two arrays of probabilities."""
    if method == "max":
        return np.maximum(watch, vision)
    if method == "mean":
        return (watch + vision) / 2.0
    if method == "product":
        return watch * vision
    if method == "weighted":
        return watch_weight * watch + (1.0 - watch_weight) * vision
    raise ValueError(f"Unknown fusion method: {method}")


def traffic_light(score: float) -> str:
    if score < GREEN_MAX:
        return "green"
    if score < ORANGE_MAX:
        return "orange"
    return "red"


# ----------------------------------------------------------------------
# Data loading and alignment
# ----------------------------------------------------------------------
def load_and_fuse() -> pd.DataFrame:
    """Load both score tables, align them, and produce the fused table."""
    watch_path = Path("data/processed/baseline_scores.parquet")
    video_path = Path("data/processed/video_scores.parquet")

    watch = pd.read_parquet(watch_path)
    video = pd.read_parquet(video_path)

    # Keep only the columns we need
    watch = watch[[
        "subject", "session", "window_start", "window_end",
        "label", "proba_calibrated",
    ]].rename(columns={"proba_calibrated": "watch_score"})

    video = video[[
        "subject", "session", "window_start",
        "proba_calibrated",
    ]].rename(columns={"proba_calibrated": "vision_score"})

    # Inner join on the shared window key
    merged = watch.merge(
        video,
        on=["subject", "session", "window_start"],
        how="inner",
    )
    print(f"  Merged rows: {len(merged)}")

    # Fuse
    merged["fused_score"] = fuse_scores(
        merged["watch_score"].to_numpy(),
        merged["vision_score"].to_numpy(),
    )
    merged["fused_pred"] = (merged["fused_score"] >= 0.5).astype(int)
    merged["traffic_light"] = merged["fused_score"].apply(traffic_light)

    return merged


# ----------------------------------------------------------------------
# Evaluation
# ----------------------------------------------------------------------
def evaluate(df: pd.DataFrame) -> dict:
    """Report AUC, missed rate, FA/hour for watch, vision, and fused."""
    y = df["label"].to_numpy()

    results = {}
    for name, score_col in [
        ("watch", "watch_score"),
        ("vision", "vision_score"),
        ("fused", "fused_score"),
    ]:
        score = df[score_col].to_numpy()
        pred = (score >= 0.5).astype(int)
        auc = roc_auc_score(y, score) if len(np.unique(y)) > 1 else float("nan")
        missed = missed_drowsy_rate(y, pred)
        fa = false_alarms_per_hour(y, pred)
        results[name] = {
            "auc": auc,
            "missed_drowsy_rate": missed,
            "false_alarms_per_hour": fa,
        }
    return results


# ----------------------------------------------------------------------
# CLI entry point
# ----------------------------------------------------------------------
def main() -> None:
    out_path = Path("data/processed/fused_scores.parquet")

    print("Loading and fusing watch + vision scores ...")
    df = load_and_fuse()
    print(f"  {df.shape}")

    print("\n==========================================")
    print(" Evaluation")
    print("==========================================")
    results = evaluate(df)
    for name, r in results.items():
        print(f"  {name:>8}: AUC={r['auc']:.4f}  "
              f"missed={r['missed_drowsy_rate']:.3f}  "
              f"FA/h={r['false_alarms_per_hour']:.1f}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    print(f"\nWrote {out_path} ({len(df)} rows)")

    # Show traffic-light distribution
    print("\nTraffic-light distribution (fused):")
    print(df["traffic_light"].value_counts())


if __name__ == "__main__":
    main()