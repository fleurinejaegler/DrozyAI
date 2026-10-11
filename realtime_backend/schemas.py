"""Transport contracts, independent of the eventual model feature schemas."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9_.:-]+$')]
Millis = Annotated[int, Field(strict=True, ge=0)]
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Values = Annotated[dict[Identifier, Number | None], Field(min_length=1, max_length=64)]
Origin = Literal['live', 'synthetic_test']
Label = Literal['ALERT', 'DROWSY']


class Message(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class Stream(Message):
    device_id: Identifier
    session_id: Identifier
    data_origin: Origin = 'live'


class WatchSample(Message):
    sensor: Literal['heart_rate', 'acceleration', 'ibi', 'temperature']
    device_time_ms: Millis
    values: Values
    unit: Literal['bpm', 'g', 'm/s2', 's', 'degC']
    sampling_hz: Annotated[Number, Field(gt=0, le=1000)] | None = None
    temperature_kind: Literal['skin', 'ambient', 'device', 'unknown'] = 'unknown'

    @model_validator(mode='after')
    def check_sensor(self):
        keys, units = {
            'heart_rate': ({'bpm'}, {'bpm'}),
            'acceleration': ({'x', 'y', 'z'}, {'g', 'm/s2'}),
            'ibi': ({'seconds'}, {'s'}),
            'temperature': ({'celsius'}, {'degC'}),
        }[self.sensor]
        if set(self.values) != keys or self.unit not in units:
            raise ValueError(f'{self.sensor} requires keys {sorted(keys)} and units {sorted(units)}')
        if self.sensor != 'temperature' and self.temperature_kind != 'unknown':
            raise ValueError('temperature_kind applies only to temperature')
        if self.sensor in ('heart_rate', 'ibi'):
            value = next(iter(self.values.values()))
            if value is not None and value <= 0:
                raise ValueError('Heart rate and IBI must be positive or null')
        return self


class WatchBatch(Stream):
    batch_id: Annotated[int, Field(strict=True, ge=0)]
    sent_device_ms: Millis
    samples: Annotated[list[WatchSample], Field(min_length=1, max_length=2048)]

    @model_validator(mode='after')
    def check_times(self):
        if any(s.device_time_ms > self.sent_device_ms for s in self.samples):
            raise ValueError('Samples cannot be later than sent_device_ms')
        keys = [(s.sensor, s.device_time_ms) for s in self.samples]
        if len(set(keys)) != len(keys):
            raise ValueError('Duplicate sensor/timestamp within a batch')
        return self


class ClockSync(Stream):
    ping_id: Identifier
    device_send_ms: Millis
    device_receive_ms: Millis
    timestamp_resolution_ms: Annotated[Number, Field(gt=0, le=1000)] = 1.0

    @model_validator(mode='after')
    def check_times(self):
        if self.device_receive_ms < self.device_send_ms:
            raise ValueError('Device clock moved backwards; start a new session')
        return self


class VideoSample(Message):
    timestamp_ms: Millis
    frame_timestamp_ms: Millis | None = None
    values: Values


class VideoBatch(Stream):
    camera_id: Identifier
    extractor_id: Identifier
    feature_schema_id: Identifier
    batch_id: Annotated[int, Field(strict=True, ge=0)]
    sampling_hz: Annotated[Number, Field(gt=0, le=1000)] | None = None
    samples: Annotated[list[VideoSample], Field(min_length=1, max_length=2048)]


class Prediction(Stream):
    modality: Literal['watch', 'video']
    model_id: Identifier
    model_version: Identifier
    target_id: Identifier
    label: Label
    score: Number | None = None
    score_kind: Literal['calibrated_probability', 'uncalibrated_score', 'none'] = 'none'
    window_start_ms: Millis
    window_end_ms: Millis
    generated_at_ms: Millis
    inference_ms: Annotated[Number, Field(ge=0)]
    clock_uncertainty_ms: Annotated[Number, Field(ge=0)] | None = None

    @model_validator(mode='after')
    def check_output(self):
        if self.window_start_ms >= self.window_end_ms:
            raise ValueError('A prediction needs a nonempty observation window')
        if self.window_end_ms > self.generated_at_ms:
            raise ValueError('A prediction cannot use future observations')
        if (self.score_kind == 'none') != (self.score is None):
            raise ValueError('Score and score_kind disagree')
        if self.score_kind == 'calibrated_probability' and not 0 <= self.score <= 1:
            raise ValueError('A probability must be in [0, 1]')
        return self
