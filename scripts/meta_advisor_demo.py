"""End-to-end demo of the LLM meta-advisor.

Picks three real windows (one per risk band), sends each through the
meta-advisor with real features, real driver baseline, and real recent
risk history, and prints the driver-facing narrative.
"""

from __future__ import annotations

import time

import pandas as pd

from src.advisor.llm_meta_advisor import meta_advisor


TRAFFIC_COLOR = {
    "green": "\033[92m",
    "orange": "\033[93m",
    "red": "\033[91m",
}
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


def traffic_light(score: float) -> str:
    if score < 0.4:
        return "green"
    if score < 0.7:
        return "orange"
    return "red"


def print_warning(risk: float, result: dict) -> None:
    light = traffic_light(risk)
    color = TRAFFIC_COLOR[light]
    weights = result.get("weights", {})
    print()
    print(f"{color}{BOLD}{'=' * 68}{RESET}")
    print(f"{color}{BOLD}  {light.upper():<8}{RESET}"
          f"  fused={risk:.2f}"
          f"  weights(watch={weights.get('watch', 0):.2f},"
          f" vision={weights.get('vision', 0):.2f})"
          f"  confidence={result.get('confidence', 0):.2f}")
    print(f"{color}{BOLD}{'=' * 68}{RESET}")
    print(f"  {BOLD}ACTION:{RESET} {result['action']}")
    print(f"  {BOLD}STORY:{RESET}  {result['reason']}")
    print(f"  {DIM}(source: {result.get('source', 'unknown')}){RESET}")


def main() -> None:
    print("Loading fused scores, feature tables, and baselines ...")
    fused = pd.read_parquet("data/processed/fused_scores.parquet")
    watch = pd.read_parquet("data/processed/window_features.parquet")
    video = pd.read_parquet("data/processed/video_features.parquet")
    base = pd.read_parquet("data/processed/driver_baselines.parquet")

    # Pick three windows across the risk spectrum
    fused_sorted = fused.sort_values("fused_score").reset_index(drop=True)
    picks = []
    for lo, hi, label in [
        (0.0, 0.4, "low risk"),
        (0.4, 0.7, "medium risk"),
        (0.7, 1.0, "high risk"),
    ]:
        band = fused_sorted[
            (fused_sorted["fused_score"] >= lo) & (fused_sorted["fused_score"] < hi)
        ]
        if len(band):
            picks.append((label, band.iloc[len(band) // 2]))

    for label, row in picks:
        subj, sess, ws = row["subject"], row["session"], int(row["window_start"])

        # Pull matching rows
        wrow = watch[
            (watch["subject"] == subj)
            & (watch["session"] == sess)
            & (watch["window_start"] == ws)
        ]
        vrow = video[
            (video["subject"] == subj)
            & (video["session"] == sess)
            & (video["window_start"] == ws)
        ]
        brow = base[(base["subject"] == subj) & (base["session"] == sess)]

        watch_feats = wrow.iloc[0].to_dict() if len(wrow) else {}
        vision_feats = vrow.iloc[0].to_dict() if len(vrow) else {}
        baseline = brow.iloc[0].to_dict() if len(brow) else {}

        # Recent risk history: last 10 fused scores for this session
        recent = fused[
            (fused["subject"] == subj) & (fused["session"] == sess)
            & (fused["window_start"] <= ws)
        ].sort_values("window_start").tail(10)["fused_score"].tolist()

        print(f"\n{'-' * 68}")
        print(f"  Example: {label}")
        print(f"  {subj}/{sess} @ {ws}s  (true label={int(row['label'])})")
        print(f"{'-' * 68}")

        t0 = time.perf_counter()
        result = meta_advisor(
            watch_score=float(row["watch_score"]),
            vision_score=float(row["vision_score"]),
            watch_features=watch_feats,
            vision_features=vision_feats,
            baseline=baseline,
            recent_risk=recent,
        )
        dt = (time.perf_counter() - t0) * 1000
        print_warning(float(result["fused_score"]), result)
        print(f"  {DIM}Advisor latency: {dt:.1f} ms{RESET}")


if __name__ == "__main__":
    main()