"""LLM meta-advisor: decides fusion weights, adapts thresholds to driver
baseline, and writes a narrative story instead of a number.

Direction is computed in Python, not by the LLM. Each feature is annotated
with above / below / at the baseline, plus a magnitude word. This prevents
the small model from flipping "above" and "below".

The target action is also computed in Python and passed to the LLM as a
fact. The LLM's job is only to write a story that supports that action.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import requests

from src.advisor.fallback import rule_based_advisor


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")
MODEL = os.environ.get("LLM_MODEL", "llama3.2:3b")
TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "15"))

SYSTEM_PROMPT = """You are a drowsy-driving safety co-pilot.

You will receive a JSON object with:
- watch_score: float in [0, 1] from a smartwatch model
- vision_score: float in [0, 1] from a facial-video model
- watch_features: raw watch features for this 60-second window
- vision_features: raw vision features for this 60-second window
- baseline_comparison: for each feature, the current value, the driver's
  own baseline mean and std, the difference, the z-score, and the
  pre-computed direction word ("above", "below", or "at") and magnitude
  word ("at", "slightly", "moderately", "strongly")
- recent_risk: list of the last 10 fused risk scores (oldest first)
- target_action: the final action that has been decided:
  "continue" | "take a break at the next rest area" | "stop now"

IMPORTANT: Direction and magnitude words are pre-computed. Use them
EXACTLY as given. Do not compute direction yourself.

Your job:
1. Decide how much to trust each model. Output weights that sum to 1.
2. Compute fused_score = watch_weight * watch_score + vision_weight * vision_score.
3. In your JSON, set "action" to target_action EXACTLY. Do not choose your own action.
4. Write a 2-3 sentence STORY that:
   - uses the direction and magnitude words from baseline_comparison,
   - mentions specific features and timings,
   - SUPPORTS the target_action. For "continue", write a reassuring story.
     For "take a break at the next rest area", explain why a break helps.
     For "stop now", convey urgency.

