"""Consume the EXISTING schema-1 iPhone relay without rewriting sensor clocks."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .schemas import Identifier, Millis, Number, Stream
from .streams import Observation


class Axes(BaseModel):
    model_config = ConfigDict(extra='allow', frozen=True)
    unit: Literal['mg', 'deg/s']
    sampleRateHz: Annotated[Number, Field(gt=0, le=1000)] | None
    x: Annotated[list[Number | None], Field(max_length=25)]
    y: Annotated[list[Number | None], Field(max_length=25)]
    z: Annotated[list[Number | None], Field(max_length=25)]
    sensorTimestampMs: Annotated[list[Millis | None], Field(max_length=25)]
    inputCount: Annotated[int, Field(strict=True, ge=0)]
    truncated: bool

    @model_validator(mode='after')
    def validate_arrays(self):
        if not len(self.x) == len(self.y) == len(self.z) == len(self.sensorTimestampMs):
            raise ValueError('Motion arrays and timestamp positions must match')
        if self.inputCount < len(self.x) or self.truncated != (self.inputCount > len(self.x)):
            raise ValueError('Motion truncation metadata disagrees with array lengths')
        return self


class Telemetry(BaseModel):
    model_config = ConfigDict(extra='allow', frozen=True)
    protocol: Literal[1]
    type: Literal['telemetry']
    schema_version: Literal[1] = Field(alias='schema')
    source: Literal['watch_sensors']
    session: Identifier
    sequence: Annotated[int, Field(strict=True, ge=0)]
    sentAt: Annotated[Number, Field(ge=0)]
    watchUptimeMs: Millis
    batchId: Annotated[int, Field(strict=True, ge=0)]
    batchReceivedAtMs: Millis | None
    heartRateBpm: Number | None
    heartRateAtMs: Millis | None
    spo2Percent: Number | None
    spo2AtMs: Millis | None
    temperatureC: Number | None
    temperatureAtMs: Millis | None
    accelerometer: Axes | None
    gyroscope: Axes | None
    beatIntervalsMs: Annotated[list[Number | None], Field(max_length=8)] | None
    hrvRmssdMs: Number | None
    hrvWindowSeconds: Annotated[Number, Field(gt=0)]

    @model_validator(mode='after')
    def validate_readings(self):
        for stamp in (self.batchReceivedAtMs, self.heartRateAtMs, self.spo2AtMs, self.temperatureAtMs):
            if stamp is not None and stamp > self.watchUptimeMs:
                raise ValueError('Callback timestamp exceeds watch uptime')
        if self.accelerometer is not None and self.accelerometer.unit != 'mg':
            raise ValueError('The existing watch protocol uses accelerometer mg')
        if self.gyroscope is not None and self.gyroscope.unit != 'deg/s':
            raise ValueError('The existing watch protocol uses gyroscope deg/s')
        return self


def ingest_relay_snapshot(runtime, snapshot, client_id='demo'):
    """Keep raw packets and clock domains intact. None means unavailable.

    sentAt is watch epoch send time; callback uptime and Garmin motion timestamps
    remain separate. No sample times or verified watch-to-Mac offset are invented.
    """
    if not isinstance(snapshot, dict) or snapshot.get('phoneRecent') is not True or snapshot.get('telemetry') is None:
        return None
    packet = Telemetry.model_validate(snapshot['telemetry'])
    if packet.session != snapshot.get('watchSession'):
        raise ValueError('Wrong-session telemetry')
    now = runtime.clock.now_ms()
    age = now - round(packet.sentAt * 1000)
    if age < -2000 or age > runtime.settings.max_prediction_age_ms:
        raise ValueError('Stale/future telemetry, or watch and Mac epoch clocks differ')
    session = runtime.streams.get(Stream(device_id=client_id, session_id=packet.session,
                                        data_origin=snapshot.get('data_origin', 'live')), create=True)
    if packet.sequence <= session.telemetry_sequence:
        return session
    records = session.telemetry.values()
    if records and packet.watchUptimeMs < records[-1].source_time_ms:
        raise ValueError('Watch uptime reset; a new watch session is required')
    session.telemetry.add([(packet.sequence, Observation(packet.watchUptimeMs, now, packet))])
    session.telemetry_sequence = packet.sequence
    session.telemetry_clock_quality = 'separate_clock_domains_preserved'
    session.last_seen_ms = now
    session.input_revisions['watch'] += 1
    return session


def pending_watch_result(runtime, session, snapshot):
    """Map runtime state to the existing RelayClient model_result contract.

    The current numeric watch gauge cannot represent label-only outputs as
    probabilities. Keep riskScore null until the contract is deliberately
    extended or compatible calibrated models are connected.
    """
    verdict = runtime.latest(session)
    if verdict['reason'] == 'MODEL_NOT_CONFIGURED':
        return None, 'models-pending', 'model_not_connected'
    if verdict['status'] != 'ok' or verdict['score_kind'] != 'calibrated_probability':
        return None, 'inference-pending', 'insufficient_data'
    packet_time = round(snapshot['telemetry']['sentAt'] * 1000)
    prediction = session.watch_prediction
    # RelayClient uses packet.sentAt as capturedAt. Reject mismatched windows
    # instead of renewing an older result under a newer packet's timestamp.
    if prediction is None or abs(prediction.window_end_ms - packet_time) > 1000:
        return None, 'input-window-mismatch', 'insufficient_data'
    return verdict['score'], ('fused-' + verdict['mode'])[:64], 'ready'
