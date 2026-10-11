"""Late fusion of future adapter outputs; no trained models or fake predictions."""
from dataclasses import dataclass

from .config import Settings
from .schemas import Prediction


@dataclass(frozen=True)
class Verdict:
    raw_label: str
    label: str
    score: float | None
    mode: str
    reason: str
    prediction_timestamp_ms: int | None
    valid_for_ms: int
    source_key: tuple


def fresh(prediction: Prediction | None, now: int, settings: Settings):
    return (prediction is not None and
            0 <= now - prediction.generated_at_ms <= settings.max_prediction_age_ms and
            0 <= now - prediction.window_end_ms <= settings.max_prediction_age_ms and
            prediction.clock_uncertainty_ms is not None and
            prediction.clock_uncertainty_ms <= settings.max_clock_uncertainty_ms)


def unavailable(reason):
    return Verdict('INSUFFICIENT_DATA', 'INSUFFICIENT_DATA', None, 'none', reason, None, 0, ())


def fuse(watch, video, video_enabled, now, settings, score_fuser=None):
    if not fresh(watch, now, settings):
        return unavailable('WATCH_UNAVAILABLE_OR_STALE')
    # The watch is required. No implicit video-only mode.
    selected, mode, reason = [watch], 'watch_only', 'WATCH_ONLY'
    if video_enabled and fresh(video, now, settings):
        same_stream = (watch.device_id, watch.session_id, watch.data_origin) == (
            video.device_id, video.session_id, video.data_origin)
        overlap = max(0, min(watch.window_end_ms, video.window_end_ms) -
                      max(watch.window_start_ms, video.window_start_ms))
        shorter = min(watch.window_end_ms - watch.window_start_ms,
                      video.window_end_ms - video.window_start_ms)
        compatible = (same_stream and watch.target_id == video.target_id and
                      abs(watch.window_end_ms - video.window_end_ms) <= settings.max_window_end_skew_ms and
                      overlap / shorter >= settings.min_window_overlap)
        calibrated = all(p.score_kind == 'calibrated_probability' for p in (watch, video))
        if compatible and calibrated:
            selected, mode, reason = [watch, video], 'watch_video', 'CALIBRATED_LATE_FUSION'
        else:
            reason = 'VIDEO_INCOMPATIBLE' if not compatible else 'VIDEO_SCORES_NOT_CALIBRATED'
    elif video_enabled:
        reason = 'VIDEO_UNAVAILABLE_OR_STALE'
    if len(selected) == 2:
        if score_fuser is None:
            score = settings.watch_weight * watch.score + (1 - settings.watch_weight) * video.score
        else:
            score = float(score_fuser(watch.score, video.score, method='weighted',
                                      watch_weight=settings.watch_weight))
            if not 0 <= score <= 1:
                return unavailable('INVALID_FUSION_OUTPUT')
        label = 'DROWSY' if score >= settings.fusion_threshold else 'ALERT'
    else:
        label = watch.label  # Preserve the adapter's own trained decision threshold.
        score = watch.score if watch.score_kind == 'calibrated_probability' else None
    expires = min(min(p.generated_at_ms, p.window_end_ms) + settings.max_prediction_age_ms for p in selected)
    # Conservative clock uncertainty reduces how long the watch may retain the result.
    expires -= max(p.clock_uncertainty_ms for p in selected)
    if expires <= now:
        return unavailable('PREDICTION_EXPIRED_WITH_CLOCK_UNCERTAINTY')
    key = (mode, *((p.model_id, p.model_version, p.target_id, p.window_end_ms, p.generated_at_ms) for p in selected))
    return Verdict(label, label, score, mode, reason,
                   max(p.generated_at_ms for p in selected), int(expires - now), key)


class Confirmer:
    """Count distinct inference windows, never repeated HTTP reads."""
    def __init__(self, count):
        self.required = count
        self.reset()

    def reset(self):
        self.confirmed = self.candidate = self.last_key = self.context = None
        self.count = 0

    def apply(self, verdict):
        if verdict.raw_label == 'INSUFFICIENT_DATA':
            self.reset()
            return verdict
        context = (verdict.mode, tuple((k[0], k[1], k[2]) for k in verdict.source_key[1:]))
        if context != self.context:
            self.reset()
            self.context = context
        if verdict.source_key != self.last_key:
            # A newly generated output over the same window cannot add confirmation.
            distinct_window = (self.last_key is None or
                               tuple(k[3] for k in verdict.source_key[1:]) !=
                               tuple(k[3] for k in self.last_key[1:]))
            if distinct_window:
                if verdict.raw_label == self.candidate:
                    self.count += 1
                else:
                    self.candidate, self.count = verdict.raw_label, 1
                if self.count >= self.required:
                    self.confirmed = self.candidate
            self.last_key = verdict.source_key
        label = self.confirmed or 'PROCESSING'
        return Verdict(verdict.raw_label, label, verdict.score, verdict.mode,
                       verdict.reason if label == verdict.raw_label else 'WAITING_FOR_CONFIRMATION',
                       verdict.prediction_timestamp_ms, verdict.valid_for_ms, verdict.source_key)
