"""Software tests use synthetic inputs/stub adapters, never physical sensors or ML."""
import asyncio
import csv
import math
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

from flask import Flask
from pydantic import ValidationError

from realtime_backend.adapters import AdapterSpec, InputWindow, ModelSlots
from realtime_backend.advice import advise
from realtime_backend.alignment import aggregate_watch_seconds, rmssd_from_raw_ibi
from realtime_backend.config import Settings
from realtime_backend.flask_routes import register_runtime
from realtime_backend.fusion import Confirmer, fuse, unavailable
from realtime_backend.journal import PredictionJournal
from realtime_backend.schemas import ClockSync, Prediction, Stream, VideoBatch, WatchBatch, WatchSample
from realtime_backend.service import Runtime
from realtime_backend.streams import Observation, TimeBuffer
from realtime_backend.telemetry import ingest_relay_snapshot, pending_watch_result


class FakeClock:
    value = 1_000_000
    def now_ms(self):
        return self.value


STREAM = dict(device_id='test-watch', session_id='software-test', data_origin='synthetic_test')


def batch(**changes):
    value = dict(**STREAM, batch_id=1, sent_device_ms=2000,
                 samples=[dict(sensor='heart_rate', device_time_ms=1000, values={'bpm': None}, unit='bpm')])
    value.update(changes)
    return WatchBatch.model_validate(value)


def prediction(modality='watch', **changes):
    value = dict(**STREAM, modality=modality, model_id='stub-' + modality, model_version='test-v1',
                 target_id='test-label', label='DROWSY', score=.8,
                 score_kind='calibrated_probability', window_start_ms=940_000,
                 window_end_ms=999_000, generated_at_ms=999_100, inference_ms=1., clock_uncertainty_ms=1.)
    value.update(changes)
    return Prediction.model_validate(value)


