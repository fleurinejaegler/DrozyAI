"""Explicit experimental late fusion with visible missing-source handling."""
from __future__ import annotations

import math
from numbers import Real
from typing import Any


def checked_score(value: Any) -> float:
    """Reject missing, boolean, non-finite and out-of-range scores."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("Scores must be numeric values in [0, 1]")
    score = float(value)
    if not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("Scores must be finite and in [0, 1]")
    return score


def fuse_scores(watch_score: float | None, facial_score: float | None,
                strategy: str = "max", watch_weight: float = 0.5) -> dict[str, Any]:
    """Fuse available scores; an absent source is never replaced with zero.

    Boundaries are explicit: [0, .4) green, [.4, .7) orange, [.7, 1] red.
    `alert` denotes a red-level warning, never an assertion of alertness.
    Thresholds and fusion weights are demonstration choices, not validated.
    """
    if strategy not in {"max", "weighted_average"}:
        raise ValueError("strategy must be max or weighted_average")
    weight = checked_score(watch_weight)
    watch = None if watch_score is None else checked_score(watch_score)
    facial = None if facial_score is None else checked_score(facial_score)
    if watch is None and facial is None:
        score, mode = None, "unavailable"
    elif watch is None:
        score, mode = facial, "facial_only"
    elif facial is None:
        score, mode = watch, "watch_only"
    else:
        score = max(watch, facial) if strategy == "max" else weight * watch + (1 - weight) * facial
        mode = "combined"
    light = "unavailable" if score is None else "green" if score < 0.4 else "orange" if score < 0.7 else "red"
    return {"fused_score": score, "alert": light == "red", "traffic_light": light,
            "mode": mode, "strategy": strategy, "watch_score": watch, "facial_score": facial,
            "watch_weight": weight if strategy == "weighted_average" else None,
            "validated": False, "score_type": "experimental_score"}
