"""Actual saved models, with synthetic sensors and no physical radio actions."""
from pathlib import Path
import os,tempfile,threading,time,unittest
from unittest.mock import Mock,patch
import numpy as np
from src.features.facial_sequence import CHANNELS,FEATURES
from src.models.predict import load_model
from src.models.facial_baseline import FacialModels
from realtime_backend.telemetry import Telemetry
from web.garmin_features import GarminWindow
from web.model_service import ModelService, Session, live_advisor, baseline_video_score
from web.relay_worker import RelayWorker
ROOT=Path(__file__).resolve().parents[1]

def packet(second,session='watch-1',temperature=32.0,ibi=True):
    up=(100+second)*1000
    axes={'unit':'mg','sampleRateHz':25,'x':[i*2 for i in range(25)],'y':[0]*25,'z':[1000]*25,
          'sensorTimestampMs':[up-960+i*40 for i in range(25)],'inputCount':25,'truncated':False}
    return Telemetry.model_validate({'protocol':1,'type':'telemetry','schema':1,'source':'watch_sensors',
        'session':session,'sequence':second+1,'sentAt':1790000000+second,'watchUptimeMs':up,
        'batchId':second+1,'batchReceivedAtMs':up,'heartRateBpm':75,'heartRateAtMs':up,
        'spo2Percent':None,'spo2AtMs':None,'temperatureC':temperature,'temperatureAtMs':up if temperature is not None else None,
        'accelerometer':axes,'gyroscope':None,'beatIntervalsMs':[780+(second%5)*10] if ibi else None,
        'hrvRmssdMs':None,'hrvWindowSeconds':60})

class GarminFeaturesTests(unittest.TestCase):
    def test_heart_rate_carries_only_short_gaps_and_does_not_replace_ibi(self):
        a=GarminWindow();outputs=[]
        for s in range(76):
            p=packet(s)
            if s%5==2:p=p.model_copy(update={'heartRateBpm':None,'heartRateAtMs':None})
            result=a.ingest(p)
            if result:outputs.append(result)
        self.assertTrue(outputs)
        self.assertAlmostEqual(outputs[-1]['features']['hr_mean'],75)
        self.assertGreater(a.quality['hr_carried_seconds'],0)
        self.assertLess(a.quality['coverage']['hr_observed'],.9)
        self.assertGreaterEqual(a.quality['coverage']['hr'],.9)
        for s in range(76,96):a.ingest(packet(s).model_copy(update={'heartRateBpm':None,'heartRateAtMs':None}))
        self.assertIn('heart rate coverage',a.quality['missing'])

    def test_motion_variance_carries_short_gaps_without_creating_samples(self):
        a=GarminWindow();outputs=[]
        for s in range(76):
            p=packet(s)
            if s%5==2:p=p.model_copy(update={'accelerometer':None})
            result=a.ingest(p)
            if result:outputs.append(result)
        self.assertTrue(outputs)
        self.assertGreater(a.quality['motion_carried_seconds'],0)
        self.assertLess(a.quality['coverage']['motion_observed'],.9)
        self.assertGreaterEqual(a.quality['coverage']['motion'],.9)
        self.assertLessEqual(a.quality['motion_max_age_ms'],5000)
        for s in range(76,96):a.ingest(packet(s).model_copy(update={'accelerometer':None}))
        self.assertIn('timestamped accelerometer coverage',a.quality['missing'])

    def test_temperature_carry_age_and_reset(self):
        a=GarminWindow();a.ingest(packet(0,temperature=31.5));a.ingest(packet(1,temperature=None))
        self.assertEqual(a.temperature,31.5);self.assertEqual(a.quality['temperature_age_ms'],1000)
        self.assertTrue(a.quality['temperature_carried'])
        a.ingest(packet(2,session='watch-2',temperature=None));self.assertIsNone(a.temperature)
    def test_first_temperature_not_invented(self):
        a=GarminWindow()
        for s in range(65):result=a.ingest(packet(s,temperature=None))
        self.assertIsNone(result);self.assertIsNone(a.temperature)
        self.assertIn('first temperature / carried history',a.quality['missing'])
    def test_intervals_and_motion_feed_four_features(self):
        a=GarminWindow();outputs=[]
        for s in range(76):
            result=a.ingest(packet(s,temperature=32.0 if s==0 else None))
            if result:outputs.append(result)
        self.assertGreater(len(outputs),1)
        self.assertEqual(set(outputs[-1]['features']),{'hr_mean','rmssd','temp_trend','motion_var'})
        self.assertAlmostEqual(outputs[-1]['features']['hr_mean'],75)
        self.assertAlmostEqual(outputs[-1]['features']['temp_trend'],0,places=10)
        self.assertGreater(outputs[-1]['features']['rmssd'],0)
        self.assertAlmostEqual(outputs[-1]['features']['motion_var'],np.var(np.arange(25)*2*.064)/3,delta=.1)
    def test_hr_never_converted_to_ibi(self):
        a=GarminWindow()
        for s in range(76):result=a.ingest(packet(s,ibi=False))
        self.assertIsNone(result);self.assertIn('genuine beat intervals',a.quality['missing'])
    def test_duplicate_packet_does_not_duplicate_samples(self):
        a=GarminWindow();p=packet(0);a.ingest(p);before=len(a.rows);a.ingest(p)
        self.assertEqual(len(a.rows),before)
    def test_null_motion_timestamps_not_invented(self):
        a=GarminWindow()
        for s in range(76):
            p=packet(s);p=p.model_copy(update={'accelerometer':p.accelerometer.model_copy(update={'sensorTimestampMs':[None]*25})})
            result=a.ingest(p)
        self.assertIsNone(result);self.assertIn('timestamped accelerometer coverage',a.quality['missing'])