def snapshot():
    axes = dict(unit='mg', sampleRateHz=25., x=[1., None], y=[2., 3.], z=[1000., 999.],
                sensorTimestampMs=[987654, None], inputCount=2, truncated=False)
    packet = dict(protocol=1, type='telemetry', schema=1, source='watch_sensors', session='relay-test',
                  sequence=1, sentAt=1000., watchUptimeMs=2000, batchId=2, batchReceivedAtMs=1990,
                  heartRateBpm=None, heartRateAtMs=None, spo2Percent=None, spo2AtMs=None,
                  temperatureC=None, temperatureAtMs=None, accelerometer=axes, gyroscope=None,
                  beatIntervalsMs=[800., None, 820.], hrvRmssdMs=None, hrvWindowSeconds=60.)
    return dict(watchSession='relay-test', phoneRecent=True, telemetry=packet, data_origin='synthetic_test')


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Settings(log_directory=Path(self.tmp.name))
        self.runtime = Runtime(self.settings, clock=FakeClock())

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_models_never_fabricate_scores(self):
        session = self.runtime.streams.get(Stream(**STREAM), True)
        response = self.runtime.latest(session)
        self.assertEqual(response['reason'], 'MODEL_NOT_CONFIGURED')
        self.assertEqual(response['verdict'], 'INSUFFICIENT_DATA')
        self.assertIsNone(response['score'])

    def test_relay_preserves_all_clock_domains_nulls_and_raw_ibi(self):
        sample = snapshot()
        session = ingest_relay_snapshot(self.runtime, sample)
        self.assertEqual(len(session.telemetry), 1)
        stored = session.telemetry.values()[0]
        self.assertEqual(stored.source_time_ms, 2000)
        self.assertEqual(stored.received_at_ms, 1_000_000)
        self.assertEqual(stored.payload.accelerometer.sensorTimestampMs, [987654, None])
        self.assertEqual(stored.payload.beatIntervalsMs, [800., None, 820.])
        self.assertIsNone(session.clock.offset_ms)
        self.assertIsNone(stored.payload.heartRateBpm)
        ingest_relay_snapshot(self.runtime, sample)
        self.assertEqual(len(session.telemetry), 1)
        self.assertEqual(pending_watch_result(self.runtime, session, sample),
                         (None, 'models-pending', 'model_not_connected'))

    def test_relay_rejects_stale_future_and_wrong_session(self):
        for field, value in [('sentAt', 900.), ('sentAt', 1100.), ('session', 'wrong')]:
            sample = snapshot()
            sample['telemetry'][field] = value
            with self.assertRaises(ValueError):
                ingest_relay_snapshot(self.runtime, sample)
        sample = snapshot(); sample['phoneRecent'] = False
        self.assertIsNone(ingest_relay_snapshot(self.runtime, sample))

    def test_relay_validates_motion_array_positions(self):
        sample = snapshot(); sample['telemetry']['accelerometer']['x'] = [1.]
        with self.assertRaises(ValueError):
            ingest_relay_snapshot(self.runtime, sample)

    def test_buffer_bounds_retention_and_conflicting_retransmission(self):
        buffer = TimeBuffer(1000, 2)
        buffer.add([(i, Observation(i * 1000, 0, i)) for i in range(4)])
        self.assertEqual([o.source_time_ms for o in buffer.values()], [2000, 3000])
        self.assertEqual(buffer.dropped, 2)
        with self.assertRaises(ValueError):
            buffer.add([(3, Observation(3000, 0, 99))])
        self.assertEqual(buffer.values()[-1].payload, 3)

    def test_missing_values_preserved_invalid_numeric_rejected(self):
        self.assertIsNone(batch().samples[0].values['bpm'])
        for value in [True, float('nan'), float('inf'), 0, '72']:
            with self.assertRaises(ValidationError):
                batch(samples=[dict(sensor='heart_rate', device_time_ms=1000, values={'bpm': value}, unit='bpm')])

    def test_batch_dedup_and_watch_timer_reset(self):
        session = self.runtime.streams.get(Stream(**STREAM), True)
        self.assertTrue(session.ingest_watch(batch(), 1_000_000))
        self.assertFalse(session.ingest_watch(batch(), 1_000_001))
        with self.assertRaises(ValueError):
            session.ingest_watch(batch(batch_id=2, sent_device_ms=1500), 1_000_002)

    def test_clock_exchange_known_offset_and_token_binding(self):
        stream = Stream(**STREAM)
        ping = self.runtime.streams.ping(stream)
        sync = ClockSync(**STREAM, ping_id=ping['ping_id'], device_send_ms=1900, device_receive_ms=2100)
        mapping = self.runtime.streams.synchronize(sync)
        self.assertEqual(mapping.offset_ms, 998_000)
        self.assertEqual(mapping.align(2000), 1_000_000)
        self.assertEqual(mapping.uncertainty_ms, 101)
        with self.assertRaises(ValueError):
            self.runtime.streams.synchronize(sync)

    def test_clock_ping_expires(self):
        ping = self.runtime.streams.ping(Stream(**STREAM))
        self.runtime.clock.value += 60_001
        with self.assertRaises(ValueError):
            self.runtime.streams.synchronize(ClockSync(**STREAM, ping_id=ping['ping_id'],
                                                       device_send_ms=1900, device_receive_ms=2100))

    def test_fuses_only_fresh_calibrated_matching_predictions(self):
        result = fuse(prediction(score=.2), prediction('video', score=.8), True, 1_000_000, self.settings)
        self.assertAlmostEqual(result.score, .5)
        self.assertEqual(result.mode, 'watch_video')
        self.assertEqual(result.label, 'DROWSY')

    def test_reuses_injected_repository_fusion_function(self):
        existing = Mock(return_value=.5)
        result = fuse(prediction(score=.2), prediction('video', score=.8), True, 1_000_000,
                      self.settings, existing)
        existing.assert_called_once_with(.2, .8, method='weighted', watch_weight=.5)
        self.assertEqual(result.score, .5)

    def test_stale_video_falls_back_and_stale_watch_is_unavailable(self):
        old = prediction('video', window_start_ms=900_000, window_end_ms=980_000)
        self.assertEqual(fuse(prediction(), old, True, 1_000_000, self.settings).mode, 'watch_only')
        self.assertEqual(fuse(old.model_copy(update={'modality':'watch'}), prediction('video'),
                              True, 1_000_000, self.settings).label, 'INSUFFICIENT_DATA')

    def test_uncalibrated_outputs_cannot_be_shown_as_probabilities(self):
        watch = prediction(score_kind='uncalibrated_score', score=.9)
        result = fuse(watch, prediction('video'), True, 1_000_000, self.settings)
        self.assertEqual(result.mode, 'watch_only')
        self.assertEqual(result.label, 'DROWSY')
        self.assertIsNone(result.score)

    def test_mismatched_windows_targets_or_sessions_never_fuse(self):
        for changes in [dict(target_id='other'), dict(session_id='other'),
                        dict(window_start_ms=980_000, window_end_ms=995_000)]:
            result = fuse(prediction(), prediction('video', **changes), True, 1_000_000, self.settings)
            self.assertEqual(result.mode, 'watch_only')
        self.assertEqual(fuse(None, prediction('video'), True, 1_000_000, self.settings).mode, 'none')

    def test_smoothing_counts_distinct_windows_and_resets_on_missing(self):
        confirmer = Confirmer(2)
        result = fuse(prediction(), None, False, 1_000_000, self.settings)
        self.assertEqual(confirmer.apply(result).label, 'PROCESSING')
        self.assertEqual(confirmer.apply(result).label, 'PROCESSING')
        new = fuse(prediction(window_end_ms=999_500, generated_at_ms=999_600), None, False, 1_000_000, self.settings)
        self.assertEqual(confirmer.apply(new).label, 'DROWSY')
        self.assertEqual(confirmer.apply(unavailable('missing')).label, 'INSUFFICIENT_DATA')
        self.assertEqual(confirmer.apply(new).label, 'PROCESSING')

    def test_timestamp_resampling_preserves_empty_seconds(self):
        samples = [WatchSample(sensor='heart_rate',device_time_ms=t,values={'bpm':v},unit='bpm')
                   for t,v in [(100,70.),(200,80.),(2100,90.)]]
        window = InputWindow(Stream(**STREAM),'watch',0,3000,
                             tuple(Observation(s.device_time_ms,0,s) for s in samples),
                             tuple(s.device_time_ms for s in samples),1.,'garmin.raw.v1')
        rows = aggregate_watch_seconds(window)
        self.assertEqual([r['heart_rate'] for r in rows], [75., None, 90.])

    def test_rmssd_uses_raw_intervals_and_breaks_invalid_pairs(self):
        samples = [WatchSample(sensor='ibi',device_time_ms=t,values={'seconds':v},unit='s')
                   for t,v in [(100,.8),(900,.9),(1800,None),(2600,.7),(3400,.8)]]
        window = InputWindow(Stream(**STREAM),'watch',0,4000,
                             tuple(Observation(s.device_time_ms,0,s) for s in samples),
                             tuple(s.device_time_ms for s in samples),1.,'garmin.raw.v1')
        self.assertAlmostEqual(rmssd_from_raw_ibi(window,1500), .1)

    def test_csv_keeps_missing_scores_empty_and_rotates_with_headers(self):
        journal = PredictionJournal(self.tmp.name, max_file_bytes=1)
        journal.start()
        journal.enqueue({'timestamp_ms':1,'final_prediction':'INSUFFICIENT_DATA','final_score':None})
        journal.enqueue({'timestamp_ms':2,'final_prediction':'INSUFFICIENT_DATA','final_score':None})
        journal.close()
        paths = [Path(self.tmp.name)/name for name in ('predictions.csv','predictions.1.csv')]
        for path in paths:
            with path.open() as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['final_score'],'')


class FlaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rt = Runtime(Settings(log_directory=Path(self.tmp.name)), clock=FakeClock())
        self.app = Flask(__name__)
        self.app.testing = True
        self.runner = register_runtime(self.app, self.rt)
        self.client = self.app.test_client()

    def tearDown(self):
        self.runner.close()
        self.tmp.cleanup()

    def test_blueprint_idempotent_and_pending_health(self):
        self.assertIs(register_runtime(self.app), self.runner)
        result = self.client.get('/health')
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json['models']['watch']['status'],'MODEL_NOT_CONFIGURED')

    def test_upload_ack_and_null_score(self):
        result = self.client.post('/garmin/data',json=batch().model_dump())
        self.assertEqual(result.status_code,200)
        self.assertIsNone(result.json['score'])
        self.assertTrue(result.json['batch_accepted'])
        repeated = self.client.post('/garmin/data',json=batch().model_dump())
        self.assertFalse(repeated.json['batch_accepted'])
        self.assertGreater(repeated.json['response_seq'],result.json['response_seq'])

    def test_existing_relay_snapshot_is_accepted(self):
        result = self.client.post('/garmin/data',json=snapshot())
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json['reason'],'MODEL_NOT_CONFIGURED')

    def test_malformed_queries_unknown_sessions_and_oversize(self):
        self.assertEqual(self.client.get('/prediction/latest').status_code,422)
        self.assertEqual(self.client.get('/prediction/latest?device_id=a&session_id=b').status_code,404)
        self.assertEqual(self.client.post('/garmin/data',json=[]).status_code,422)
        self.assertEqual(self.client.post('/garmin/data',data=b' '*512_001,content_type='application/json').status_code,413)

    def test_video_optional_does_not_start_camera_and_stop_clears_history(self):
        self.client.post('/garmin/data',json=batch().model_dump())
        payload = dict(**STREAM, camera_id='test-camera', extractor_id='test-extractor',feature_schema_id='test-schema',
                       batch_id=1,samples=[dict(timestamp_ms=999_000,values={'test_feature':None})])
        self.assertEqual(self.client.post('/video/features',json=payload).status_code,422)
        result = self.client.post('/video/start',json=STREAM)
        self.assertFalse(result.json['camera_started'])
        self.assertEqual(self.client.post('/video/features',json=payload).status_code,200)
        self.client.post('/video/stop',json=STREAM)
        current = self.runner.invoke(self.rt.streams.get,Stream(**STREAM))
        self.assertEqual(len(current.video),0)
        self.assertIsNone(current.video_prediction)


