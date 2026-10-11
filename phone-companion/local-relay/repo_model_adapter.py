"""Read-only adapter to the teammate's existing src.models.predict interface.

Raw Garmin telemetry is not compatible with the current UL-DD five-feature model.
This adapter does not fabricate EDA, substitute sensor temperature for skin
temperature, or silently change the trained RMSSD/motion preprocessing.
"""
from __future__ import annotations

import ast
import hashlib
import math
import sys
from collections.abc import Mapping
from numbers import Real
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREDICT_SOURCE = ROOT / "src/models/predict.py"
MODEL_PATH = ROOT / "data/processed/baseline_model.pkl"


def feature_order():
    """Read the actual source contract without importing ML dependencies."""
    tree = ast.parse(PREDICT_SOURCE.read_text(encoding="utf-8-sig"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "FEATURE_COLUMNS"
            for target in node.targets
        ):
            names = ast.literal_eval(node.value)
            if isinstance(names, list) and all(isinstance(name, str) for name in names):
                return tuple(names)
    raise ValueError("No explicit FEATURE_COLUMNS contract in src/models/predict.py")


class RepoModelAdapter:
    def __init__(self, model_path=MODEL_PATH):
        self.model_path = Path(model_path).resolve()
        self.features = feature_order()
        self._model = None
        self.version = "uldd-baseline-" + (
            hashlib.sha256(self.model_path.read_bytes()).hexdigest()[:12]
            if self.model_path.is_file() else "not-found"
        )

    def evaluate_garmin(self, packet):
        """Return missing risk until a Garmin-compatible feature contract exists."""
        if not self.model_path.is_file():
            return self._result(None, "model_not_connected", ["Trained artifact missing"])
        return self._result(None, "insufficient_data", [
            "Garmin feed has no EDA; eda_peaks cannot be supplied",
            "Sensor.Info temperature is not established as the training skin-temperature input",
            "Training RMSSD uses successive per-second IBI means, unlike watch beat-level RMSSD",
            "Training accelerometer units/scale and 32 Hz aggregation need an explicit Garmin mapping",
        ])

    def evaluate_prepared_features(self, features):
        """Call the existing model with complete, training-compatible features.

        This is for the teammate's matching preprocessing, not raw Garmin packets.
        Feature units and definitions must match src.features.watch_features.
        """
        if not isinstance(features, Mapping):
            raise TypeError("Expected named, training-compatible features")
        missing = [name for name in self.features if name not in features]
        if missing:
            return self._result(None, "insufficient_data", ["Missing: " + ", ".join(missing)])
        values = {}
        for name in self.features:
            value = features[name]
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                return self._result(None, "insufficient_data", ["Invalid feature: " + name])
            values[name] = float(value)
        if not self.model_path.is_file():
            return self._result(None, "model_not_connected", ["Trained artifact missing"])
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from src.models.predict import load_model, predict_score
        if self._model is None:
            self._model = load_model(self.model_path)
        score = float(predict_score(values, model=self._model))
        if not math.isfinite(score) or not 0 <= score <= 1:
            return self._result(None, "insufficient_data", ["Invalid model output"])
        return self._result(score, "ready", [])

    def send_garmin_result(self, relay, snapshot):
        """Relay an explicit unknown result for this incompatible live model."""
        result = self.evaluate_garmin(snapshot.get("telemetry"))
        receipt = relay.send_model_result(snapshot, result["riskScore"], self.version, result["status"])
        return result, receipt

    def _result(self, score, status, reasons):
        return {"riskScore": score, "status": status, "modelVersion": self.version,
                "featureOrder": list(self.features), "reasons": reasons}


if __name__ == "__main__":
    import json
    adapter = RepoModelAdapter()
    print(json.dumps(adapter.evaluate_garmin(None), indent=2))
