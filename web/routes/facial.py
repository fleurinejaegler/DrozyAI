"""Inference endpoints for the existing TCN and logistic video benchmark."""
from __future__ import annotations

from typing import Any

from flask import Blueprint, current_app

from src.features.fusion import checked_score
from src.features.video_features import FEATURES
from web.routes import feature_values, json_object

router = Blueprint("facial_score", __name__)


def score_payload(body: Any) -> dict[str, Any]:
    """Require model-specific inputs rather than substitute blendshape scores."""
    if not isinstance(body, dict):
        raise ValueError("facial must be an object")
    models = current_app.extensions["facial_models"]
    name = body.get("model", "small_tcn")
    if name == "small_tcn":
        score = models.predict_tcn(body.get("sequence"), body.get("channels"))
    elif name == "logistic_regression":
        score = models.predict_logistic(feature_values(body.get("features"), FEATURES))
    else:
        raise ValueError("model must be small_tcn or logistic_regression")
    return {"score": checked_score(score), "model": name, "score_type": "uncalibrated_score",
            "source": "provided_features", "live_camera_adapter_ready": False}


@router.post("/api/facial")
def facial_score() -> dict[str, Any]:
    """Score one trailing 60-second sequence or one aggregated feature row."""
    return score_payload(json_object())
