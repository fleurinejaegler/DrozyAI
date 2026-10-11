"""Bounded raw buffers and explicit watch-to-server clock mapping."""
from collections import OrderedDict
from dataclasses import dataclass, field
import time
import uuid

from .config import Settings
from .schemas import ClockSync, Prediction, Stream, VideoBatch, WatchBatch


class Clock:
    # An epoch anchor plus monotonic elapsed time avoids wall-clock jumps mid-session.
    def __init__(self):
        self._epoch = time.time_ns() / 1_000_000
        self._mono = time.monotonic_ns() / 1_000_000

    def now_ms(self):
        return int(self._epoch + time.monotonic_ns() / 1_000_000 - self._mono)


@dataclass(frozen=True)
class Observation:
    source_time_ms: int
    received_at_ms: int
    payload: object


class TimeBuffer:
    def __init__(self, retention_ms, capacity):
        self.retention_ms, self.capacity = retention_ms, capacity
        self._items = {}
        self.dropped = 0

    def add(self, observations):
        for key, record in observations:
            existing = self._items.get(key)
            if existing is not None and existing.payload != record.payload:
                raise ValueError('Conflicting retransmission at the same timestamp')
        for key, record in observations:
            self._items.setdefault(key, record)
        if self._items:
            newest = max(o.source_time_ms for o in self._items.values())
            ordered = sorted(self._items.items(), key=lambda kv: kv[1].source_time_ms)
            kept = [(k, v) for k, v in ordered if v.source_time_ms >= newest - self.retention_ms]
            kept = kept[-self.capacity:]
            self.dropped += len(self._items) - len(kept)
            self._items = dict(kept)

    def values(self):
        return tuple(sorted(self._items.values(), key=lambda o: o.source_time_ms))

    def __len__(self):
        return len(self._items)


@dataclass
class ClockMapping:
    offset_ms: float | None = None
    uncertainty_ms: float | None = None
    synchronized_at_ms: int | None = None
    revision: int = 0
    quality: str = 'not_synchronized'

    def synchronize(self, sync, received, sent, now):
        network_ms = (sync.device_receive_ms - sync.device_send_ms) - (sent - received)
        if not 0 <= network_ms <= 10_000:
            raise ValueError('Clock exchange has invalid or excessive round-trip time')
        self.offset_ms = ((received - sync.device_send_ms) + (sent - sync.device_receive_ms)) / 2
        self.uncertainty_ms = network_ms / 2 + sync.timestamp_resolution_ms
        self.synchronized_at_ms = now
        self.quality = 'synchronized'
        self.revision += 1

    def uncertainty(self, now):
        if self.uncertainty_ms is None or self.synchronized_at_ms is None:
            return None
        # Conservative provisional drift allowance: 100 parts per million.
        return self.uncertainty_ms + max(0, now - self.synchronized_at_ms) * 0.0001

    def align(self, device_ms):
        return None if self.offset_ms is None else round(device_ms + self.offset_ms)