Respond with JSON ONLY, in this exact shape:
{
  "fused_score": <float>,
  "action": "<must equal target_action>",
  "reason": "<2-3 sentence story>",
  "weights": {"watch": <float>, "vision": <float>},
  "confidence": <float in [0, 1]>
}
No text outside the JSON.
"""


# ----------------------------------------------------------------------
# Baseline comparison helpers
# ----------------------------------------------------------------------
def _direction_word(diff: float, eps: float = 1e-9) -> str:
    if diff > eps:
        return "above"
    if diff < -eps:
        return "below"
    return "at"


def _magnitude_word(z: float) -> str:
    z = abs(z)
    if z < 0.25:
        return "at"
    if z < 0.75:
        return "slightly"
    if z < 1.5:
        return "moderately"
    return "strongly"


def _baseline_compare(
    features: dict[str, float],
    baseline: dict[str, float],
    prefix: str,
    keys: list[str],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for k in keys:
        current = features.get(k)
        mean = baseline.get(f"{prefix}_{k}_mean")
        std = baseline.get(f"{prefix}_{k}_std")
        if current is None or mean is None:
            continue
        mean = float(mean)
        std = float(std) if std else 0.0
        diff = float(current) - mean
        z = diff / std if std > 1e-9 else 0.0
        out[k] = {
            "current": round(float(current), 4),
            "baseline_mean": round(mean, 4),
            "baseline_std": round(std, 4),
            "difference": round(diff, 4),
            "z_score": round(z, 3),
            "direction": _direction_word(diff),
            "magnitude": _magnitude_word(z),
        }
    return out


# ----------------------------------------------------------------------
# Action helper
# ----------------------------------------------------------------------
def _action_from_score(score: float) -> str:
    if score < 0.40:
        return "continue"
    if score >= 0.70:
        return "stop now"
    return "take a break at the next rest area"


# ----------------------------------------------------------------------
# Prompt construction
# ----------------------------------------------------------------------
def _prepare_user_payload(
    watch_score: float,
    vision_score: float,
    watch_features: dict[str, float],
    vision_features: dict[str, float],
    baseline: dict[str, float],
    recent_risk: list[float],
    target_action: str = "",
) -> dict[str, Any]:
    keys_watch = ["hr_mean", "rmssd", "temp_trend", "motion_var"]
    keys_vision = [
        "perclos", "blink_rate_per_min", "longest_closure_sec",
        "left_ear_mean", "right_ear_mean", "yawn_count",
    ]

    def pick(feats, keys):
        return {k: round(float(feats.get(k, 0.0)), 4) for k in keys}

    return {
        "watch_score": round(float(watch_score), 3),
        "vision_score": round(float(vision_score), 3),
        "watch_features": pick(watch_features, keys_watch),
        "vision_features": pick(vision_features, keys_vision),
        "baseline_comparison": {
            "watch": _baseline_compare(watch_features, baseline, "w", keys_watch),
            "vision": _baseline_compare(vision_features, baseline, "v", keys_vision),
        },
        "recent_risk": [round(float(x), 3) for x in recent_risk[-10:]],
        "target_action": target_action,
    }


# ----------------------------------------------------------------------
# JSON extraction
# ----------------------------------------------------------------------
def _extract_json(text: str) -> dict[str, Any] | None:
    candidates = [text]

    stripped = text.strip().strip("`")
    if stripped.startswith("json"):
        stripped = stripped[4:].strip()
    candidates.append(stripped)

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        candidates.append(match.group(0))

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
    return None


# ----------------------------------------------------------------------
# LLM call
# ----------------------------------------------------------------------
def _call_llm(payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(
        f"{BASE_URL}/chat/completions",
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload)},
            ],
            "temperature": 0.3,
            "max_tokens": 150,
            "response_format": {"type": "json_object"},
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"].strip()

    result = _extract_json(content)
    if result is None:
        raise ValueError(f"Could not parse JSON from LLM output: {content[:200]}")
    return result


def _validate(result: dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return False
    for key in ("fused_score", "action", "reason"):
        if key not in result:
            return False
    if result["action"] not in {
        "stop now", "take a break at the next rest area", "continue"
    }:
        return False
    try:
        float(result["fused_score"])
    except (TypeError, ValueError):
        return False
    return isinstance(result["reason"], str) and bool(result["reason"].strip())


def _enforce_action_thresholds(result: dict[str, Any]) -> dict[str, Any]:
    """Force the action to match the fused_score thresholds."""
    try:
        score = float(result["fused_score"])
    except (KeyError, TypeError, ValueError):
        return result
    result["action"] = _action_from_score(score)
    return result


# ----------------------------------------------------------------------
# Rule-based meta-advisor (fallback)
# ----------------------------------------------------------------------
def _fallback(
    watch_score: float, vision_score: float, recent_risk: list[float]
) -> dict[str, Any]:
    fused = 0.5 * watch_score + 0.5 * vision_score
    action = _action_from_score(fused)
    base = rule_based_advisor(fused, trend=0.0, top_signals=[])
    return {
        "fused_score": fused,
        "action": action,
        "reason": base["reason"],
        "weights": {"watch": 0.5, "vision": 0.5},
        "confidence": 0.5,
        "source": "fallback",
    }


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------
def meta_advisor(
    watch_score: float,
    vision_score: float,
    watch_features: dict[str, float] | None = None,
    vision_features: dict[str, float] | None = None,
    baseline: dict[str, float] | None = None,
    recent_risk: list[float] | None = None,
) -> dict[str, Any]:
    """LLM meta-advisor with rule-based fallback."""
    watch_features = watch_features or {}
    vision_features = vision_features or {}
    baseline = baseline or {}
    recent_risk = recent_risk or []

    # Target action from a quick fused estimate
    quick_fused = 0.5 * watch_score + 0.5 * vision_score
    target_action = _action_from_score(quick_fused)

    payload = _prepare_user_payload(
        watch_score, vision_score,
        watch_features, vision_features,
        baseline, recent_risk,
        target_action=target_action,
    )

    try:
        result = _call_llm(payload)
        if _validate(result):
            result = _enforce_action_thresholds(result)
            result["source"] = "llm"
            return result
        fb = _fallback(watch_score, vision_score, recent_risk)
        fb["source"] = "fallback_invalid"
        return fb
    except Exception as exc:  # noqa: BLE001
        fb = _fallback(watch_score, vision_score, recent_risk)
        fb["source"] = f"fallback_error: {type(exc).__name__}"
        return fb