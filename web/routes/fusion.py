"""Combine explicit component scores or compute them from measured features."""
from __future__ import annotations

from typing import Any

from flask import Blueprint

from src.features.fusion import fuse_scores
from web.routes import json_object
from web.routes.facial import score_payload
from web.routes.score import score_features

router = Blueprint("fusion", __name__)


@router.post("/api/fusion")
def fused_score() -> dict[str, Any]:
    """Allow single-source operation, with the operating mode in every result."""
    body = json_object()
    from_features = "watch_features" in body or "facial" in body
    if from_features and ("watch_score" in body or "facial_score" in body):
        raise ValueError("Choose feature inputs or provided scores, not both")
    if from_features:
        watch = score_features(body["watch_features"]) if body.get("watch_features") is not None else None
        facial = score_payload(body["facial"])["score"] if body.get("facial") is not None else None
    else:
        watch, facial = body.get("watch_score"), body.get("facial_score")
    result = fuse_scores(watch, facial, body.get("strategy", "max"), body.get("watch_weight", 0.5))
    result["input_source"] = "provided_features" if from_features else "provided_scores"
    # Alert transport to a Garmin app is a separate, unfinished integration.
    result["watch_alert_sent"] = False
    return result
