"""Causal, webcam-reproducible video event features from 68-point landmarks.

Source files are read only. Events are extracted at frame resolution before
one-second aggregation. All time windows use past data, never future frames.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FeatureConfig:
    fps: int = 60
    session_seconds: int = 2400
    calibration_seconds: int = 15
    window_seconds: int = 60
    stride_seconds: int = 5
    eye_close_ratio: float = 0.65
    eye_reopen_ratio: float = 0.75
    blink_min_seconds: float = 0.08
    blink_max_seconds: float = 0.8
    mouth_open_ratio: float = 0.60
    mouth_reclose_ratio: float = 0.45
    mouth_event_min_seconds: float = 1.0
    window_min_coverage: float = 0.90
    second_min_coverage: float = 0.50


CHANNELS = ["left_eye_openness", "right_eye_openness", "eye_closed_fraction",
            "long_closure_fraction", "closure_age_seconds", "long_closure_count",
            "blink_count", "blink_duration_sum_seconds", "blink_duration_max_seconds",
            "mouth_ratio", "mouth_open_fraction", "mouth_age_seconds",
            "mouth_event_count", "mouth_duration_sum_seconds", "valid_fraction"]
FEATURES = ["left_eye_mean", "left_eye_variability", "right_eye_mean", "right_eye_variability",
            "eye_asymmetry_mean", "eye_closed_fraction", "long_closure_fraction",
            "longest_closure_seconds", "long_closures_per_minute", "blinks_per_minute",
            "blink_duration_mean_seconds", "blink_duration_max_seconds",
            "interblink_interval_mean_seconds", "mouth_ratio_mean", "mouth_ratio_variability",
            "mouth_open_fraction", "longest_mouth_open_seconds", "mouth_events_per_minute",
            "mouth_event_duration_mean_seconds", "valid_frame_fraction",
            "eye_closure_trend", "mouth_open_trend"]


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def landmark_ratios(raw):
    """EAR for each eye and inner-mouth aspect ratio, invariant to image scale."""
    def point(i):
        return raw[[f"X{i}", f"Y{i}"]].to_numpy(dtype=float)
    def distance(a, b):
        return np.linalg.norm(point(a) - point(b), axis=1)
    def divide(a, b):
        return np.divide(a, b, out=np.full(len(raw), np.nan), where=b > 1e-6)
    left = divide(distance(38, 42) + distance(39, 41), 2 * distance(37, 40))
    right = divide(distance(44, 48) + distance(45, 47), 2 * distance(43, 46))
    mouth = divide(distance(62, 68) + distance(63, 67) + distance(64, 66), 3 * distance(61, 65))
    return np.column_stack([left, right, mouth])


def frame_events(left, right, mouth, valid, config):
    """Hysteresis state machines; invalid frames break runs and censor events.

    A blink is counted only when reopening is observed. An ongoing closure's
    age is available immediately, but its final duration is never backfilled.
    """
    fps = config.fps
    values = np.zeros((len(left), len(CHANNELS)), dtype=np.float32)
    values[:, 0] = np.where(valid, left, 0)
    values[:, 1] = np.where(valid, right, 0)
    values[:, 9] = np.where(valid, mouth, 0)
    values[:, 14] = valid
    eye_start = mouth_start = None
    eye_censored = mouth_censored = True
    blink_ends = []
    for i in range(len(left)):
        if not valid[i]:
            eye_start = mouth_start = None
            eye_censored = mouth_censored = True
            continue
        if eye_start is None:
            if max(left[i], right[i]) < config.eye_close_ratio:
                eye_start = i
            elif min(left[i], right[i]) > config.eye_reopen_ratio:
                eye_censored = False
        elif min(left[i], right[i]) > config.eye_reopen_ratio:
            duration = (i - eye_start) / fps
            if not eye_censored and config.blink_min_seconds <= duration <= config.blink_max_seconds:
                values[i, 6:9] = [1, duration, duration]
                blink_ends.append(i / fps)
            eye_start = None
            eye_censored = False
        if eye_start is not None:
            age = (i - eye_start + 1) / fps
            values[i, 2] = 1
            values[i, 3] = age > config.blink_max_seconds
            values[i, 4] = age
            if not eye_censored and (i - eye_start) / fps <= config.blink_max_seconds < age:
                values[i, 5] = 1
        if mouth_start is None:
            if mouth[i] > config.mouth_open_ratio:
                mouth_start = i
            elif mouth[i] < config.mouth_reclose_ratio:
                mouth_censored = False
        elif mouth[i] < config.mouth_reclose_ratio:
            duration = (i - mouth_start) / fps
            if not mouth_censored and duration >= config.mouth_event_min_seconds:
                values[i, 12:14] = [1, duration]
            mouth_start = None
            mouth_censored = False
        if mouth_start is not None:
            values[i, 10] = 1
            values[i, 11] = (i - mouth_start + 1) / fps
    return values, np.asarray(blink_ends)


def aggregate_seconds(frame_values, config):
    grid = frame_values.reshape(config.session_seconds, config.fps, len(CHANNELS))
    seconds = np.zeros((config.session_seconds, len(CHANNELS)), dtype=np.float32)
    valid_count = grid[:, :, 14].sum(axis=1)
    for j in (0, 1, 2, 3, 9, 10):
        seconds[:, j] = np.divide(grid[:, :, j].sum(axis=1), valid_count,
                                   out=np.zeros(config.session_seconds), where=valid_count > 0)
    for j in (4, 8, 11):
        seconds[:, j] = grid[:, :, j].max(axis=1)
    for j in (5, 6, 7, 12, 13):
        seconds[:, j] = grid[:, :, j].sum(axis=1)
    seconds[:, 14] = valid_count / config.fps
    return seconds


def summarize_window(sequence, blink_times, start_second, config):
    """Readable tabular features; all state ages are bounded to the window size."""
    weights = sequence[:, 14]
    observed_seconds = weights.sum()
    def mean(j):
        return float(np.average(sequence[:, j], weights=weights))
    def std(j):
        return float(np.sqrt(np.average((sequence[:, j] - mean(j)) ** 2, weights=weights)))
    blink_count = sequence[:, 6].sum()
    mouth_count = sequence[:, 12].sum()
    events = blink_times[(blink_times >= start_second) & (blink_times < start_second + len(sequence))]
    half = len(sequence) // 2
    def trend(j):
        return float(np.average(sequence[half:, j], weights=weights[half:]) -
                     np.average(sequence[:half, j], weights=weights[:half]))
    result = [mean(0), std(0), mean(1), std(1),
        float(np.average(np.abs(sequence[:, 0] - sequence[:, 1]), weights=weights)),
        mean(2), mean(3), float(min(sequence[:, 4].max(), config.window_seconds)),
        float(sequence[:, 5].sum() / observed_seconds * 60),
        float(blink_count / observed_seconds * 60),
        float(sequence[:, 7].sum() / blink_count) if blink_count else 0.0,
        float(sequence[:, 8].max()), float(np.diff(events).mean()) if len(events) >= 2 else 0.0,
        mean(9), std(9), mean(10), float(min(sequence[:, 11].max(), config.window_seconds)),
        float(mouth_count / observed_seconds * 60),
        float(sequence[:, 13].sum() / mouth_count) if mouth_count else 0.0,
        float(weights.mean()), trend(2), trend(10)]
    return dict(zip(FEATURES, result))


def extract_68point_window(frames: np.ndarray) -> dict:
    """Extract the final trailing window from a 60 FPS 68-point time grid.

    Input shape is [frames, 68, 2], in image-plane coordinates, with at least
    75 complete seconds: 15 seconds of initial calibration and 60 seconds of
    history. Missing frames must occupy their original grid slot as NaNs.
    This is a feature adapter for the training landmark layout, not a direct
    adapter for the dashboard's MediaPipe blendshapes or its sparse points.
    The caller is responsible for matching the capture clock and geometry.
    """
    raw = np.asarray(frames, dtype=float)
    if raw.ndim != 3 or raw.shape[1:] != (68, 2) or len(raw) < 75 * 60 or len(raw) % 60:
        raise ValueError("Expected [N, 68, 2], with N >= 4500 and N divisible by 60")
    config = FeatureConfig(session_seconds=len(raw) // 60)
    points = [*range(37, 49), *range(61, 69)]
    table = pd.DataFrame({f"{axis}{i}": raw[:, i - 1, j]
                          for i in points for j, axis in enumerate("XY")})
    ratios = landmark_ratios(table)
    valid = np.isfinite(ratios).all(axis=1)
    valid &= (ratios[:, :2] > 0.02).all(axis=1) & (ratios[:, :2] < 1.0).all(axis=1)
    valid &= (ratios[:, 2] >= 0) & (ratios[:, 2] <= 2.0)
    warmup = config.calibration_seconds * config.fps
    if valid[:warmup].sum() < 0.8 * warmup:
        raise ValueError("Insufficient initial calibration coverage")
    reference = np.quantile(ratios[:warmup, :2][valid[:warmup]], 0.9, axis=0)
    if (reference < 0.1).any():
        raise ValueError("Implausible eye calibration reference")
    eyes = np.clip(ratios[:, :2] / reference, 0, 2)
    events, blink_times = frame_events(eyes[:, 0], eyes[:, 1], ratios[:, 2], valid, config)
    seconds = aggregate_seconds(events, config)
    seconds[:, [4, 11]] = np.minimum(seconds[:, [4, 11]], config.window_seconds)
    window = seconds[-config.window_seconds:]
    if window[:, 14].mean() < config.window_min_coverage or window[:, 14].min() < config.second_min_coverage:
        raise ValueError("Insufficient observed coverage in trailing window")
    start_second = len(seconds) - config.window_seconds
    return {"channels": list(CHANNELS), "sequence": window.T.tolist(),
            "features": summarize_window(window, blink_times, start_second, config)}
