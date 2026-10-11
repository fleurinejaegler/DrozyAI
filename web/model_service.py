"""Connect the shipped models, existing fusion and advisors to measured windows.

Artifact inference and transport are distinct: a loaded model is not evidence
that a raw Garmin packet has training-compatible features.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import hashlib
import math
import os
from pathlib import Path
import threading
import time
from typing import Any

import numpy as np

from realtime_backend.journal import PredictionJournal
from realtime_backend.schemas import Stream
from src.advisor.fallback import rule_based_advisor
from src.advisor.local_explanation import explain, MODEL as LLM_MODEL
from src.features.facial_sequence import CHANNELS, FEATURES
from src.features.fusion import fuse_scores
from src.models.predict import FEATURE_COLUMNS, predict_score
from web.routes import feature_values


def checked_score(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, np.number)):
        raise ValueError('score must be numeric')
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ValueError('score must be finite and in [0, 1]')
    return result


def baseline_video_score(raw, sequence, reference):
    """Attenuate the saved TCN by sustained changes from a neutral baseline.

    This is an explicit demo heuristic, not a fitted probability calibration.
    Ordinary blinks and static face geometry alone cannot raise the score.
    Missing observations stay missing and are handled separately by coverage.
    """
    reference=np.asarray(reference)
    if (reference.shape!=(15,) or reference.dtype.kind not in 'fiu' or
        not np.isfinite(reference).all() or (reference<0).any() or
        (reference[[0,1,9]]>2).any() or (reference[[2,3]]>1).any() or reference[14]!=1):
        raise ValueError('Camera baseline must be a finite 15-channel neutral reference')
    recent=np.asarray(sequence,dtype=float)[:,-15:]
    mask=recent[14]; observed=float(mask.sum())
    if observed<8:
        return 0.,{'raw_score':float(raw),'baseline_seconds':15,'baseline_adjusted':True,
                   'baseline_deviation':None,'baseline_recent_insufficient':True}
    mean=lambda channel:float(np.sum(recent[channel]*mask)/observed)
    peak=lambda channel:float(np.max(recent[channel][mask>0]))
    ramp=lambda value,noise,scale:max(0.,min(1.,(value-noise)/scale))
    changes={
        'excess_eye_closure':ramp(mean(2)-float(reference[2]),.08,.32),
        'excess_long_closure':ramp(mean(3)-float(reference[3]),.03,.17),
        'sustained_eye_closure':ramp(peak(4),1.5,2.5),
        # A mouth event alone is deliberately capped below the warning level.
        'sustained_mouth_opening':.6*ramp(peak(11),2.,4.)}
    deviation=max(changes.values())
    return checked_score(raw)*deviation,{
        'raw_score':float(raw),'baseline_seconds':15,'baseline_adjusted':True,
        'baseline_deviation':deviation,'baseline_signals':changes,
        'baseline_recent_insufficient':False}


def combine(watch, video, strategy='mean', watch_weight=0.5):
    if strategy not in {'mean', 'weighted', 'max', 'product'}:
        raise ValueError('strategy must be mean, weighted, max, or product')
    weight = checked_score(watch_weight)
    if watch is None and video is None:
        raise ValueError('At least one measured model input is required')
    watch = None if watch is None else checked_score(watch)
    video = None if video is None else checked_score(video)
    score = (video if watch is None else watch if video is None else
             checked_score(fuse_scores(np.array([watch]), np.array([video]),
                                      method=strategy, watch_weight=weight)[0]))
    return {'score': score, 'drowsiness_score': round(score * 100, 2),
            'score_type': 'uncalibrated_score',
            'mode': 'video_only' if watch is None else 'watch_only' if video is None else 'watch_video',
            'watch_score': watch, 'facial_score': video, 'strategy': strategy,
            'watch_weight': weight if strategy == 'weighted' else 0.5 if strategy == 'mean' else None}


@dataclass
class Component:
    score: float
    features: dict
    start: int
    end: int
    version: str
    model: str
    quality: dict = field(default_factory=dict)


@dataclass
class Session:
    watch: Component | None = None
    video: Component | None = None
    baseline: dict = field(default_factory=dict)
    history: list = field(default_factory=list)
    history_key: Any = None
    advice: dict | None = None
    advice_key: Any = None
    attempted_key: Any = None
    log_key: Any = None
    baseline_rows: list = field(default_factory=list)
    touched: int = 0
    generations: dict = field(default_factory=lambda: {"watch":0,"video":0})
    alert_windows: list = field(default_factory=list)


def live_advisor(session, score, end):
    """Match the watch's 70/90 thresholds and three-window warning confirmation."""
    rows=session.alert_windows
    if rows and end-rows[-1][0]>10_000:rows.clear()
    if not rows or end>rows[-1][0]:rows.append((end,score))
    elif end==rows[-1][0]:rows[-1]=(end,score)
    session.alert_windows=rows[-3:]
    if score>=.90:
        return {'action':'stop now','reason':'The experimental model score exceeds the high alert threshold. Stop as soon as it is safe.'}
    if len(session.alert_windows)==3 and all(value>=.70 for _,value in session.alert_windows):
        return {'action':'take a break at the next rest area','reason':'The experimental model score stayed elevated for three model updates. Plan a break.'}
    return {'action':'continue','reason':'Elevated score awaiting three consecutive updates.' if score>=.70 else 'Experimental score is below the alert threshold; keep monitoring.'}


