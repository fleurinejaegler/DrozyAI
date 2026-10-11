"""Concurrency and adapter-failure tests with software-only stub models."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest

from realtime_backend.adapters import AdapterSpec, ModelSlots
from realtime_backend.config import Settings
from realtime_backend.schemas import Prediction, Stream, VideoBatch, WatchBatch
from realtime_backend.service import Runtime

STREAM = dict(device_id='test-watch',session_id='worker-test',data_origin='synthetic_test')


class Clock:
    def now_ms(self):return 1_000_000


class StubAdapter:
    def __init__(self,modality,entered=None,release=None,fail=False):
        self.spec=AdapterSpec('stub-'+modality,'test-v1',modality,'test-label',
                              'garmin.raw.v1' if modality=='watch' else 'test-video',
                              ('test_feature',),('test-unit',),'reject missing','test-preprocessor',60.)
        self.entered,self.release,self.fail=entered,release,fail

    def predict(self,window):
        if self.entered:self.entered.set()
        if self.release:self.release.wait(timeout=2)
        if self.fail:raise ValueError('Test adapter failure')
        return Prediction(**window.stream.model_dump(),modality=window.modality,
                          model_id=self.spec.model_id,model_version=self.spec.version,target_id=self.spec.target_id,
                          label='DROWSY',score=.8,score_kind='calibrated_probability',
                          window_start_ms=window.start_ms,window_end_ms=window.aligned_timestamps_ms[-1],
                          generated_at_ms=1_000_000,inference_ms=1.)


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.entered,self.release=threading.Event(),threading.Event()
        self.rt=Runtime(Settings(log_directory=Path(self.tmp.name)),
                        ModelSlots(StubAdapter('watch'),StubAdapter('video',self.entered,self.release)),Clock())
        self.rt.executors={m:ThreadPoolExecutor(max_workers=1) for m in ('watch','video')}
        self.session=self.rt.streams.get(Stream(**STREAM),True)
        self.session.clock.offset_ms=998000
        self.session.clock.uncertainty_ms=1.
        self.session.clock.synchronized_at_ms=1_000_000
        self.session.ingest_watch(WatchBatch(**STREAM,batch_id=1,sent_device_ms=2000,
            samples=[dict(sensor='heart_rate',device_time_ms=1000,values={'bpm':72.},unit='bpm')]),1_000_000)
        self.session.toggle_video(True)
        self.session.ingest_video(VideoBatch(**STREAM,camera_id='test',extractor_id='test',feature_schema_id='test-video',
            batch_id=1,samples=[dict(timestamp_ms=999000,values={'test_feature':1.})]),1_000_000)

    async def asyncTearDown(self):
        self.release.set()
        for executor in self.rt.executors.values():executor.shutdown(wait=True)
        self.tmp.cleanup()

    async def test_slow_video_does_not_block_watch_or_runtime_state(self):
        video=asyncio.create_task(self.rt.infer_once('video'))
        self.assertTrue(await asyncio.to_thread(self.entered.wait,1))
        await asyncio.wait_for(self.rt.infer_once('watch'),timeout=1)
        self.assertIsNotNone(self.session.watch_prediction)
        self.assertEqual(self.rt.latest(self.session)['mode'],'watch_only')
        self.assertFalse(video.done())
        self.release.set();await video
        self.assertEqual(self.rt.latest(self.session)['mode'],'watch_video')

    async def test_video_stopped_and_restarted_discards_inflight_result(self):
        video=asyncio.create_task(self.rt.infer_once('video'))
        self.assertTrue(await asyncio.to_thread(self.entered.wait,1))
        self.session.toggle_video(False);self.session.toggle_video(True)
        self.release.set();await video
        self.assertIsNone(self.session.video_prediction)

    async def test_adapter_failure_clears_prediction_and_can_recover(self):
        self.rt.models.adapters['watch'].fail=True
        await self.rt.infer_once('watch')
        self.assertIsNone(self.session.watch_prediction)
        self.assertIn('watch',self.session.errors)
        self.rt.models.adapters['watch'].fail=False
        await self.rt.infer_once('watch')
        self.assertIsNotNone(self.session.watch_prediction)
        self.assertNotIn('watch',self.session.errors)


if __name__=='__main__':unittest.main()