class BaselineVideoTests(unittest.TestCase):
    def setUp(self):
        self.sequence=np.zeros((15,60));self.sequence[[0,1,14]]=1
        self.reference=self.sequence[:,0].copy()
    def test_neutral_face_and_normal_blink_cannot_raise_even_a_saturated_model(self):
        score,q=baseline_video_score(1,self.sequence,self.reference)
        self.assertEqual(score,0);self.assertEqual(q['raw_score'],1)
        self.sequence[2,-2]=.3;self.sequence[4,-2]=.3
        self.assertEqual(baseline_video_score(1,self.sequence,self.reference)[0],0)
    def test_sustained_deviation_increases_score_but_never_exceeds_raw_model(self):
        self.sequence[4,-1]=2.75
        score,q=baseline_video_score(.8,self.sequence,self.reference)
        self.assertAlmostEqual(score,.4);self.assertAlmostEqual(q['baseline_deviation'],.5)
        self.sequence[4,-1]=5
        self.assertEqual(baseline_video_score(.8,self.sequence,self.reference)[0],.8)
    def test_baseline_closure_rate_is_subtracted_and_mouth_only_is_capped(self):
        self.reference[2]=.1;self.sequence[2,-15:]=.15
        self.assertEqual(baseline_video_score(1,self.sequence,self.reference)[0],0)
        self.sequence[11,-1]=10
        self.assertEqual(baseline_video_score(1,self.sequence,self.reference)[0],.6)
    def test_missing_recent_face_is_unavailable_and_bad_baseline_is_rejected(self):
        self.sequence[:,-10:]=0
        score,q=baseline_video_score(1,self.sequence,self.reference)
        self.assertTrue(q['baseline_recent_insufficient'])
        for bad in ([float('nan')]*15,[-1]*15,[1]*14):
            with self.assertRaises(ValueError):baseline_video_score(1,self.sequence,bad)

class ConnectedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch;torch.set_num_threads(1)
        cls.watch=load_model(ROOT/'data/processed/baseline_model.pkl');cls.facial=FacialModels.load(ROOT/'data/processed')
    def setUp(self):
        self.logs=tempfile.TemporaryDirectory(prefix="drozy-tests-")
        self.env=patch.dict(os.environ,{"DROZY_LOG_DIRECTORY":self.logs.name});self.env.start()
        self.now=1790000100000
        self.service=ModelService(self.watch,self.facial,ROOT,now=lambda:self.now,llm=False)
        self.identity={'device_id':'demo','session_id':'watch-1','data_origin':'synthetic_test'}
        seq=np.zeros((15,60));seq[[0,1,14]]=1
        self.video={**self.identity,'schema_id':'facial.uldd.tcn15.v1','channels':CHANNELS,'sequence':seq.tolist(),
            'features':dict.fromkeys(FEATURES,0.0),'window':{'start_ms':self.now-60000,'end_ms':self.now}}
        self.video['features'].update(left_eye_mean=1,right_eye_mean=1,valid_frame_fraction=1)
        self.watch_body={**self.identity,'schema_id':'watch.uldd.four.v1','features':{'hr_mean':75,'rmssd':.05,'temp_trend':.0001,'motion_var':5},
            'window':{'start_ms':self.now-60000,'end_ms':self.now}}
    def tearDown(self):
        self.service.close();self.env.stop();self.logs.cleanup()
    def test_actual_models_fuse_and_expire(self):
        self.service.update('watch',self.watch_body);state=self.service.update('video',self.video)
        self.assertEqual(state['mode'],'watch_video')
        self.assertAlmostEqual(state['score'],(state['watch_score']+state['facial_score'])/2)
        self.assertEqual(state['strategy'],'mean')
        self.assertEqual(state['score_type'],'uncalibrated_score')
        self.now+=10001;self.assertIsNone(self.service.state(('demo','watch-1','synthetic_test'))['score'])
    def test_misaligned_video_falls_back_to_watch(self):
        self.service.update('watch',self.watch_body)
        self.video['window']={k:v-3000 for k,v in self.video['window'].items()}
        result=self.service.update('video',self.video)
        self.assertEqual(result['mode'],'watch_only');self.assertEqual(result['reason'],'VIDEO_WINDOW_NOT_ALIGNED')
    def test_live_rgb_partial_window_uses_mask_but_offline_contract_remains_strict(self):
        self.video['schema_id']='facial.rgb.geometry.v1'
        self.video['baseline_reference']=np.asarray(self.video['sequence'])[:,0].tolist()
        sequence=np.asarray(self.video['sequence']);sequence[:,:40]=0
        self.video['sequence']=sequence.tolist()
        result=self.service.update('video',self.video)
        self.assertEqual(result['status'],'provisional')
        self.assertIsNone(result['score'])
        quality=result['components']['video']['quality']
        self.assertTrue(quality['partial_window']);self.assertEqual(quality['observed_seconds'],20)
        with self.assertRaises(ValueError):self.service.facial(self.video)
        sequence[:,50:]=0;self.video['sequence']=sequence.tolist()
        with self.assertRaises(ValueError):self.service.update('video',self.video)
        sequence[:]=0;self.video['sequence']=sequence.tolist()
        with self.assertRaises(ValueError):self.service.update('video',self.video)

    def test_live_camera_requires_neutral_baseline_and_keeps_raw_model_output(self):
        self.video['schema_id']='facial.rgb.geometry.v1'
        with self.assertRaisesRegex(ValueError,'neutral baseline'):self.service.update('video',self.video)
        self.video['baseline_reference']=np.asarray(self.video['sequence'])[:,0].tolist()
        state=self.service.update('video',self.video)
        self.assertEqual(state['status'],'ok')
        self.assertEqual(state['facial_score'],0)
        self.assertGreater(state['components']['video']['quality']['raw_score'],0)
        self.assertEqual(state['components']['video']['quality']['baseline_seconds'],15)
    def test_sessions_not_mixed(self):
        self.service.update('watch',self.watch_body);self.video['session_id']='watch-2'
        self.assertEqual(self.service.update('video',self.video)['mode'],'video_only')
    def test_invalid_new_input_clears_old_prediction(self):
        self.service.update('watch',self.watch_body);self.watch_body['features']['rmssd']=None
        with self.assertRaises(ValueError):self.service.update('watch',self.watch_body)
        self.assertIsNone(self.service.state(('demo','watch-1','synthetic_test'))['score'])
    def test_future_and_wrong_window_rejected(self):
        self.watch_body['window']['end_ms']+=1
        with self.assertRaises(ValueError):self.service.update('watch',self.watch_body)
    def test_async_explanation_cannot_change_score_action_or_weights(self):
        release=threading.Event();entered=threading.Event()
        def explanation(payload):
            entered.set();release.wait(2)
            return {'weights':{'watch':.8,'vision':.2},'confidence':.9,'action':'stop now','reason':'test','fused_score':.999}
        self.service.update('watch',self.watch_body);self.service.explainer=explanation
        started=time.monotonic();state=self.service.update('video',self.video)
        self.assertLess(time.monotonic()-started,.5);self.assertTrue(entered.wait(1))
        original_score,original_action=state['score'],state['advice']['action']
        original_weights=dict(state['advice']['weights'])
        self.assertEqual(state['advice']['source'],'fallback');release.set();self.service.future.result(timeout=2)
        for _ in range(100):
            state=self.service.state(('demo','watch-1','synthetic_test'))
            if state['advice']['source']=='llm':break
            time.sleep(.001)
        self.assertAlmostEqual(state['score'],original_score)
        self.assertEqual(state['advice']['action'],original_action)
        self.assertEqual(state['advice']['weights'],original_weights)
        self.assertEqual(state['advice']['reason'],'test')
    def test_failed_llm_fallback(self):
        self.service.update('watch',self.watch_body);self.service.explainer=Mock(side_effect=RuntimeError('offline'))
        self.service.update('video',self.video)
        with self.assertRaises(RuntimeError):self.service.future.result(timeout=2)
        self.assertIn('fallback',self.service.state(('demo','watch-1','synthetic_test'))['advice']['source'])
    def test_late_advisor_after_stop_discarded(self):
        release=threading.Event()
        self.service.update('watch',self.watch_body)
        self.service.explainer=lambda *args:(release.wait(2) and {'reason':'Old combined result'})
        self.service.update('video',self.video)
        self.service.clear('video',self.identity);release.set();self.service.future.result(timeout=2)
        self.assertEqual(self.service.state(('demo','watch-1','synthetic_test'))['mode'],'watch_only')
        self.assertIsNone(self.service.sessions[('demo','watch-1','synthetic_test')].advice)
    def test_camera_only_and_watch_only_explanations(self):
        self.service.explainer=Mock(return_value={'reason':'Measured model inputs.'})
        for modality,body in [('video',self.video),('watch',self.watch_body)]:
            key=('demo',modality,'synthetic_test')
            window={'start_ms':self.now-60000,'end_ms':self.now}
            self.service.update(modality,{**body,'session_id':modality,'window':window})
            self.service.future.result(timeout=2)
            for _ in range(100):
                state=self.service.state(key)
                if state['advice']['source']=='llm':break
                time.sleep(.001)
            self.assertEqual(state['advice']['source'],'llm')
            self.assertEqual(state['mode'],'video_only' if modality=='video' else 'watch_only')
            self.now+=10001
            self.assertIsNone(self.service.state(key)['advice'])
    def test_explanation_for_expired_window_is_discarded(self):
        release=threading.Event()
        self.service.explainer=lambda payload:(release.wait(2) and {'reason':'Expired explanation'})
        self.service.update('video',self.video)
        self.now+=10001;release.set();self.service.future.result(timeout=2)
        self.assertIsNone(self.service.state(('demo','watch-1','synthetic_test'))['advice'])
    def test_synthetic_data_never_sent_to_watch(self):
        relay=RelayWorker(self.service,ROOT);relay.relay=Mock()
        p=packet(100).model_dump(by_alias=True)
        relay.ingest({'phoneRecent':True,'watchSession':'watch-1','telemetry':p,'data_origin':'synthetic_test'})
        relay.send_latest();relay.send_camera_latest();relay.relay.send_model_result.assert_not_called()

