"""Load Isaac's existing video models without retraining the watch model.

The small TCN consumes 15 channels over 60 trailing seconds. The logistic
regression benchmark consumes 22 aggregated video features. Outputs are
uncalibrated scores; neither model has been validated on live RGB webcams.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Mapping

import joblib
import numpy as np
import torch
from torch import nn

from src.features.facial_sequence import CHANNELS, FEATURES

ROOT = Path(__file__).resolve().parents[2]


def small_tcn() -> nn.Sequential:
    """Reproduce the saved 3,889-parameter network's layer order exactly."""
    layers: list[nn.Module] = []
    input_channels = len(CHANNELS)
    for dilation in (1, 2, 4, 8, 16):
        layers.extend([
            nn.ConstantPad1d((2 * dilation, 0), 0),
            nn.Conv1d(input_channels, 16, kernel_size=3, dilation=dilation),
            nn.ReLU(), nn.Dropout(0.15),
        ])
        input_channels = 16
    layers.extend([nn.AdaptiveAvgPool1d(1), nn.Flatten(), nn.Linear(16, 1)])
    return nn.Sequential(*layers)


def validate_sequence(value: Any, channels: Any, *, allow_partial=False) -> np.ndarray:
    """Require the training schema, finite values and observed-time coverage."""
    if channels != CHANNELS:
        raise ValueError("channels must exactly match /api/models → facial.channels")
    try:
        sequence = np.asarray(value)
    except (TypeError, ValueError) as error:
        raise ValueError("sequence must be a rectangular numeric array") from error
    if sequence.shape != (15, 60) or sequence.dtype.kind not in "fiu":
        raise ValueError("sequence must have shape [15 channels][60 seconds] with numeric values")
    sequence = sequence.astype(np.float64)
    if not np.isfinite(sequence).all() or (sequence < 0).any():
        raise ValueError("sequence must contain finite, nonnegative values")
    if (sequence[[2, 3, 10, 14]] > 1).any():
        raise ValueError("fraction channels must be in [0, 1]")
    if (sequence[[0, 1, 9]] > 2).any():
        raise ValueError("eye openness and mouth ratios must be in [0, 2]")
    if (sequence[[4, 8, 11]] > 60).any():
        raise ValueError("state ages and maximum blink durations must be capped at 60 seconds")
    if allow_partial:
        if sequence[14].sum() < 10 or sequence[14,-5:].sum() < 0.5:
            raise ValueError('Partial live video needs 10 observed seconds and recent face observations')
    elif sequence[14].mean() < 0.90 or sequence[14].min() < 0.50:
        raise ValueError("Insufficient observed coverage: need 90% overall and 50% in each second")
    # Training exports are float32. Match their rounding before preprocessing.
    with np.errstate(over="ignore"):
        sequence = sequence.astype(np.float32)
    if not np.isfinite(sequence).all():
        raise ValueError("Sequence values exceed the model's numeric range")
    return sequence


@dataclass
class FacialModels:
    """Trusted, local artifacts loaded once per application instance."""
    network: nn.Sequential
    scaler: Any
    logistic: Any
    lock: Lock

    @classmethod
    def load(cls, directory: Path = ROOT / "data/processed") -> FacialModels:
        """Use weights-only PyTorch loading and verify the embedded contract."""
        checkpoint = torch.load(directory / "small_tcn.pt", map_location="cpu", weights_only=True)
        if (checkpoint["channels"] != CHANNELS or checkpoint["hidden_channels"] != 16
                or checkpoint["dilations"] != [1, 2, 4, 8, 16]
                or checkpoint["config"]["window_seconds"] != 60):
            raise ValueError("Unexpected TCN checkpoint architecture or feature schema")
        network = small_tcn()
        network.load_state_dict(checkpoint["state_dict"], strict=True)
        network.eval()
        scaler = joblib.load(directory / "tcn_scaler.joblib")
        benchmark = joblib.load(directory / "facial_model.pkl")
        if scaler.n_features_in_ != 15 or benchmark["features"] != FEATURES:
            raise ValueError("Saved preprocessing schema does not match the model inputs")
        return cls(network, scaler, benchmark["model"], Lock())

    def predict_tcn(self, sequence: Any, channels: Any, *, allow_partial=False) -> float:
        """Apply the original scaler per second and return a sigmoid score."""
        values = validate_sequence(sequence, channels, allow_partial=allow_partial)
        normalized = self.scaler.transform(values.T).T
        if not np.isfinite(normalized).all():
            raise ValueError("Scaled sequence is non-finite")
        tensor = torch.from_numpy(np.ascontiguousarray(normalized[None], dtype=np.float32))
        with self.lock, torch.inference_mode():
            score = float(torch.sigmoid(self.network(tensor)).item())
        return score

    def predict_logistic(self, features: Mapping[str, float]) -> float:
        """Run the existing interpretable benchmark on its original 22 columns."""
        import pandas as pd

        if not 0.90 <= features["valid_frame_fraction"] <= 1:
            raise ValueError("Logistic inputs need at least 90% valid-frame coverage")
        return float(self.logistic.predict_proba(pd.DataFrame([features], columns=FEATURES))[0, 1])


def train_logistic_baseline(training: Any, destination: Path) -> None:
    """Fit a benchmark on caller-supplied training people only; no watch changes.

    Split participants before calling this function. Evaluation belongs on
    separate participants and must not use this final model's training scores.
    The shipped artifact already exists; running this function is optional.
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    model = make_pipeline(StandardScaler(), LogisticRegression(
        C=0.3, max_iter=2000, class_weight="balanced", random_state=42))
    model.fit(training[FEATURES], training["drowsy"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "features": FEATURES}, destination, compress=3)
