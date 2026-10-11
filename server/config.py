from dataclasses import dataclass
from pathlib import Path
import os
import secrets


@dataclass(frozen=True)
class Config:
    token: str
    data_dir: Path
    window_seconds: float = 60.0
    min_intervals: int = 30
    min_window_seconds: float = 30.0
    gap_seconds: float = 3.0
    max_body_bytes: int = 65536

    def __post_init__(self):
        if len(self.token) < 12:
            raise ValueError("GARMIN_API_TOKEN must have at least 12 characters")
        if not (0 < self.min_window_seconds <= self.window_seconds <= 300):
            raise ValueError("Invalid HRV window settings")
        if not (2 <= self.min_intervals <= 1000) or not (0 < self.gap_seconds <= 10):
            raise ValueError("Invalid HRV interval settings")

    @classmethod
    def from_env(cls):
        token = os.getenv("GARMIN_API_TOKEN")
        if not token:
            token = secrets.token_urlsafe(12)
            print(f"Temporary watch API token: {token}", flush=True)
            print("Enter it in the watch's Upload token menu; it changes after restart.", flush=True)
        return cls(
            token=token,
            data_dir=Path(os.getenv("GARMIN_DATA_DIR", "server/data")),
            window_seconds=float(os.getenv("GARMIN_HRV_WINDOW_SECONDS", "60")),
            min_intervals=int(os.getenv("GARMIN_HRV_MIN_INTERVALS", "30")),
            min_window_seconds=float(os.getenv("GARMIN_HRV_MIN_SPAN_SECONDS", "30")),
        )