class AdviceTests(unittest.TestCase):
    @staticmethod
    def rule(score,trend=0.,top_signals=None):
        return {'action':'stop now' if score>=.75 else 'take a break at the next rest area' if score>=.5 else 'continue',
                'reason':'deterministic test reason'}

    def test_missing_and_stale_data_do_not_recommend_continue(self):
        for value in [None,float('nan'),True]:
            self.assertIsNone(advise(watch_score=value,fallback=self.rule)['action'])
        self.assertIsNone(advise(watch_score=.2,fresh=False,fallback=self.rule)['action'])

    def test_watch_only_uses_existing_rule_contract(self):
        result = advise(watch_score=.8,fallback=self.rule)
        self.assertEqual(result['action'],'stop now')
        self.assertEqual(result['weights'],{'watch':1.,'vision':0.})

    def test_missing_llm_features_never_become_zero(self):
        llm=Mock()
        result=advise(watch_score=.2,vision_score=.8,fallback=self.rule,meta_advisor=llm)
        llm.assert_not_called()
        self.assertEqual(result['source'],'fallback_missing_llm_features')

    def test_llm_arithmetic_recomputed_and_action_thresholds_consistent(self):
        from realtime_backend.advice import WATCH_KEYS,VISION_KEYS
        llm=Mock(return_value={'weights':{'watch':.25,'vision':.75},'confidence':.9,
                               'fused_score':.99,'action':'stop now','reason':'wrong action story'})
        result=advise(watch_score=.2,vision_score=.8,watch_features=dict.fromkeys(WATCH_KEYS,1.),
                      vision_features=dict.fromkeys(VISION_KEYS,1.),fallback=self.rule,meta_advisor=llm)
        self.assertAlmostEqual(result['fused_score'],.65)
        self.assertEqual(result['action'],'take a break at the next rest area')
        self.assertEqual(result['reason'],'deterministic test reason')

    def test_invalid_weights_and_llm_failure_use_deterministic_fallback(self):
        from realtime_backend.advice import WATCH_KEYS,VISION_KEYS
        for llm in [Mock(side_effect=TimeoutError),Mock(return_value={'weights':{'watch':float('nan'),'vision':.5},'confidence':.5})]:
            result=advise(watch_score=.2,vision_score=.8,watch_features=dict.fromkeys(WATCH_KEYS,1.),
                          vision_features=dict.fromkeys(VISION_KEYS,1.),fallback=self.rule,meta_advisor=llm)
            self.assertEqual(result['source'],'fallback_invalid_or_failed_llm')
            self.assertAlmostEqual(result['fused_score'],.5)


if __name__=='__main__':
    unittest.main()