class ModelService:
    def __init__(self, watch_model, facial_models, root: Path, *, now=None, llm=True):
        self.watch_model, self.facial_models = watch_model, facial_models
        self.now = now or (lambda: round(time.time() * 1000))
        self.lock, self.watch_lock = threading.RLock(), threading.Lock()
        self.sessions = {}
        self.versions = {name: hashlib.sha256((root/'data/processed'/file).read_bytes()).hexdigest()[:12]
                         for name, file in [('watch','baseline_model.pkl'), ('small_tcn','small_tcn.pt'),
                                            ('logistic_regression','facial_model.pkl')]}
        self.explainer = explain if llm else None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='local-advisor')
        self.future = None
        self.closed = False
        self.journal = PredictionJournal(Path(os.getenv('DROZY_LOG_DIRECTORY',str(root/'realtime_backend/data'))))
        self.journal.start()

    def close(self):
        if self.closed: return
        self.closed = True
        self.journal.close()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def watch(self, value):
        features = feature_values(value, FEATURE_COLUMNS)
        if not 0 < features['hr_mean'] <= 250 or features['rmssd'] < 0 or features['motion_var'] < 0:
            raise ValueError('Invalid watch feature range')
        with self.watch_lock:
            score = checked_score(predict_score(features, model=self.watch_model))
        return {'score': score, 'drowsiness_score': round(score * 100, 2),
                'model': 'teammate_watch_baseline', 'score_type': 'uncalibrated_score',
                'version': self.versions['watch'], 'features': features,
                'source': 'provided_features', 'live_garmin_adapter_ready': True, 'garmin_transfer_validated': False}

    def facial(self, body, *, allow_partial=False):
        if not isinstance(body, dict):
            raise ValueError('facial must be an object')
        model = body.get('model', 'small_tcn')
        features = {}
        calibration = {}
        if model == 'small_tcn':
            score = self.facial_models.predict_tcn(body.get('sequence'), body.get('channels'), allow_partial=allow_partial)
            if body.get('schema_id')=='facial.rgb.geometry.v1' and body.get('baseline_reference') is not None:
                score,calibration=baseline_video_score(score,body['sequence'],body['baseline_reference'])
            if 'features' in body:
                features = feature_values(body['features'], FEATURES)
        elif model == 'logistic_regression':
            features = feature_values(body.get('features'), FEATURES)
            score = self.facial_models.predict_logistic(features)
        else:
            raise ValueError('model must be small_tcn or logistic_regression')
        score = checked_score(score)
        return {'score': score, 'drowsiness_score': round(score * 100, 2), 'model': model,
                'version': self.versions[model], 'score_type': 'uncalibrated_score',
                'source': 'provided_features', 'features': features, 'calibration':calibration,
                'live_camera_adapter_ready': True, 'rgb_transfer_validated': False}

    def offline(self, body):
        if any(k in body for k in ('watch_score', 'facial_score')):
            raise ValueError('Supply watch_features and/or facial model inputs; client scores are not model predictions')
        watch = self.watch(body['watch_features']) if body.get('watch_features') is not None else None
        video = self.facial(body['facial']) if body.get('facial') is not None else None
        result = combine(watch['score'] if watch else None, video['score'] if video else None,
                         body.get('strategy','mean'), body.get('watch_weight',0.5))
        advice = rule_based_advisor(result['score'])
        return {**result, 'components': {'watch': watch, 'video': video},
                'advice': {**advice, 'source': 'fallback', 'confidence': None},
                'input_source': 'provided_features', 'watch_alert_sent': False,
                'transport_eligible': False}

    def identity(self, body):
        stream = Stream.model_validate({k: body[k] for k in ('device_id','session_id','data_origin') if k in body})
        return stream.device_id, stream.session_id, stream.data_origin

    def session(self, key):
        now = self.now()
        for old in list(self.sessions):
            if now - self.sessions[old].touched > 600_000:
                del self.sessions[old]
        if key not in self.sessions:
            if len(self.sessions) >= 8:
                raise ValueError('Too many active sessions')
            self.sessions[key] = Session()
        result = self.sessions[key]
        result.touched = now
        return result

    def update(self, modality, body):
        key = self.identity(body)
        with self.lock:
            session = self.session(key)
            generation = session.generations[modality]
        try:
            window = body.get('window', {})
            start, end = window.get('start_ms'), window.get('end_ms')
            if (type(start) is not int or type(end) is not int or end-start != 60_000 or
                not 0 <= self.now()-end <= 10_000):
                raise ValueError('Supply a fresh trailing 60000-ms window in Mac UTC epoch milliseconds')
            if modality == 'watch':
                if body.get('schema_id') not in ('watch.uldd.four.v1','watch.garmin.transfer.v1'):
                    raise ValueError('Watch inputs must declare schema_id watch.uldd.four.v1 and use its training preprocessing')
                result = self.watch(body.get('features'))
            else:
                if body.get('schema_id') not in ('facial.uldd.tcn15.v1','facial.rgb.geometry.v1'):
                    raise ValueError('Unsupported facial preprocessing schema')
                if body.get('schema_id')=='facial.rgb.geometry.v1' and body.get('baseline_reference') is None:
                    raise ValueError('Restart the camera to capture a 15-second neutral baseline')
                result = self.facial(body, allow_partial=body.get('schema_id')=='facial.rgb.geometry.v1')
        except Exception:
            with self.lock:
                if generation == session.generations[modality]:
                    setattr(session, modality, None)
                    session.advice = None
            raise
        with self.lock:
            if generation != session.generations[modality]:
                return self.state(key)
            previous = getattr(session, modality)
            if previous is not None and end <= previous.end:
                return self.state(key)
            quality=dict(body.get('quality',{}))
            quality.update(result.get('calibration',{}))
            if modality=='video' and body.get('model','small_tcn')=='small_tcn':
                mask=np.asarray(body['sequence'],dtype=float)[14]
                quality.update(observed_seconds=float(mask.sum()), valid_fraction=float(mask.mean()),
                               partial_window=bool(mask.mean()<0.9 or mask.min()<0.5))
            setattr(session, modality, Component(result['score'], result['features'], start, end,
                                                 result['version'], result['model'], quality))
            session.advice = None
            if sum(source==modality for source,_ in session.baseline_rows)<12:
                session.baseline_rows.append((modality,dict(result['features'])))
                for name,prefix in [('watch','w'),('video','v')]:
                    rows=[values for source,values in session.baseline_rows if source==name]
                    if len(rows)>=6:
                        for feature in rows[0]:
                            values=[row[feature] for row in rows if feature in row]
                            session.baseline.setdefault(prefix+'_'+feature+'_mean',float(np.mean(values)))
                            session.baseline.setdefault(prefix+'_'+feature+'_std',float(np.std(values)))
            return self.state(key)

    def clear(self, modality, body):
        key = self.identity(body)
        with self.lock:
            session = self.session(key)
            session.generations[modality] += 1
            setattr(session, modality, None)
            session.advice = None
            return self.state(key)

    def set_baseline(self, body):
        baseline = body.get('baseline')
        if not isinstance(baseline, dict) or len(baseline) > 100:
            raise ValueError('baseline must be a numeric dictionary with at most 100 entries')
        values = feature_values(baseline, list(baseline))
        if any(k.endswith('_std') and v < 0 for k,v in values.items()):
            raise ValueError('Baseline standard deviations cannot be negative')
        with self.lock:
            session = self.session(self.identity(body))
            session.baseline = values
            session.advice = session.advice_key = session.attempted_key = None
        return {'status':'ok'}

    def state(self, key):
        with self.lock:
            session = self.session(key)
            now = self.now()
            watch = session.watch if session.watch and 0 <= now-session.watch.end <= 10_000 else None
            video = session.video if session.video and 0 <= now-session.video.end <= 10_000 else None
            provisional = video if video and (video.quality.get('partial_window') or video.quality.get('baseline_recent_insufficient')) else None
            if provisional:video=None
            reason = None
            if watch and video and abs(watch.end-video.end) > 2000:
                video, reason = None, 'VIDEO_WINDOW_NOT_ALIGNED'
            if not watch and not video:
                if provisional:
                    return {'status':'provisional','score':None,'drowsiness_score':None,'score_type':'none',
                            'mode':'none','advice':None,'reason':'PARTIAL_VIDEO_PROVISIONAL',
                            'components':{'watch':None,'video':{'score':provisional.score,'model':provisional.model,
                                'version':provisional.version,'window_start_ms':provisional.start,
                                'window_end_ms':provisional.end,'quality':provisional.quality}},
                            'valid_for_ms':provisional.end+10_000-now,'window_end_ms':provisional.end,
                            'watch_alert_sent':False}
                return {'status':'collecting', 'score':None, 'drowsiness_score':None,
                        'score_type':'none', 'mode':'none', 'advice':None,
                        'reason':'NO_FRESH_MODEL_WINDOW', 'watch_alert_sent':False}
            result = combine(watch.score if watch else None, video.score if video else None, strategy='mean')
            weights = {'watch':1.0 if video is None else 0.0 if watch is None else 0.5,
                       'vision':0.0 if video is None else 1.0 if watch is None else 0.5}
            source_key = tuple((x.model,x.version,x.end) if x else None for x in (watch,video))
            trend = result['score']-session.history[0] if session.history else 0.0
            if source_key != session.history_key:
                session.history = (session.history+[result['score']])[-10:]
                session.history_key = source_key
            base = {**live_advisor(session,result['score'],min(x.end for x in (watch,video) if x)), 'source':'fallback',
                    'fused_score':result['score'],
                    'llm_status':'waiting' if self.explainer else 'disabled',
                    'model':LLM_MODEL, 'compute_host':os.getenv('DROWSY_COMPUTE_LABEL','local'),
                    'confidence':None, 'weights':weights}
            if session.advice_key == source_key and session.advice:
                base = session.advice
            elif self.explainer and session.attempted_key != source_key and not self.closed:
                if self.future is None or self.future.done():
                    session.attempted_key = source_key
                    base['llm_status'] = 'generating'
                    fixed_advice = dict(base)
                    revision = (id(session.watch), id(session.video), dict(session.generations))
                    payload = {'action':base['action'], 'mode':result['mode'],
                               'score_kind':'uncalibrated_score',
                               'watch_score':watch.score if watch else None,
                               'video_score':video.score if video else None,
                               'watch_features':dict(watch.features) if watch else None,
                               'video_features':dict(video.features) if video else None}
                    self.future = self.executor.submit(self.explainer, payload)
                    def accept(future):
                        try:
                            output = future.result()
                            text = output.get('reason') if isinstance(output,dict) else None
                            if not isinstance(text,str) or not text.strip() or len(text.strip()) > 400:
                                raise ValueError('Invalid explanation')
                            # Only copy explanation fields; never accept model-generated actions or scores.
                            accepted = {**fixed_advice,'reason':text.strip(),'source':'llm','llm_status':'ready'}
                            if isinstance(output.get('latency_ms'),(int,float)):
                                accepted['latency_ms'] = output['latency_ms']
                        except Exception:
                            accepted = {**fixed_advice,'llm_status':'fallback'}
                        with self.lock:
                            if self.closed or self.sessions.get(key) is not session: return
                            current = (id(session.watch), id(session.video), session.generations)
                            if current == revision and all(0 <= self.now()-x.end <= 10_000 for x in (watch,video) if x):
                                session.advice, session.advice_key = accepted, source_key
                    self.future.add_done_callback(accept)
            elif self.explainer and session.attempted_key == source_key:
                base['llm_status'] = 'generating'
            components = {name: None if x is None else {'score':x.score,'model':x.model,'version':x.version,
                          'window_start_ms':x.start,'window_end_ms':x.end,'quality':x.quality}
                          for name,x in [('watch',watch),('video',video or provisional)]}
            log_key = source_key, result['score'], base['source']
            if session.log_key != log_key:
                session.log_key = log_key
                label = 'DROWSY' if result['score']>=0.5 else 'ALERT'
                row = {'timestamp_ms':now,'device_id':key[0],'session_id':key[1],'data_origin':key[2],
                    'raw_final_prediction':label,'final_prediction':label,'final_score':result['score'],
                    'inference_mode':result['mode'],'video_enabled':video is not None,'reason':base['source']}
                for name,component in [('watch',watch),('video',video)]:
                    if component:
                        row.update({name+'_prediction':'DROWSY' if component.score>=0.5 else 'ALERT',
                                    name+'_score':component.score,name+'_score_kind':'uncalibrated_score',
                                    name+'_window_start_ms':component.start,name+'_window_end_ms':component.end,
                                    name+'_model_version':component.model+':'+component.version,
                                    name+'_data_age_ms':now-component.end})
                self.journal.enqueue(row)
            return {**result, 'status':'ok','advice':base,'components':components,
                    'window_end_ms':min(x.end for x in (watch,video) if x),
                    'valid_for_ms':min(x.end+10_000-now for x in (watch,video) if x),
                    'reason':reason,'device_id':key[0],'session_id':key[1],'data_origin':key[2],
                    'watch_alert_sent':False}
