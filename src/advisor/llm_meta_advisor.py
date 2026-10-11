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
import math
import os
import re
from urllib.parse import urlsplit
from typing import Any

import requests

from src.advisor.fallback import rule_based_advisor


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")
MODEL = os.environ.get("LLM_MODEL", "llama3.2:3b")
TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "15"))

SYSTEM_PROMPT = """Summarize experimental, uncalibrated drowsiness-model signals.
Input: watch_score, vision_score, measured features, optional descriptive
baseline_comparison, recent_risk, and target_action chosen by Python.
Choose watch weight w in [0,1]; vision weight is 1-w. Missing baseline is
unknown. Use provided directions; invent no measurements or certainty.
Return ONLY this JSON array: [0.5,0.5,"factual reason, maximum 4 words"].
Values are [watch weight, self-reported confidence, reason]. Confidence is
not detection accuracy. Python computes the
weighted score and action. Do not output calculations or additional keys.
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
    return rule_based_advisor(score)['action']


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
    # Keep real feature names from the supplied extractor. Absent values stay
    # absent; they must never become fabricated zeros in an LLM prompt.
    keys_vision = list(vision_features)

    def pick(feats, keys):
        return {k: round(float(feats[k]), 4) for k in keys if k in feats}

    comparisons = {
        "watch": _baseline_compare(watch_features, baseline, "w", keys_watch),
        "vision": _baseline_compare(vision_features, baseline, "v", keys_vision),
    }
    # Keep the most informative baseline comparisons to bound local latency;
    # all current raw features are still supplied. Empty baseline stays empty.
    ranked = sorted(((abs(v["z_score"]), source, key) for source, entries in comparisons.items()
                     for key, v in entries.items()), reverse=True)[:6]
    selected = {(source, key) for _, source, key in ranked}
    comparisons = {source: {k:v for k,v in entries.items() if (source,k) in selected}
                   for source, entries in comparisons.items()}
    return {
        "watch_score": round(float(watch_score), 3),
        "vision_score": round(float(vision_score), 3),
        "watch_features": pick(watch_features, keys_watch),
        "vision_features": pick(vision_features, keys_vision),
        "baseline_comparison": comparisons,
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
            "max_tokens": 64,
            **({"reasoning_effort": os.getenv("LLM_REASONING_EFFORT", "none")}
               if urlsplit(BASE_URL).hostname in {"localhost", "127.0.0.1"} and urlsplit(BASE_URL).port == 11434 else {}),
            "response_format": {"type":"json_schema","json_schema":{"name":"advisor","schema":{
                "type":"array","prefixItems":[{"type":"number","minimum":0,"maximum":1},
                {"type":"number","minimum":0,"maximum":1},{"type":"string"}],"minItems":3,"maxItems":3}}},
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"].strip()

    result = _extract_json(content)
    if isinstance(result,list) and len(result)==3:
        result={"w":result[0],"c":result[1],"r":result[2]}
    if not isinstance(result, dict):
        raise ValueError("Local advisor did not return the required JSON schema")
    if "w" in result:
        weight=result["w"]
        if isinstance(weight,bool) or not isinstance(weight,(int,float)) or not math.isfinite(weight) or not 0<=weight<=1:
            raise ValueError("Invalid advisor weight")
        fused=weight*payload["watch_score"]+(1-weight)*payload["vision_score"]
        return {"fused_score":fused,"action":_action_from_score(fused),
                "reason":result.get("r"),"weights":{"watch":weight,"vision":1-weight},
                "confidence":result.get("c")}
    # Keep compatibility with a server returning the original full schema.
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