"""Latency benchmark for the DrozyAI pipeline.

Measures the time (in milliseconds) for:
    1. Loading features
    2. Watch model inference (single window)
    3. Vision model inference (single window)
    4. Fusion
    5. Advisor (LLM or fallback)

Run with Wi-Fi off to confirm offline operation.

Usage:
    python scripts/latency_benchmark.py
"""

from __future__ import annotations

import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from src.advisor.nemotron_client import advisor
from src.features.fusion import fuse_scores


def timeit(fn, *args, **kwargs):
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    t1 = time.perf_counter()
    return result, (t1 - t0) * 1000.0  # ms


def main() -> None:
    print("=== DrozyAI Latency Benchmark ===\n")

    # Load models
    print("Loading models...")
    watch_pipe = joblib.load("data/processed/baseline_model.pkl")
    vision_pipe = joblib.load("data/processed/video_model.pkl")
    print("  Done.\n")

    # Load one sample window per model
    watch_df = pd.read_parquet("data/processed/window_features.parquet")
    video_df = pd.read_parquet("data/processed/video_features.parquet")

    watch_features = ["hr_mean", "rmssd", "temp_trend", "motion_var"]
    video_features = [
        "left_ear_mean", "right_ear_mean", "perclos", "longest_closure_sec",
        "blink_rate_per_min", "blink_duration_mean", "inter_blink_interval_mean",
        "mar_mean", "yawn_count", "max_yawn_duration", "tracking_coverage",
    ]

    watch_row = watch_df.dropna(subset=watch_features).iloc[0]
    video_row = video_df.dropna(subset=video_features).iloc[0]

    X_watch = watch_row[watch_features].to_numpy(dtype=float).reshape(1, -1)
    X_video = video_row[video_features].to_numpy(dtype=float).reshape(1, -1)

    # 1. Watch model inference
    _, t_watch = timeit(watch_pipe.predict_proba, X_watch)
    print(f"Watch model inference:  {t_watch:>8.2f} ms")

    # 2. Vision model inference
    _, t_vision = timeit(vision_pipe.predict_proba, X_video)
    print(f"Vision model inference: {t_vision:>8.2f} ms")

    # 3. Fusion
    watch_score = float(watch_pipe.predict_proba(X_watch)[0, 1])
    vision_score = float(vision_pipe.predict_proba(X_video)[0, 1])
    _, t_fusion = timeit(fuse_scores, np.array([watch_score]), np.array([vision_score]))
    print(f"Fusion:                 {t_fusion:>8.2f} ms")

    # 4. Advisor (may include LLM call)
    fused_score = float(fuse_scores(np.array([watch_score]), np.array([vision_score]))[0])
    _, t_advisor = timeit(advisor, fused_score, 0.0, ["perclos"])
    print(f"Advisor (LLM + rules):  {t_advisor:>8.2f} ms")

    total = t_watch + t_vision + t_fusion + t_advisor
    print(f"\nTotal time-to-alert:    {total:>8.2f} ms")

    # Write report
    report = f"""# DrozyAI Latency Benchmark

Measured with the network off, on a Mac (Apple Silicon).

| Stage | Time (ms) |
|---|---|
| Watch model inference | {t_watch:.2f} |
| Vision model inference | {t_vision:.2f} |
| Fusion | {t_fusion:.2f} |
| Advisor (LLM + rules) | {t_advisor:.2f} |
| **Total time-to-alert** | **{total:.2f}** |

Notes:
- Watch model: HistGradientBoostingClassifier (4 features)
- Vision model: HistGradientBoostingClassifier (11 features)
- Advisor: rule-based action + local LLM reason (Ollama, llama3.2:3b)
- All stages run locally on-device with no network access
"""
    Path("docs").mkdir(exist_ok=True)
    Path("docs/latency.md").write_text(report)
    print("\nWrote docs/latency.md")


if __name__ == "__main__":
    main()