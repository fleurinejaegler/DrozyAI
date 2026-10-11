"""Sliding-window feature extraction for the DrozyAI wearable model.

Reads the aligned per-second table produced by Person 1 and produces
one row per 60-second window (step 5 seconds) with five raw features:

    hr_mean      : mean heart rate over the window
    rmssd        : root mean square of successive differences of IBI
                   (only over seconds with ibi_count > 0)
    temp_trend   : linear slope of skin temperature over the window
    eda_peaks    : number of EDA peaks above (mean + 1*std) in the window
    motion_var   : mean of the three accelerometer variance columns

Note on normalization:
    No per-driver normalization is done here on purpose.
    Normalization is applied inside the model pipeline (see
    src/models/baseline.py) using sklearn's RobustScaler, fitted only
    on the training folds of the leave-one-subject-out split. This
    prevents data leakage from the test subject.

Usage:
    python -m src.features.watch_features
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import warnings


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
WINDOW_SECONDS = 60
STEP_SECONDS = 5

FEATURE_COLUMNS = [
    "hr_mean",
    "rmssd",
    "temp_trend",
    "eda_peaks",
    "motion_var",
]

# Suppress NumPy warnings that we handle explicitly.
warnings.filterwarnings("ignore", message="Mean of empty slice")
warnings.filterwarnings("ignore", message="Degrees of freedom <= 0 for slice")


# ----------------------------------------------------------------------
# Safe aggregation helpers
# ----------------------------------------------------------------------
def _safe_mean(values: np.ndarray) -> float:
    if values.size == 0:
        return float("nan")
    valid = values[~np.isnan(values)]
    return float(np.mean(valid)) if valid.size else float("nan")


# ----------------------------------------------------------------------
# Per-window feature computation
# ----------------------------------------------------------------------
def _rmssd_from_ibi(ibi_values: np.ndarray) -> float:
    if ibi_values.size < 2:
        return float("nan")
    clean = ibi_values[~np.isnan(ibi_values)]
    if clean.size < 2:
        return float("nan")
    diff = np.diff(clean)
    return float(np.sqrt(np.mean(diff ** 2)))


def _temp_trend(values: np.ndarray) -> float:
    clean = values[~np.isnan(values)]
    if clean.size < 2:
        return float("nan")
    x = np.arange(clean.size, dtype=float)
    slope, _ = np.polyfit(x, clean, 1)
    return float(slope)


def _count_eda_peaks(values: np.ndarray, std_mult: float = 1.0) -> int:
    clean = values[~np.isnan(values)]
    if clean.size < 3:
        return 0
    mu = float(np.mean(clean))
    sigma = float(np.std(clean))
    if sigma <= 1e-9:
        return 0
    cutoff = mu + std_mult * sigma
    peaks = 0
    for i in range(1, clean.size - 1):
        if (
            clean[i] > cutoff
            and clean[i] > clean[i - 1]
            and clean[i] >= clean[i + 1]
        ):
            peaks += 1
    return peaks


def _extract_window_features(window: pd.DataFrame) -> dict[str, float]:
    hr = window["heart_rate"].to_numpy(dtype=float)
    temp = window["temp"].to_numpy(dtype=float)
    eda = window["eda"].to_numpy(dtype=float)

    valid_ibi = window.loc[window["ibi_count"] > 0, "ibi_mean"]
    ibi_values = valid_ibi.to_numpy(dtype=float)
    rmssd = _rmssd_from_ibi(ibi_values)

    var_x = _safe_mean(window["accel_var_x"].to_numpy(dtype=float))
    var_y = _safe_mean(window["accel_var_y"].to_numpy(dtype=float))
    var_z = _safe_mean(window["accel_var_z"].to_numpy(dtype=float))
    motion_candidates = [v for v in (var_x, var_y, var_z) if not np.isnan(v)]
    motion_var = float(np.mean(motion_candidates)) if motion_candidates else float("nan")

    return {
        "hr_mean": _safe_mean(hr),
        "rmssd": rmssd,
        "temp_trend": _temp_trend(temp),
        "eda_peaks": float(_count_eda_peaks(eda)),
        "motion_var": motion_var,
    }


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------
def build_feature_table(full_df: pd.DataFrame) -> pd.DataFrame:
    """Build the sliding-window feature table.

    Returns one row per window with the five raw features (no
    normalization) and a majority-vote label.
    """
    records = []

    for (subject, session), group in full_df.groupby(["subject", "session"]):
        group = group.sort_values("second").reset_index(drop=True)
        n = len(group)
        if n < WINDOW_SECONDS:
            continue

        for start in range(0, n - WINDOW_SECONDS + 1, STEP_SECONDS):
            end = start + WINDOW_SECONDS
            window = group.iloc[start:end]
            feats = _extract_window_features(window)
            label = int(round(window["drowsy"].mean()))
            records.append(
                {
                    "subject": subject,
                    "session": session,
                    "window_start": start,
                    "window_end": end,
                    **feats,
                    "label": label,
                }
            )

    features = pd.DataFrame(records)
    return features


# ----------------------------------------------------------------------
# CLI entry point
# ----------------------------------------------------------------------
def main() -> None:
    in_path = Path("data/processed/full_dataset.parquet")
    out_path = Path("data/processed/window_features.parquet")

    print(f"Loading {in_path} ...")
    full_df = pd.read_parquet(in_path)
    print(
        f"  {len(full_df)} rows, "
        f"{full_df['subject'].nunique()} subjects, "
        f"{full_df.groupby(['subject', 'session']).ngroups} sessions"
    )

    print("Building window features ...")
    features = build_feature_table(full_df)
    print(f"  {len(features)} windows")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(out_path, index=False)
    print(f"Wrote {out_path}")

    print("\nRaw feature summary (no normalization):")
    print(features[FEATURE_COLUMNS].describe())

    print("\nMissing values:")
    print(features[FEATURE_COLUMNS].isna().sum())

    print("\nLabel distribution (per window):")
    print(features["label"].value_counts())


if __name__ == "__main__":
    main()