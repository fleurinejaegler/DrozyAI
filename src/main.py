"""DrozyAI entry point.

Currently runs the Person 1 pipeline: build the aligned per-second
dataset from the raw UL-DD files.
"""

from __future__ import annotations

from src.data.build_dataset import main as build_dataset


def main() -> None:
    print("=== DrozyAI: building aligned per-second dataset ===")
    build_dataset()


if __name__ == "__main__":
    main()