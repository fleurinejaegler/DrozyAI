"""Extension points ONLY. User-supplied models and preprocessing come later."""
from dataclasses import dataclass
from typing import Protocol

from .schemas import Prediction, Stream
from .streams import Observation


@dataclass(frozen=True)
class AdapterSpec:
    model_id: str
    version: str
    modality: str
    target_id: str
    input_schema_id: str
    feature_order: tuple[str, ...]
    units: tuple[str, ...]
    missing_value_policy: str
    preprocessing_version: str
    window_seconds: float

    def __post_init__(self):
        if self.modality not in ('watch', 'video') or self.window_seconds <= 0:
            raise ValueError('Invalid adapter modality or window')
        if not self.feature_order or len(set(self.feature_order)) != len(self.feature_order):
            raise ValueError('Explicit unique training feature order is required')
        if len(self.units) != len(self.feature_order):
            raise ValueError('Provide the training units for every feature')
        if not all((self.model_id, self.version, self.target_id, self.input_schema_id,
                    self.missing_value_policy, self.preprocessing_version)):
            raise ValueError('Provide the complete training/preprocessing contract')


@dataclass(frozen=True)
class InputWindow:
    stream: Stream
    modality: str
    start_ms: int
    end_ms: int
    observations: tuple[Observation, ...]
    aligned_timestamps_ms: tuple[int, ...]
    clock_uncertainty_ms: float
    input_schema_id: str


class ModelAdapter(Protocol):
    spec: AdapterSpec

    def predict(self, window: InputWindow) -> Prediction | None:
        """Apply the supplied training preprocessing, then infer; None means insufficient data."""
        ...


class ModelSlots:
    def __init__(self, watch: ModelAdapter | None = None, video: ModelAdapter | None = None):
        self.adapters = {'watch': watch, 'video': video}
        for modality, adapter in self.adapters.items():
            if adapter is not None and adapter.spec.modality != modality:
                raise ValueError('Adapter supplied to the wrong model slot')

    def status(self):
        return {name: ({'status': 'MODEL_NOT_CONFIGURED', 'model_id': None, 'version': None}
                       if adapter is None else
                       {'status': 'configured', 'model_id': adapter.spec.model_id,
                        'version': adapter.spec.version, 'window_seconds': adapter.spec.window_seconds,
                        'input_schema_id': adapter.spec.input_schema_id})
                for name, adapter in self.adapters.items()}
