"""Timestamped model inputs, live fused state and the existing phone return path."""
from flask import Blueprint, current_app, request
import os
import socket
from urllib.parse import urlsplit
from web.routes import json_object

router = Blueprint('live_inference', __name__)


def services():
    return current_app.extensions['model_service'], current_app.extensions['relay_worker']


@router.post('/api/live/<modality>')
def update(modality):
    if modality not in ('watch','video'): raise ValueError('Unknown modality')
    model, _ = services()
    return model.update(modality,json_object())


@router.post('/api/live/<modality>/stop')
def stop(modality):
    if modality not in ('watch','video'): raise ValueError('Unknown modality')
    model, _ = services()
    return model.clear(modality,json_object())


@router.get('/api/live/state')
def state():
    model, relay = services()
    info = relay.info()
    body = request.args.to_dict()
    body.setdefault('device_id',info['client_id'])
    body.setdefault('session_id',info['watch_session'] or 'browser')
    return {**model.state(model.identity(body)), 'relay':info}


@router.post('/api/baseline')
def baseline():
    model, _ = services()
    return model.set_baseline(json_object())


@router.post('/api/advisor/sample')
def advisor_sample():
    """Explicit sample; never enters live sessions, prediction logs or watch transport."""
    json_object()
    from src.features.facial_sequence import CHANNELS, FEATURES
    model, _ = services()
    sequence = [[0.0] * 60 for _ in CHANNELS]
    for index in (0, 1, 14):
        sequence[index] = [1.0] * 60
    features = dict.fromkeys(FEATURES, 0.0)
    features.update(left_eye_mean=1.0, right_eye_mean=1.0, valid_frame_fraction=1.0)
    result = model.offline({'facial': {'sequence':sequence,'channels':CHANNELS,'features':features}})
    advice = result['advice']
    if model.explainer:
        try:
            explanation = model.explainer({'action':advice['action'],'mode':'video_only',
                'data_origin':'synthetic_demo','score_kind':'uncalibrated_score',
                'watch_score':None,'watch_features':None,
                'video_score':result['score'],'video_features':features})
            advice = {**advice,'reason':explanation['reason'],'source':'llm',
                      'latency_ms':explanation.get('latency_ms')}
        except Exception:
            advice = {**advice,'source':'fallback'}
    return {**result,'advice':advice,'input_source':'synthetic_demo',
            'transport_eligible':False,'watch_alert_sent':False}


@router.post('/garmin/data')
def garmin():
    model, relay = services()
    relay.ingest(json_object())
    info = relay.info()
    if not info['watch_session']:
        return {'status':'collecting','score':None,'relay':info}
    return {**model.state((info['client_id'],info['watch_session'],'live')),'relay':info}


@router.post('/api/watch/send')
def send():
    json_object()
    _, relay = services()
    result = relay.send_latest()
    return {'delivery':result, 'watch_alert_sent':False,
            'note':'Queued is not a confirmed watch receipt'}


@router.post('/api/setup')
def setup():
    json_object()
    # Explicit same-origin UI action; the pairing token never goes into logs.
    if request.headers.get('Origin') != request.host_url.rstrip('/'):
        return {'error':'Open pairing details from the local dashboard'},403
    token=os.getenv('DROWSY_RELAY_TOKEN')
    if not token:return {'error':'Start with run_demo.py to configure the phone relay'},503
    port=urlsplit(os.getenv('DROWSY_RELAY_URL','http://127.0.0.1:8765')).port or 8765
    public_url = os.getenv('DROWSY_PHONE_URL')
    if public_url:
        parsed = urlsplit(public_url)
        if (parsed.scheme != 'http' or not parsed.hostname or not parsed.port
                or parsed.username or parsed.password or parsed.path not in ('', '/')
                or parsed.query or parsed.fragment):
            raise ValueError('DROWSY_PHONE_URL must be a plain HTTP relay address with a port')
        return {'client_id':os.getenv('DROWSY_RELAY_CLIENT_ID','demo'),'pairing_token':token,
                'relay_port':parsed.port,'phone_urls':[public_url.rstrip('/')],
                'note':'The Mac forwards phone data to the GX10 over SSH. Keep the bridge running.'}
    addresses=set()
    try:
        for _,_,_,_,addr in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET):
            if not addr[0].startswith('127.'):addresses.add(addr[0])
    except OSError:pass
    return {'client_id':os.getenv('DROWSY_RELAY_CLIENT_ID','demo'),'pairing_token':token,
            'relay_port':port, 'phone_urls':[f'http://{address}:{port}' for address in sorted(addresses)],
            'note':'Choose this Mac’s Wi-Fi/LAN address. localhost on iPhone points to the phone.'}
