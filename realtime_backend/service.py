"""One event-loop owner for state; separate watch/video executors for future adapters."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import logging
import time
import uuid

from .adapters import InputWindow, ModelSlots
from .config import Settings
from .fusion import Confirmer, fuse, unavailable
from .journal import PredictionJournal
from .schemas import Prediction, Stream
from .streams import Clock, Observation, Streams

LOG = logging.getLogger(__name__)


class Runtime:
    def __init__(self, settings=None, models=None, clock=None, score_fuser=None):
        self.settings = settings or Settings.from_env()
        self.models = models or ModelSlots()  # Intentionally empty; never scan/load old artifacts.
        self.clock = clock or Clock()
        self.score_fuser = score_fuser
        self.streams = Streams(self.settings, self.clock)
        self.journal = PredictionJournal(self.settings.log_directory)
        self.server_id = uuid.uuid4().hex[:12]
        self.response_seq = 0
        self.confirmers, self.last_logged = {}, {}
        self.tasks, self.executors = [], {}

    async def start(self):
        self.journal.start()
        for modality in ('watch', 'video'):
            if self.models.adapters[modality] is not None:
                self.executors[modality] = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f'{modality}-inference')
            self.tasks.append(asyncio.create_task(self._loop(modality)))
        self.tasks.append(asyncio.create_task(self._monitor()))

    async def stop(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        for executor in self.executors.values():
            executor.shutdown(wait=False, cancel_futures=True)
        await asyncio.to_thread(self.journal.close)

    async def _loop(self, modality):
        while True:
            await self.infer_once(modality)
            await asyncio.sleep(self.settings.inference_interval_s)

    async def _monitor(self):
        while True:
            keys = set(self.streams.sessions)
            for mapping in (self.confirmers, self.last_logged):
                for key in set(mapping) - keys:
                    del mapping[key]
            for session in list(self.streams.sessions.values()):
                self.latest(session)
            await asyncio.sleep(min(1.0, self.settings.inference_interval_s))

    def window(self, session, modality, spec):
        now = self.clock.now_ms()
        if spec.window_seconds > self.settings.buffer_seconds:
            raise ValueError('Model window exceeds configured buffer retention')
        if modality == 'watch':
            uncertainty = session.clock.uncertainty(now)
            if uncertainty is None or uncertainty > self.settings.max_clock_uncertainty_ms:
                return None
            schema = 'garmin.telemetry.v1' if len(session.telemetry) else 'garmin.raw.v1'
            source = session.telemetry if len(session.telemetry) else session.watch
            records = [(session.clock.align(o.source_time_ms), o) for o in source.values()]
        else:
            if not session.video_enabled or session.video_identity is None:
                return None
            uncertainty = 1.0
            schema = session.video_identity[2]
            records = [(o.source_time_ms, o) for o in session.video.values()]
        if schema != spec.input_schema_id:
            raise ValueError('Input schema differs from adapter training contract')
        records = [(t, o) for t, o in records if t is not None and t <= now]
        if not records or now - records[-1][0] > self.settings.max_prediction_age_ms:
            return None
        end = records[-1][0] + 1
        start = end - round(spec.window_seconds * 1000)
        records = [(t, o) for t, o in records if start <= t < end]
        if not records:
            return None
        # Copies isolate the event-loop-owned buffers from preprocessing in worker threads.
        copies = tuple(Observation(o.source_time_ms, o.received_at_ms, o.payload.model_copy(deep=True))
                       for _, o in records)
        return InputWindow(session.stream, modality, start, end, copies,
                           tuple(t for t, _ in records), uncertainty, schema)

    async def infer_once(self, modality):
        adapter = self.models.adapters[modality]
        if adapter is None:
            return
        for key, session in list(self.streams.sessions.items()):
            clock_revision = session.clock.revision
            video_generation = session.video_generation
            try:
                window = self.window(session, modality, adapter.spec)
                if window is None:
                    continue
                previous = getattr(session, f'{modality}_prediction')
                if previous is not None and previous.window_end_ms >= window.aligned_timestamps_ms[-1]:
                    continue
                started = time.perf_counter()
                # Each modality has a dedicated single-worker executor. A slow video
                # prediction cannot occupy the watch's executor or the HTTP event loop.
                prediction = await asyncio.get_running_loop().run_in_executor(
                    self.executors[modality], adapter.predict, window)
                measured_ms = (time.perf_counter() - started) * 1000
                if self.streams.sessions.get(key) is not session or clock_revision != session.clock.revision:
                    continue
                if modality == 'video' and (not session.video_enabled or video_generation != session.video_generation):
                    continue
                if prediction is not None:
                    if not isinstance(prediction, Prediction):
                        raise ValueError('Adapter must return the validated Prediction contract')
                    spec = adapter.spec
                    if ((prediction.device_id, prediction.session_id, prediction.data_origin) != key or
                        prediction.modality != modality or prediction.model_id != spec.model_id or
                        prediction.model_version != spec.version or prediction.target_id != spec.target_id or
                        prediction.window_start_ms < window.start_ms or
                        prediction.window_end_ms > window.aligned_timestamps_ms[-1] or
                        prediction.generated_at_ms > self.clock.now_ms()):
                        raise ValueError('Adapter returned mismatched identity, schema, or timestamps')
                    prediction = prediction.model_copy(update={'inference_ms': measured_ms,
                                                                'clock_uncertainty_ms': window.clock_uncertainty_ms})
                setattr(session, f'{modality}_prediction', prediction)
                session.errors.pop(modality, None)
                LOG.info('%s inference: %s | %.1f ms', modality,
                         prediction.label if prediction else 'INSUFFICIENT_DATA', measured_ms)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                setattr(session, f'{modality}_prediction', None)
                session.errors[modality] = type(exc).__name__
                LOG.error('%s inference failed: %s', modality, type(exc).__name__)
            self.latest(session)

    def latest(self, session, request_latency_ms=None):
        now = self.clock.now_ms()
        key = self.streams.key(session.stream)
        watch, video = session.watch_prediction, session.video_prediction
        verdict = fuse(watch, video, session.video_enabled, now, self.settings, self.score_fuser)
        if self.models.adapters['watch'] is None:
            verdict = unavailable('MODEL_NOT_CONFIGURED')
        elif not len(session.watch) and not len(session.telemetry):
            verdict = unavailable('WATCH_DATA_MISSING')
        elif session.clock.offset_ms is None:
            verdict = unavailable('CLOCK_NOT_SYNCHRONIZED')
        elif 'watch' in session.errors:
            verdict = unavailable('WATCH_MODEL_ERROR')
        if verdict.mode == 'watch_only' and session.video_enabled and self.models.adapters['video'] is None:
            verdict = replace(verdict, reason='VIDEO_MODEL_NOT_CONFIGURED')
        confirmer = self.confirmers.setdefault(key, Confirmer(self.settings.confirmation_windows))
        verdict = confirmer.apply(verdict)
        self._record(session, verdict, now)
        self.response_seq += 1
        score = verdict.score if verdict.label == verdict.raw_label else None
        return {
            'status': 'ok' if verdict.label in ('ALERT', 'DROWSY') else
                      ('processing' if verdict.label == 'PROCESSING' else 'collecting'),
            'verdict': verdict.label, 'score': score,
            'score_kind': 'calibrated_probability' if score is not None else 'none',
            'mode': verdict.mode, 'reason': verdict.reason, 'server_id': self.server_id,
            'response_seq': self.response_seq, 'timestamp_ms': now,
            'prediction_timestamp_ms': verdict.prediction_timestamp_ms,
            'valid_for_ms': verdict.valid_for_ms, 'data_origin': session.stream.data_origin,
            'request_latency_ms': request_latency_ms,
        }

    def _record(self, session, verdict, now):
        watch, video = session.watch_prediction, session.video_prediction
        key = self.streams.key(session.stream)
        signature = (verdict.source_key, verdict.label, verdict.reason, session.video_enabled,
                     None if video is None else (video.generated_at_ms, video.window_end_ms))
        if self.last_logged.get(key) == signature:
            return
        self.last_logged[key] = signature
        row = {'timestamp_ms': now, **session.stream.model_dump(),
               'raw_final_prediction': verdict.raw_label, 'final_prediction': verdict.label,
               'final_score': verdict.score if verdict.label == verdict.raw_label else None,
               'inference_mode': verdict.mode, 'video_enabled': session.video_enabled, 'reason': verdict.reason,
               'prediction_latency_ms': (now - min(p.window_end_ms for p in (watch, video) if p is not None))
                                       if watch is not None or video is not None else None}
        for name, prediction in (('watch', watch), ('video', video)):
            row[f'{name}_prediction'] = prediction.label if prediction else None
            row[f'{name}_score'] = prediction.score if prediction else None
            row[f'{name}_score_kind'] = prediction.score_kind if prediction else None
            row[f'{name}_model_version'] = f'{prediction.model_id}:{prediction.model_version}' if prediction else None
            row[f'{name}_data_age_ms'] = now - prediction.window_end_ms if prediction else None
            for suffix in ('window_start_ms', 'window_end_ms'):
                row[f'{name}_{suffix}'] = getattr(prediction, suffix) if prediction else None
            row[f'{name}_prediction_timestamp_ms'] = prediction.generated_at_ms if prediction else None
        self.journal.enqueue(row)
        LOG.info('Final: %s | mode=%s | %s', verdict.label, verdict.mode, verdict.reason)

    def status(self, session):
        now = self.clock.now_ms()
        watch = session.watch.values()
        video = session.video.values()
        latest_watch = session.clock.align(watch[-1].source_time_ms) if watch else None
        return {
            'models': self.models.status(),
            'watch': {'samples': len(watch), 'dropped_samples': session.watch.dropped,
                      'telemetry_packets': len(session.telemetry),
                      'telemetry_clock_quality': session.telemetry_clock_quality,
                      'sensors': sorted({o.payload.sensor for o in watch}),
                      'data_age_ms': now - latest_watch if latest_watch is not None else None,
                      'last_batch_received_ms': max((o.received_at_ms for o in watch), default=None),
                      'clock_quality': session.clock.quality,
                      'clock_uncertainty_ms': session.clock.uncertainty(now),
                      'clock_revision': session.clock.revision},
            'video': {'enabled': session.video_enabled, 'camera_status': session.camera_status,
                      'samples': len(video), 'dropped_samples': session.video.dropped,
                      'data_age_ms': now - video[-1].source_time_ms if video else None,
                      'source': session.video_identity},
            'errors': dict(session.errors), 'logging': self.journal.status(),
            'confirmation_windows': self.settings.confirmation_windows,
            'nominal_smoothing_delay_s': (self.settings.confirmation_windows - 1) * self.settings.inference_interval_s,
            'data_origin': session.stream.data_origin,
        }
