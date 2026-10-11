"""End-to-end LLM advisor demo.

Picks a few real windows from the fused score table, sends each one
through the local LLM advisor, and prints the driver-facing warning
exactly as it would appear on screen.

Run with the local Ollama server on.

Usage:
    python -m scripts.llm_demo
"""

from __future__ import annotations

import time

import pandas as pd

from src.advisor.nemotron_client import advisor


# ----------------------------------------------------------------------
# Pretty-print helpers
# ----------------------------------------------------------------------
TRAFFIC_COLOR = {
    "green": "\033[92m",    # bright green
    "orange": "\033[93m",   # bright yellow
    "red": "\033[91m",      # bright red
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


def print_warning(row: pd.Series, result: dict) -> None:
    """Print the driver-facing warning the way the app would show it."""
    light = traffic_light(row["fused_score"])
    color = TRAFFIC_COLOR[light]

    # Big colored banner (mimics the driver app screen)
    print()
    print(f"{color}{BOLD}{'=' * 60}{RESET}")
    print(f"{color}{BOLD}  {light.upper():<12}{RESET}   "
          f"risk = {row['fused_score']:.2f}   "
          f"(watch {row['watch_score']:.2f} | vision {row['vision_score']:.2f})")
    print(f"{color}{BOLD}{'=' * 60}{RESET}")
    print()
    print(f"  {BOLD}ACTION:{RESET} {result['action']}")
    print()
    print(f"  {BOLD}REASON:{RESET} {result['reason']}")
    print()
    print(f"  {DIM}(source: {result.get('source', 'unknown')}){RESET}")
    print()


# ----------------------------------------------------------------------
# Main demo
# ----------------------------------------------------------------------
def main() -> None:
    print("=" * 60)
    print("  DrozyAI — LLM Advisor Demo")
    print("=" * 60)

    # Load the fused scores
    df = pd.read_parquet("data/processed/fused_scores.parquet")

    # Pick a few interesting rows across the risk spectrum
    # Sort by fused_score and take one from each band
    df_sorted = df.sort_values("fused_score").reset_index(drop=True)
    picks = []
    for lo, hi, label in [
        (0.0, 0.4, "low risk (green)"),
        (0.4, 0.7, "medium risk (orange)"),
        (0.7, 1.0, "high risk (red)"),
    ]:
        band = df_sorted[(df_sorted["fused_score"] >= lo) & (df_sorted["fused_score"] < hi)]
        if len(band) > 0:
            row = band.iloc[len(band) // 2]   # median of the band
            picks.append((label, row))

    print(f"\nShowing {len(picks)} examples across the risk spectrum.\n")

    for label, row in picks:
        print(f"\n{'-' * 60}")
        print(f"  Example: {label}")
        print(f"  {row['subject']}/{row['session']} @ "
              f"{int(row['window_start'])}s  "
              f"(true label = {int(row['label'])})")
        print(f"{'-' * 60}")

        # Measure how long the LLM call takes
        t0 = time.perf_counter()
        result = advisor(
            risk_score=float(row["fused_score"]),
            trend=0.0,   # we do not compute trend in this demo
            top_signals=["perclos", "rmssd"],
        )
        dt_ms = (time.perf_counter() - t0) * 1000

        print_warning(row, result)
        print(f"  {DIM}Advisor latency: {dt_ms:.1f} ms{RESET}")


if __name__ == "__main__":
    main()