class RelayReturnTests(unittest.TestCase):
    setUpClass = classmethod(ConnectedTests.setUpClass.__func__)
    setUp = ConnectedTests.setUp
    tearDown = ConnectedTests.tearDown
    def test_average_drives_score_and_action_in_either_direction(self):
        self.service.update('watch',self.watch_body);self.service.update('video',self.video)
        session=self.service.session(('demo','watch-1','synthetic_test'))
        for watch,video in [(0.9,0.1),(0.1,0.9),(0.8,0.8)]:
            session.watch.score,session.video.score=watch,video
            state=self.service.state(('demo','watch-1','synthetic_test'))
            self.assertEqual(state['score'],(watch+video)/2)
            self.assertEqual(state['advice']['weights'],{'watch':.5,'vision':.5})
            self.assertEqual(state['advice']['action'],'continue')
        self.now+=10001
        self.assertIsNone(self.service.state(('demo','watch-1','synthetic_test'))['score'])

    def test_oxygen_actual_timestamp_null_carry_and_session_reset(self):
        relay=RelayWorker(self.service,ROOT)
        p=packet(100).model_copy(update={'spo2Percent':97,'spo2AtMs':199000})
        def ingest(value):
            relay.ingest({'phoneRecent':True,'watchSession':value.session,'telemetry':value.model_dump(by_alias=True)})
        ingest(p)
        self.assertEqual(relay.info()['spo2_percent'],97)
        self.assertEqual(relay.info()['spo2_age_ms'],1000)
        self.now+=1000;ingest(packet(101))
        self.assertEqual(relay.info()['spo2_age_ms'],2000)
        self.now+=11000
        self.assertEqual(relay.info()['spo2_status'],'last_reading')
        self.now=1790000102000;ingest(packet(102,session='watch-2'))
        self.assertIsNone(relay.info()['spo2_percent'])

    def test_video_only_score_returns_when_watch_features_are_missing(self):
        self.video['data_origin']='live'
        state=self.service.update('video',self.video)
        relay=RelayWorker(self.service,ROOT);relay.relay=Mock()
        relay.relay.send_model_result.return_value={'commandId':'video-1','status':'queued'}
        relay.ingest({'phoneRecent':True,'watchSession':'watch-1',
                      'telemetry':packet(100,ibi=False).model_dump(by_alias=True)})
        relay.send_latest()
        args,kwargs=relay.relay.send_model_result.call_args
        self.assertEqual(args[3],'ready')
        self.assertAlmostEqual(args[1],state['score'])
        self.assertIn('video_only',args[2])
        self.assertEqual(kwargs['captured_at'],state['window_end_ms']/1000)
        relay.send_latest()
        self.assertEqual(relay.relay.send_model_result.call_count,1)

    def test_provisional_video_never_drives_watch_score_or_camera_alert(self):
        self.video.update(data_origin='live',schema_id='facial.rgb.geometry.v1')
        self.video['baseline_reference']=np.asarray(self.video['sequence'])[:,0].tolist()
        sequence=np.asarray(self.video['sequence']);sequence[:,:40]=0;self.video['sequence']=sequence.tolist()
        self.service.update('video',self.video)
        relay=RelayWorker(self.service,ROOT);relay.relay=Mock()
        relay.ingest({'phoneRecent':True,'watchSession':'watch-1','telemetry':packet(100).model_dump(by_alias=True)})
        relay.send_latest();relay.send_camera_latest()
        relay.relay.send_model_result.assert_not_called();relay.relay.send_camera_alert.assert_not_called()

    def test_fused_score_returns_through_existing_watch_envelope(self):
        self.identity['data_origin']='live';self.watch_body['data_origin']='live';self.video['data_origin']='live'
        self.service.update('watch',self.watch_body);fused=self.service.update('video',self.video)
        relay=RelayWorker(self.service,ROOT);relay.relay=Mock();relay.relay.send_model_result.return_value={'commandId':'cmd-1','status':'queued'}
        p=packet(100).model_dump(by_alias=True)
        snapshot={'phoneRecent':True,'watchSession':'watch-1','telemetry':p}
        relay.ingest(snapshot);relay.send_latest()
        args,kwargs=relay.relay.send_model_result.call_args
        self.assertAlmostEqual(args[1],fused['score']);self.assertEqual(args[3],'ready')
        self.assertEqual(kwargs['captured_at'],fused['window_end_ms']/1000)
        self.assertEqual(relay.delivery['state'],'queued_delivery_unconfirmed')
        relay.ingest({**snapshot,'events':[{'type':'command_result','commandId':'cmd-1','status':'accepted'}]})
        self.assertEqual(relay.delivery['state'],'accepted')
    def test_video_only_can_trigger_independent_watch_alert(self):
        self.video['data_origin']='live';self.service.update('video',self.video)
        relay=RelayWorker(self.service,ROOT);relay.relay=Mock()
        relay.ingest({'phoneRecent':True,'watchSession':'watch-1','telemetry':packet(100).model_dump(by_alias=True)})
        original=self.service.state
        state=original(('demo','watch-1','live'));state['advice']['action']='stop now'
        self.service.state=Mock(return_value=state)
        relay.send_camera_latest()
        relay.relay.send_camera_alert.assert_called_once()
        self.assertEqual(relay.relay.send_camera_alert.call_args.args[1],'high')

    def test_unknown_status_does_not_repeat_or_block_first_ready_window(self):
        relay=RelayWorker(self.service,ROOT);relay.relay=Mock()
        relay.relay.send_model_result.return_value={'commandId':'pending','status':'queued'}
        snapshot={'phoneRecent':True,'watchSession':'watch-1','telemetry':packet(100).model_dump(by_alias=True)}
        relay.ingest(snapshot);relay.send_latest();relay.send_latest()
        self.assertEqual(relay.relay.send_model_result.call_count,1)
        self.watch_body['data_origin']='live';self.service.update('watch',self.watch_body)
        relay.send_latest()
        self.assertEqual(relay.relay.send_model_result.call_count,2)
        self.assertIsNotNone(relay.relay.send_model_result.call_args.args[1])
    def test_valid_older_window_does_not_send_unknown_under_new_timestamp(self):
        self.watch_body['data_origin']='live';self.service.update('watch',self.watch_body)
        self.now+=3000
        relay=RelayWorker(self.service,ROOT);relay.relay=Mock()
        relay.ingest({'phoneRecent':True,'watchSession':'watch-1','telemetry':packet(103).model_dump(by_alias=True)})
        relay.send_latest();relay.relay.send_model_result.assert_not_called()

class LiveSensitivityTests(unittest.TestCase):
    def test_moderate_spike_and_repeated_polling_do_not_alert(self):
        session=Session()
        for _ in range(10):self.assertEqual(live_advisor(session,.8,10000)['action'],'continue')
        self.assertEqual(live_advisor(session,.6,15000)['action'],'continue')
        self.assertEqual(live_advisor(session,.8,20000)['action'],'continue')
    def test_warning_needs_three_windows_and_high_matches_watch_threshold(self):
        session=Session()
        for end in [10000,15000]:self.assertEqual(live_advisor(session,.8,end)['action'],'continue')
        self.assertEqual(live_advisor(session,.8,20000)['action'],'take a break at the next rest area')
        self.assertEqual(live_advisor(session,.8,40000)['action'],'continue')
        self.assertEqual(live_advisor(session,.9,45000)['action'],'stop now')
