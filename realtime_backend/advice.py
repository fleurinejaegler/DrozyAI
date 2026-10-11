"""Validation wrapper for existing advisors. Never called without fresh risk data.

The eventual caller must run slow LLM calls separately from inference and discard
late results. This wrapper does not install/start/call an LLM by itself.
"""
import math
from numbers import Real

ACTIONS = {'continue', 'take a break at the next rest area', 'stop now'}
WATCH_KEYS = {'hr_mean', 'rmssd', 'temp_trend', 'motion_var'}
VISION_KEYS = {'perclos', 'blink_rate_per_min', 'longest_closure_sec',
               'left_ear_mean', 'right_ear_mean', 'yawn_count'}


def numeric(value, lo=None, hi=None):
    return (not isinstance(value, bool) and isinstance(value, Real) and math.isfinite(value) and
            (lo is None or value >= lo) and (hi is None or value <= hi))


def checked_rule(fallback, score, trend, top_signals):
    output = fallback(score, trend=trend, top_signals=top_signals)
    if (not isinstance(output, dict) or output.get('action') not in ACTIONS or
        not isinstance(output.get('reason'), str) or not output['reason'].strip()):
        raise ValueError('Invalid deterministic advisor contract')
    return output


def advise(*, watch_score, vision_score=None, watch_features=None, vision_features=None,
           baseline=None, recent_risk=None, trend=0.0, top_signals=None, fresh=True,
           fallback, meta_advisor=None, score_fuser=None, required_vision_keys=None):
    if not fresh or not numeric(watch_score, 0, 1):
        return {'action': None, 'reason': 'Insufficient fresh model data',
                'source': 'unavailable', 'fused_score': None, 'confidence': None}
    if vision_score is not None and not numeric(vision_score, 0, 1):
        vision_score = None
    if not numeric(trend):
        trend = 0.0
    top_signals = [s for s in (top_signals or []) if isinstance(s, str)][:20]
    def combine(weight):
        return float(score_fuser(watch_score, vision_score, method='weighted', watch_weight=weight)
                     if score_fuser else weight * watch_score + (1 - weight) * vision_score)
    score = watch_score if vision_score is None else combine(0.5)
    result = {**checked_rule(fallback, score, trend, top_signals), 'fused_score': score,
              'weights': {'watch': 1.0 if vision_score is None else 0.5,
                          'vision': 0.0 if vision_score is None else 0.5},
              'confidence': None, 'source': 'fallback', 'score_kind': 'uncalibrated_score'}
    if meta_advisor is None or vision_score is None:
        return result
    watch_features, vision_features = watch_features or {}, vision_features or {}
    # Supply complete finite feature context to the advisor; never replace
    # unavailable measurements with fabricated numeric values.
    if (not all(k in watch_features and numeric(watch_features[k]) for k in WATCH_KEYS) or
        not all(k in vision_features and numeric(vision_features[k]) for k in (VISION_KEYS if required_vision_keys is None else required_vision_keys))):
        return {**result, 'source': 'fallback_missing_llm_features'}
    try:
        history = [float(v) for v in (recent_risk or [])[-10:] if numeric(v, 0, 1)]
        output = meta_advisor(watch_score, vision_score, watch_features, vision_features,
                              baseline or {}, history)
        if output.get('source','llm') != 'llm':
            return {**result, 'source':output.get('source','fallback')}
        weights = output['weights']
        a, b = weights['watch'], weights['vision']
        confidence = output['confidence']
        if (not numeric(a, 0, 1) or not numeric(b, 0, 1) or abs(a + b - 1) > 1e-6 or
            not numeric(confidence, 0, 1) or output.get('action') not in ACTIONS or
            not isinstance(output.get('reason'), str) or not output['reason'].strip()):
            raise ValueError('Invalid meta-advisor output')
        score = combine(a)  # Ignore LLM arithmetic; Python recomputes it.
        if not numeric(score, 0, 1):
            raise ValueError('Invalid recomputed fused score')
        rule = checked_rule(fallback, score, trend, top_signals)
        # Use the same action thresholds everywhere; a story for a different
        # action is discarded instead of attached to a contradictory action.
        reason = output['reason'] if output['action'] == rule['action'] else rule['reason']
        return {**rule, 'reason': reason, 'fused_score': score, 'weights': {'watch': a, 'vision': b},
                'confidence': confidence, 'confidence_kind': 'llm_self_reported',
                'source': output.get('source', 'llm'), 'score_kind': 'uncalibrated_score'}
    except Exception:
        return {**result, 'source': 'fallback_invalid_or_failed_llm'}
