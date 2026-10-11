"""Inference for the shipped four-feature RobustScaler + gradient boosting pipeline.

The saved artifact does not include the isotonic mapping used for evaluation.
Its predict_proba output is exposed as an uncalibrated research score.
Required order: hr_mean, rmssd, temp_trend, motion_var.
Use the exact training preprocessing; do not impute missing sensor fields.
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
    model = joblib.load(path)
    if getattr(model, 'n_features_in_', None) != len(FEATURE_COLUMNS):
        raise ValueError('Watch artifact feature width differs from the four-feature contract')
    if list(getattr(model, 'classes_', [])) != [0, 1]:
        raise ValueError('Watch artifact must have classes [0, 1]')
    return model


def predict_score(
    features: Mapping[str, float] | np.ndarray | list[float],
    model: Any | None = None,
    model_path: Path | str = DEFAULT_MODEL_PATH,
) -> float:
    """Return the uncalibrated drowsiness score for one window.

    Parameters
    ----------
    features : mapping, ndarray, or list
        Either a dict with the four feature keys, or an array-like of
        length 4 in the order [hr_mean, rmssd, temp_trend, motion_var].
    model : fitted Pipeline, optional
        If provided, it is used directly. Otherwise loaded from
        `model_path`.
    model_path : Path or str
        Only used when `model` is None.

    Returns
    -------
    float
        Uncalibrated score in [0, 1]. Higher means more drowsy.
    """
    # Build the (1, 4) input array
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

    if not np.isfinite(x).all():
        raise ValueError(
            "Features contain non-finite values. Fill missing values before "
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
    """Return uncalibrated scores for many windows at once.

    Parameters
    ----------
    features_matrix : (N, 4) array-like
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
    if not np.isfinite(X).all():
        raise ValueError("Features contain non-finite values.")

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
        "motion_var": 9.0,
    }
    drowsy = {
        "hr_mean": 72.0,
        "rmssd": 0.045,
        "temp_trend": 0.0003,
        "motion_var": 4.0,
    }

    print("Demo: predict_score on two hand-crafted windows")
    print(f"  Alert-like  -> score = {predict_score(alert):.4f}")
    print(f"  Drowsy-like -> score = {predict_score(drowsy):.4f}")


if __name__ == "__main__":
    _demo()