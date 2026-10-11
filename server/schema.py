"""Compact schema: t = watch callback uptime ms; v = original measurement."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Scalar = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Tick = Annotated[int, Field(strict=True, ge=0, le=2147483647)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Observation(StrictModel):
    t: Tick
    v: Scalar | None


class Acceleration(StrictModel):
    t: Tick
    rate_hz: Annotated[int, Field(strict=True, ge=1, le=25)]
    x: list[Scalar | None] = Field(min_length=1, max_length=25)
    y: list[Scalar | None] = Field(min_length=1, max_length=25)
    z: list[Scalar | None] = Field(min_length=1, max_length=25)
    sensor_ms: list[Tick | None] = Field(min_length=1, max_length=25)

    @model_validator(mode="after")
    def equal_axes(self):
        if len({len(self.x), len(self.y), len(self.z), len(self.sensor_ms)}) != 1:
            raise ValueError("Accelerometer axes/timestamps must have equal lengths")
        known = [t for t in self.sensor_ms if t is not None]
        if any(b <= a for a, b in zip(known, known[1:])):
            raise ValueError("Sensor timestamps must increase within a block")
        return self


class Intervals(StrictModel):
    t: Tick
    values_ms: list[Scalar | None] = Field(max_length=8)


class Temperature(Observation):
    source: Literal["watch_onboard_history", "watch_sensor_info_no_external"]
    type: Literal["unknown", "ambient", "skin", "onboard"] = "unknown"
    epoch_s: Annotated[int, Field(strict=True, ge=0)] | None = None


class Drops(StrictModel):
    heart_rate: Tick = 0
    accelerometer: Tick = 0
    ibi: Tick = 0
    temperature: Tick = 0
    expired_batches: Tick = 0


class Availability(StrictModel):
    heart_rate: Literal["receiving", "unavailable", "external_blocked"]
    accelerometer: Literal["receiving", "unavailable"]
    ibi: Literal["receiving", "unavailable", "external_blocked"]
    temperature: Literal["receiving", "unavailable", "external_blocked"]


class Batch(StrictModel):
    schema_version: Literal[1]
    device: Literal["garmin_forerunner_970"]
    session: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9_-]+$")
    batch_id: Annotated[int, Field(strict=True, ge=1)]
    anchor_epoch_s: Annotated[int, Field(strict=True, ge=0)]
    anchor_watch_ms: Tick
    created_watch_ms: Tick
    heart_rate: list[Observation] = Field(max_length=32)
    accelerometer: list[Acceleration] = Field(max_length=5)
    ibi: list[Intervals] = Field(max_length=32)
    temperature: list[Temperature] = Field(max_length=32)
    availability: Availability
    dropped: Drops

    @model_validator(mode="after")
    def validate_clock_and_values(self):
        for series in (self.heart_rate, self.accelerometer, self.ibi, self.temperature):
            if any(s.t > self.created_watch_ms for s in series):
                raise ValueError("Observation occurs after batch creation")
            if any(b.t < a.t for a, b in zip(series, series[1:])):
                raise ValueError("Callback observations must be ordered")
        for s in self.heart_rate:
            if s.v is not None and not 0 < s.v <= 300:
                raise ValueError("Heart rate outside 0..300 BPM")
        # IBI artifacts are retained in raw CSV and excluded only from derived HRV.
        return self

    def epoch(self, t: int) -> float:
        return self.anchor_epoch_s + (t - self.anchor_watch_ms) / 1000.0
