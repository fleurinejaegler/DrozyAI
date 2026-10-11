"""Real-time drowsiness score interface for the DrozyAI driver app.

Exposes a single function, `predict_score`, that takes one 60-second
window of wearable features and returns a calibrated drowsiness
probability in [0, 1].

The probability is produced by the Person 2 baseline
(HistGradientBoostingClassifier + RobustScaler + isotonic calibration),
trained on the UL-DD dataset with 5-fold stratified cross-validation.

Usage
-----
    from src.models.predict import load_model, predict_score

    # Option A: one-shot call (loads model from disk)
    score = predict_score({
        "hr_mean": 75.3,
        "rmssd": 0.052,
        "temp_trend": -0.0001,
        "eda_peaks": 3,
        "motion_var": 8.2,
    })
    print(score)   # e.g. 0.68

    # Option B: load the model once, then call many times
    model = load_model()
    for window in stream:
        score = predict_score(window, model=model)

Notes
-----
- The score is a *real probability*: 0.7 means about a 70% chance
  that the current window is drowsy.
- Missing feature values are not allowed; the caller must fill them
  (for example with the driver's baseline).
- The model must be trained first with:
      python -m src.models.baseline
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import joblib
import numpy as np


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
FEATURE_COLUMNS = [
    "hr_mean",
    "rmssd",
    "temp_trend",
    "eda_peaks",
    "motion_var",
]

DEFAULT_MODEL_PATH = Path("data/processed/baseline_model.pkl")


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------
def load_model(model_path: Path | str = DEFAULT_MODEL_PATH):
    """Load the trained sklearn Pipeline from disk."""
    path = Path(model_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Model file not found: {path}. "
            "Run `python -m src.models.baseline` first to train and "
            "save the model."
        )
    return joblib.load(path)


def predict_score(
    features: Mapping[str, float] | np.ndarray | list[float],
    model: Any | None = None,
    model_path: Path | str = DEFAULT_MODEL_PATH,
) -> float:
    """Return the calibrated drowsiness probability for one window.

    Parameters
    ----------
    features : mapping, ndarray, or list
        Either a dict with the 5 feature keys, or an array-like of
        length 5 in the order [hr_mean, rmssd, temp_trend, eda_peaks,
        motion_var].
    model : fitted Pipeline, optional
        If provided, it is used directly. Otherwise loaded from
        `model_path`.
    model_path : Path or str
        Only used when `model` is None.

    Returns
    -------
    float
        Calibrated probability in [0, 1]. Higher means more drowsy.
    """
    # Build the (1, 5) input array
    if isinstance(features, Mapping):
        x = np.array(
            [[float(features[c]) for c in FEATURE_COLUMNS]],
            dtype=float,
        )
    else:
        arr = np.asarray(features, dtype=float).reshape(1, -1)
        if arr.shape[1] != len(FEATURE_COLUMNS):
            raise ValueError(
                f"Expected {len(FEATURE_COLUMNS)} features, "
                f"got {arr.shape[1]}."
            )
        x = arr

    if np.isnan(x).any():
        raise ValueError(
            "Features contain NaN. Fill missing values before "
            "calling predict_score."
        )

    if model is None:
        model = load_model(model_path)

    return float(model.predict_proba(x)[0, 1])


def predict_score_batch(
    features_matrix: np.ndarray | list[list[float]],
    model: Any | None = None,
    model_path: Path | str = DEFAULT_MODEL_PATH,
) -> np.ndarray:
    """Return calibrated probabilities for many windows at once.

    Parameters
    ----------
    features_matrix : (N, 5) array-like
    model, model_path : same as predict_score

    Returns
    -------
    np.ndarray of shape (N,)
    """
    X = np.asarray(features_matrix, dtype=float)
    if X.ndim != 2 or X.shape[1] != len(FEATURE_COLUMNS):
        raise ValueError(
            f"Expected shape (N, {len(FEATURE_COLUMNS)}), got {X.shape}."
        )
    if np.isnan(X).any():
        raise ValueError("Features contain NaN.")

    if model is None:
        model = load_model(model_path)

    return model.predict_proba(X)[:, 1]


# ----------------------------------------------------------------------
# CLI demo
# ----------------------------------------------------------------------
def _demo() -> None:
    """Quick self-test with two hand-crafted windows."""
    alert = {
        "hr_mean": 78.0,
        "rmssd": 0.065,
        "temp_trend": -0.0002,
        "eda_peaks": 3,
        "motion_var": 9.0,
    }
    drowsy = {
        "hr_mean": 72.0,
        "rmssd": 0.045,
        "temp_trend": 0.0003,
        "eda_peaks": 2,
        "motion_var": 4.0,
    }

    print("Demo: predict_score on two hand-crafted windows")
    print(f"  Alert-like  -> score = {predict_score(alert):.4f}")
    print(f"  Drowsy-like -> score = {predict_score(drowsy):.4f}")


if __name__ == "__main__":
    _demo()