"""Thin adapter around the teammate-owned watch prediction interface."""
from __future__ import annotations

from typing import Any

from flask import Blueprint, current_app

from src.features.fusion import checked_score
from src.models.predict import FEATURE_COLUMNS, predict_score
from web.routes import feature_values, json_object

router = Blueprint("watch_score", __name__)


def score_features(value: Any) -> float:
    """Call the black box with validated features and the startup-loaded model."""
    features = feature_values(value, FEATURE_COLUMNS)
    model = current_app.extensions["watch_model"]
    return checked_score(predict_score(features, model=model))


@router.post("/api/score")
def watch_score() -> dict[str, Any]:
    """Accept a feature dictionary directly or inside a `features` envelope."""
    body = json_object()
    return {"score": score_features(body.get("features", body)),
            "model": "teammate_watch_baseline", "source": "provided_features",
            "live_garmin_adapter_ready": False}
