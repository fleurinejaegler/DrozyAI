"""Rule-based fallback advisor.

Used when the local LLM (Ollama / Nemotron) is unavailable or returns
invalid output. Also serves as the ground-truth baseline for the LLM
advisor.

Input:
    risk_score   : float in [0, 1]
    trend        : float, signed change in risk over the last 10 minutes
    top_signals  : list of strings, names of the strongest contributors

Output:
    {"action": ..., "reason": ...}

Actions:
    "stop now"
    "take a break at the next rest area"
    "continue"
"""

from __future__ import annotations

from typing import Any, Mapping

VALID_ACTIONS = {
    "stop now",
    "take a break at the next rest area",
    "continue",
}


def rule_based_advisor(
    risk_score: float,
    trend: float = 0.0,
    top_signals: list[str] | None = None,
) -> dict[str, str]:
    """Deterministic rule-based advisor."""
    top_signals = top_signals or []

    # High risk -> stop now
    if risk_score >= 0.75:
        return {
            "action": "stop now",
            "reason": (
                f"Drowsiness risk is very high ({risk_score:.2f}). "
                "Stop as soon as it is safe to do so."
            ),
        }

    # Rising risk + moderate score -> take a break
    if risk_score >= 0.50 and trend > 0.0:
        return {
            "action": "take a break at the next rest area",
            "reason": (
                f"Drowsiness risk is rising (score {risk_score:.2f}, "
                f"trend +{trend:.2f}). Plan a break soon."
            ),
        }

    # Moderate score, flat or falling -> take a break
    if risk_score >= 0.50:
        return {
            "action": "take a break at the next rest area",
            "reason": (
                f"Drowsiness risk is moderate ({risk_score:.2f}). "
                "A short break will help."
            ),
        }

    # Otherwise -> continue
    return {
        "action": "continue",
        "reason": (
            f"Drowsiness risk is low ({risk_score:.2f}). "
            "Keep monitoring."
        ),
    }


def validate_advisor_output(output: Any) -> bool:
    """Check that the LLM output is a dict with a valid action."""
    if not isinstance(output, Mapping):
        return False
    if "action" not in output or "reason" not in output:
        return False
    if output["action"] not in VALID_ACTIONS:
        return False
    if not isinstance(output["reason"], str) or not output["reason"].strip():
        return False
    return True


# ----------------------------------------------------------------------
# CLI demo
# ----------------------------------------------------------------------
if __name__ == "__main__":
    samples = [
        {"risk_score": 0.85, "trend": 0.10, "top_signals": ["perclos"]},
        {"risk_score": 0.60, "trend": 0.15, "top_signals": ["rmssd"]},
        {"risk_score": 0.55, "trend": -0.05, "top_signals": ["ear_mean"]},
        {"risk_score": 0.20, "trend": 0.00, "top_signals": []},
    ]
    for s in samples:
        result = rule_based_advisor(**s)
        print(f"risk={s['risk_score']:.2f} trend={s['trend']:+.2f} -> {result['action']}")
        print(f"  reason: {result['reason']}")
        print()