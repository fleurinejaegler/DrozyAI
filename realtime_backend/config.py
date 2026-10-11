from dataclasses import dataclass
from pathlib import Path
import math
import os


@dataclass(frozen=True)
class Settings:
    inference_interval_s: float = 5.0
    max_prediction_age_ms: int = 10_000
    max_window_end_skew_ms: int = 2_000
    max_clock_uncertainty_ms: int = 1_000
    min_window_overlap: float = 0.5
    watch_weight: float = 0.5
    fusion_threshold: float = 0.5
    confirmation_windows: int = 1
    buffer_seconds: int = 600
    max_samples_per_source: int = 30_000
    max_streams: int = 8
    max_body_bytes: int = 512_000
    relay_poll_interval_s: float = 1.0
    log_directory: Path = Path(__file__).resolve().parent / 'data'

    def __post_init__(self):
        for name in ('inference_interval_s', 'max_prediction_age_ms', 'buffer_seconds',
                     'max_samples_per_source', 'max_streams', 'max_body_bytes',
                     'confirmation_windows', 'max_clock_uncertainty_ms', 'relay_poll_interval_s'):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be positive and finite')
        for name in ('watch_weight', 'fusion_threshold', 'min_window_overlap'):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f'{name} must be between zero and one')

    @classmethod
    def from_env(cls):
        return cls(
            inference_interval_s=float(os.getenv('DROZY_INFERENCE_INTERVAL_S', '5')),
            max_prediction_age_ms=int(os.getenv('DROZY_MAX_PREDICTION_AGE_MS', '10000')),
            watch_weight=float(os.getenv('DROZY_WATCH_WEIGHT', '0.5')),
            fusion_threshold=float(os.getenv('DROZY_FUSION_THRESHOLD', '0.5')),
            confirmation_windows=int(os.getenv('DROZY_CONFIRMATION_WINDOWS', '1')),
            log_directory=Path(os.getenv('DROZY_LOG_DIRECTORY', str(cls().log_directory))),
        )
