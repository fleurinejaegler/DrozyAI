"""Build the aligned per-second dataset for all UL-DD subjects and sessions.

For each (subject, session) pair:

1. Loads and aligns the raw signals using src.data.loader.load_session.
2. Saves one Parquet file per session under data/processed/.
3. Concatenates everything into a single Parquet file for quick loading.

Usage:
    python -m src.data.build_dataset
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.loader import list_sessions, load_session


RAW_ROOT = Path("data/raw/CSV_Files/CSV_Files")
OUT_ROOT = Path("data/processed")


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    pairs = list_sessions(RAW_ROOT)
    print(f"Found {len(pairs)} sessions.")

    frames = []
    for i, (user, session) in enumerate(pairs, start=1):
        print(f"[{i}/{len(pairs)}] {user}/{session} ...", end=" ")
        try:
            df = load_session(user, session, RAW_ROOT)
        except FileNotFoundError as exc:
            print(f"SKIP ({exc})")
            continue
        df.to_parquet(OUT_ROOT / f"{user}_{session}.parquet", index=False)
        frames.append(df)
        print(f"OK ({len(df)} rows)")

    if not frames:
        print("No sessions loaded. Nothing to write.")
        return

    full = pd.concat(frames, ignore_index=True)
    full.to_parquet(OUT_ROOT / "full_dataset.parquet", index=False)
    print(f"\nWrote {len(full)} total rows to {OUT_ROOT / 'full_dataset.parquet'}")

    print("\nLabel distribution:")
    print(full.groupby("drowsy").size())

    print("\nSessions:")
    print(full.groupby(["subject", "session"]).size())


if __name__ == "__main__":
    main()