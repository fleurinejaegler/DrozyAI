"""JSON validation shared by the local Flask endpoints."""
from __future__ import annotations

import math
from numbers import Real
from typing import Any, Sequence

from flask import request


def json_object() -> dict[str, Any]:
    """Require a JSON object, including for actions with an empty payload."""
    body = request.get_json()
    if not isinstance(body, dict):
        raise ValueError("A JSON object is required")
    return body


def feature_values(value: Any, columns: Sequence[str]) -> dict[str, float]:
    """Require every measured feature; never silently impute absent sensors."""
    if not isinstance(value, dict):
        raise ValueError("features must be an object")
    missing = [name for name in columns if name not in value]
    if missing:
        raise ValueError("Missing features: " + ", ".join(missing))
    clean: dict[str, float] = {}
    for name in columns:
        raw = value[name]
        if isinstance(raw, bool) or not isinstance(raw, Real) or not math.isfinite(float(raw)):
            raise ValueError(f"{name} must be a finite number")
        clean[name] = float(raw)
    return clean