@dataclass
class Session:
    stream: Stream
    settings: Settings
    last_seen_ms: int
    clock: ClockMapping = field(default_factory=ClockMapping)
    video_enabled: bool = False
    camera_status: str = 'disabled'
    last_watch_batch: int = -1
    last_watch_send_ms: int = -1
    last_video_batch: int = -1
    video_identity: tuple | None = None
    video_generation: int = 0
    watch_prediction: Prediction | None = None
    video_prediction: Prediction | None = None
    errors: dict = field(default_factory=dict)
    input_revisions: dict = field(default_factory=lambda: {'watch': 0, 'video': 0})

    def __post_init__(self):
        self.watch = TimeBuffer(self.settings.buffer_seconds * 1000, self.settings.max_samples_per_source)
        self.video = TimeBuffer(self.settings.buffer_seconds * 1000, self.settings.max_samples_per_source)
        self.telemetry = TimeBuffer(self.settings.buffer_seconds * 1000, min(2048, self.settings.max_samples_per_source))
        self.telemetry_sequence = -1
        self.telemetry_clock_quality = 'not_received'

    def ingest_watch(self, batch: WatchBatch, now):
        if batch.batch_id <= self.last_watch_batch:
            return False
        if batch.sent_device_ms < self.last_watch_send_ms:
            raise ValueError('Device timer reset; use a new session_id')
        self.watch.add([((s.sensor, s.device_time_ms), Observation(s.device_time_ms, now, s)) for s in batch.samples])
        self.last_watch_batch, self.last_watch_send_ms = batch.batch_id, batch.sent_device_ms
        self.last_seen_ms = now
        self.input_revisions['watch'] += 1
        return True

    def ingest_video(self, batch: VideoBatch, now):
        if not self.video_enabled:
            raise ValueError('Video is disabled; call /video/start first')
        identity = (batch.camera_id, batch.extractor_id, batch.feature_schema_id)
        if self.video_identity is not None and identity != self.video_identity:
            raise ValueError('Video source changed; stop/start video to clear its history')
        if batch.batch_id <= self.last_video_batch:
            return False
        if any(s.timestamp_ms > now + 250 or
               (s.frame_timestamp_ms is not None and s.frame_timestamp_ms > s.timestamp_ms)
               for s in batch.samples):
            raise ValueError('Video timestamps must use the server clock and cannot be in the future')
        keys = [s.timestamp_ms for s in batch.samples]
        if len(set(keys)) != len(keys):
            raise ValueError('Duplicate video timestamps')
        self.video.add([(s.timestamp_ms, Observation(s.timestamp_ms, now, s)) for s in batch.samples])
        self.video_identity, self.last_video_batch = identity, batch.batch_id
        self.last_seen_ms = now
        self.input_revisions['video'] += 1
        return True

    def toggle_video(self, enabled):
        if self.video_enabled == enabled:
            return
        self.video_enabled = enabled
        self.video_generation += 1
        self.camera_status = 'external_extractor_pending' if enabled else 'disabled'
        self.video = TimeBuffer(self.settings.buffer_seconds * 1000, self.settings.max_samples_per_source)
        self.video_prediction = None
        self.video_identity, self.last_video_batch = None, -1
        self.input_revisions['video'] += 1


class Streams:
    def __init__(self, settings, clock):
        self.settings, self.clock = settings, clock
        self.sessions = OrderedDict()
        self.pings = OrderedDict()

    @staticmethod
    def key(stream):
        return stream.device_id, stream.session_id, stream.data_origin

    def get(self, stream, create=False):
        key = self.key(stream)
        if key not in self.sessions:
            if not create:
                raise KeyError('Unknown session; upload watch data or start video first')
            now = self.clock.now_ms()
            for old_key, session in list(self.sessions.items()):
                if now - session.last_seen_ms > self.settings.buffer_seconds * 1000:
                    del self.sessions[old_key]
            if len(self.sessions) >= self.settings.max_streams:
                raise OverflowError('Maximum active sessions reached')
            self.sessions[key] = Session(stream, self.settings, now)
        return self.sessions[key]

    def ping(self, stream):
        now = self.clock.now_ms()
        self.pings = OrderedDict((k, v) for k, v in self.pings.items() if now - v[1] <= 60_000)
        token = uuid.uuid4().hex
        sent = self.clock.now_ms()
        self.pings[token] = (self.key(stream), now, sent)
        while len(self.pings) > 128:
            self.pings.popitem(last=False)
        return {'ping_id': token, 'server_receive_ms': now, 'server_send_ms': sent}

    def synchronize(self, sync: ClockSync):
        item = self.pings.get(sync.ping_id)
        now = self.clock.now_ms()
        if item is None or item[0] != self.key(sync) or now - item[1] > 60_000:
            raise ValueError('Unknown, expired, or wrong-session clock ping')
        session = self.get(Stream(**sync.model_dump(include={'device_id', 'session_id', 'data_origin'})), create=True)
        session.clock.synchronize(sync, item[1], item[2], now)
        del self.pings[sync.ping_id]
        session.watch_prediction = None
        session.input_revisions['watch'] += 1
        return session.clock
