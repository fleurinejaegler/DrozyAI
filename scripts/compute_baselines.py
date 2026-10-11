"""Compute per-driver baselines from the first 5 minutes of each session.

Output:
    data/processed/driver_baselines.parquet
        One row per (subject, session), with mean and std for each feature.

Usage:
    python -m scripts.compute_baselines
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


BASELINE_SECONDS = 300  # first 5 minutes

WATCH_FEATURES = ["hr_mean", "rmssd", "temp_trend", "motion_var"]

VIDEO_FEATURES = [
    "left_ear_mean", "right_ear_mean", "perclos", "longest_closure_sec",
    "blink_rate_per_min", "blink_duration_mean", "inter_blink_interval_mean",
    "mar_mean", "yawn_count", "max_yawn_duration", "tracking_coverage",
]


def main() -> None:
    print("Loading feature tables ...")
    watch = pd.read_parquet("data/processed/window_features.parquet")
    video = pd.read_parquet("data/processed/video_features.parquet")

    # For each (subject, session), take windows whose window_start is in
    # the first BASELINE_SECONDS seconds.
    def baseline_stats(df, features, prefix):
        rows = []
        for (subj, sess), group in df.groupby(["subject", "session"]):
            base = group[group["window_start"] < BASELINE_SECONDS]
            if len(base) == 0:
                continue
            row = {"subject": subj, "session": sess}
            for f in features:
                col = base[f].dropna()
                row[f"{prefix}_{f}_mean"] = float(col.mean()) if len(col) else float("nan")
                row[f"{prefix}_{f}_std"] = float(col.std()) if len(col) > 1 else 0.0
            rows.append(row)
        return pd.DataFrame(rows)

    print("Computing watch baselines ...")
    wb = baseline_stats(watch, WATCH_FEATURES, "w")

    print("Computing video baselines ...")
    vb = baseline_stats(video, VIDEO_FEATURES, "v")

    print("Merging ...")
    baselines = wb.merge(vb, on=["subject", "session"], how="outer")

    out = Path("data/processed/driver_baselines.parquet")
    baselines.to_parquet(out, index=False)
    print(f"Wrote {out} ({len(baselines)} rows)")


if __name__ == "__main__":
    main()