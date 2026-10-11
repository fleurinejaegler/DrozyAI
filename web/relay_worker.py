"""Use the existing authenticated phone relay; never turn raw fields into guesses."""
from collections import deque
from copy import deepcopy
import importlib.util
import threading
import time
from urllib.error import HTTPError

from realtime_backend.telemetry import Telemetry
from web.garmin_features import GarminWindow


class RelayWorker:
    def __init__(self, models, root, *, token=None, url='http://127.0.0.1:8765', client_id='demo', monotonic=None):
        self.models, self.client_id = models, client_id
        self.monotonic = monotonic or time.monotonic
        self.lock = threading.RLock()
        self.snapshot = None
        self.packets = deque(maxlen=2048)
        self.last_sequence = None
        self.status = 'not_configured' if not token else 'connecting'
        self.delivery = None
        self.stop_event = threading.Event()
        self.thread = None
        self.sent_key = None
        self.last_send = 0
        self.relay = None
        self.preprocessor = GarminWindow()
        self.camera_key = None
        self.recovery_count = 0
        self.camera_alert_active = None  # Unknown after a backend restart.
        self.oxygen = None
        self.oxygen_at = None
        self.oxygen_epoch = None
        if token:
            path = root/'phone-companion/local-relay/gateway_client.py'
            spec = importlib.util.spec_from_file_location('drowsy_gateway', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.relay = module.RelayClient(url, token, client_id)

    def start(self):
        if self.relay:
            self.thread = threading.Thread(target=self._run, daemon=True, name='phone-relay')
            self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread: self.thread.join(timeout=6)

    def ingest(self, snapshot):
        if not isinstance(snapshot,dict) or snapshot.get('phoneRecent') is not True or not snapshot.get('telemetry'):
            with self.lock:
                self.status, self.snapshot = 'waiting_for_phone_or_watch', None
            return
        packet = Telemetry.model_validate(snapshot['telemetry'])
        if packet.session != snapshot.get('watchSession') or not 0 <= self.models.now()-round(packet.sentAt*1000) <= 10_000:
            raise ValueError('Wrong-session or stale watch telemetry')
        with self.lock:
            key = packet.session, packet.sequence
            if self.last_sequence and self.last_sequence[0] == packet.session and packet.sequence < self.last_sequence[1]:
                raise ValueError('Out-of-order watch telemetry')
            if self.last_sequence and self.last_sequence[0] != packet.session:
                self.packets.clear()
                self.oxygen = self.oxygen_at = self.oxygen_epoch = None
            if (packet.spo2Percent is not None and 0 < packet.spo2Percent <= 100 and
                    packet.spo2AtMs is not None and
                    (self.oxygen_at is None or packet.spo2AtMs > self.oxygen_at)):
                self.oxygen, self.oxygen_at = packet.spo2Percent, packet.spo2AtMs
                self.oxygen_epoch = round(packet.sentAt*1000)-packet.watchUptimeMs+packet.spo2AtMs
            if key != self.last_sequence:
                self.packets.append(packet)
                self.last_sequence = key
            self.snapshot = deepcopy(snapshot)
            if self.delivery:
                command_id = self.delivery.get('receipt',{}).get('commandId')
                for event in snapshot.get('events',[]):
                    if event.get('type')=='command_result' and event.get('commandId')==command_id:
                        self.delivery['state'] = event.get('status','delivery_unknown')
                    elif event.get('type')=='user_acknowledged':
                        self.delivery['acknowledgment'] = dict(event)
            self.status = 'connected_raw_features_pending'
        # Future companion preprocessing may supply this explicit contract.
        # Raw HR/RMSSD alone are deliberately not substituted for model inputs.
        prepared = snapshot.get('modelFeatures')
        if prepared is None:
            prepared = self.preprocessor.ingest(packet)
            if prepared is not None: prepared['quality'] = dict(self.preprocessor.quality)
        if prepared is not None:
            self.models.update('watch', {**prepared, 'device_id':self.client_id,
                'session_id':packet.session, 'data_origin':snapshot.get('data_origin','live')})
            with self.lock: self.status = 'connected_models_running'

    def info(self):
        with self.lock:
            snapshot = self.snapshot
            fresh = bool(snapshot and 0 <= self.models.now()-round(snapshot['telemetry']['sentAt']*1000) <= 10_000)
            quality=dict(self.preprocessor.quality)
            if self.preprocessor.temperature_at is not None and self.preprocessor.epoch_offset is not None:
                quality['temperature_age_ms']=max(0,self.models.now()-(self.preprocessor.epoch_offset+self.preprocessor.temperature_at))
            oxygen_age = None if self.oxygen_epoch is None else max(0,self.models.now()-self.oxygen_epoch)
            return {'status':self.status if fresh or snapshot is None else 'stale',
                    'watch_session':snapshot['watchSession'] if fresh else None,
                    'client_id':self.client_id,'raw_packets_buffered':len(self.packets),
                    'watch_features_ready':not self.preprocessor.quality.get('missing'),'delivery':self.delivery,
                    'quality':quality,
                    'heart_rate_bpm':snapshot['telemetry'].get('heartRateBpm') if fresh else None,
                    'heart_rate_time_s':snapshot['telemetry']['sentAt'] if fresh else None,
                    'spo2_percent':self.oxygen, 'spo2_age_ms':oxygen_age,
                    'spo2_status':'unavailable' if self.oxygen is None else 'live' if fresh and oxygen_age <= 10_000 else 'last_reading',
                    'note':'Experimental Garmin transfer; first real temperature required, then carried on null; genuine IBI required'}

    def send_latest(self):
        with self.lock: snapshot = deepcopy(self.snapshot)
        if not self.relay or not snapshot or snapshot.get('data_origin','live') != 'live': return None
        packet = snapshot['telemetry']
        now = self.models.now()
        if not 0 <= now-round(packet['sentAt']*1000) <= 10_000: return None
        key = self.client_id, packet['session'], 'live'
        state = self.models.state(key)
        watch = state.get('components',{}).get('watch')
        video = state.get('components',{}).get('video')
        primary = watch or video
        usable = (state['status']=='ok' and primary is not None and
                  abs(primary['window_end_ms']-round(packet['sentAt']*1000)) <= 2000 and
                  abs(state['window_end_ms']-round(packet['sentAt']*1000)) <= 2000)
        # A still-valid previous window is not a new unknown prediction. Sending
        # null every five seconds here can consume the phone/watch rate limit
        # just before the next ready window arrives, or replace it in the queue.
        if primary is not None and not usable: return self.delivery
        stamp = ((packet['session'],state['window_end_ms'],state['score']) if usable
                 else (packet['session'],'unavailable'))
        if stamp == self.sent_key: return self.delivery
        if usable and self.delivery and self.delivery.get('score') is not None and self.monotonic()-self.last_send < 5:
            return self.delivery
        score = state['score'] if usable else None
        receipt = self.relay.send_model_result(snapshot,score,
            'research-'+state['mode']+'-'+primary['version'] if usable else 'research-waiting',
            'ready' if usable else 'insufficient_data',
            captured_at=state['window_end_ms']/1000 if usable else packet['sentAt'])
        self.last_send, self.sent_key = self.monotonic(), stamp
        with self.lock: self.delivery = {'state':'queued_delivery_unconfirmed','receipt':receipt,
                                        'score':score,'input_sequence':packet['sequence']}
        return self.delivery

    def send_camera_latest(self):
        with self.lock: snapshot = deepcopy(self.snapshot)
        if not self.relay or not snapshot or snapshot.get('data_origin','live') != 'live': return
        if not 0 <= self.models.now()-round(snapshot['telemetry']['sentAt']*1000) <= 10_000: return
        state = self.models.state((self.client_id,snapshot['watchSession'],'live'))
        video = state.get('components',{}).get('video')
        if state['status'] != 'ok' or video is None: return
        stamp = snapshot['watchSession'],video['window_end_ms']
        if stamp == self.camera_key: return
        self.camera_key = stamp
        action = state['advice']['action']
        captured = video['window_end_ms']/1000
        if action in ('stop now','take a break at the next rest area'):
            self.recovery_count = 0
            receipt = self.relay.send_camera_alert(snapshot,'high' if action=='stop now' else 'warning',captured)
            self.camera_alert_active = True
        else:
            self.recovery_count += 1
            if self.recovery_count < 3 or self.camera_alert_active is False: return
            receipt = self.relay.clear_camera_alert(snapshot,captured)
            self.camera_alert_active = False
        with self.lock: self.delivery = {'state':'queued_delivery_unconfirmed','receipt':receipt,'source':'video_or_fused_advice'}

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self.ingest(self.relay.state())
                self.send_latest()
                self.send_camera_latest()
            except HTTPError as exc:
                with self.lock:
                    self.status = ('waiting_for_phone_or_watch' if exc.code==404 else
                                   'pairing_token_rejected' if exc.code==401 else 'relay_http_error')
                    if exc.code==404:self.snapshot=None
            except Exception as exc:
                with self.lock: self.status = 'relay_unavailable_or_invalid: '+type(exc).__name__
            # Poll faster than the 1-Hz producer so phase drift does not discard
            # a watch packet before the next latest-value snapshot is read.
            self.stop_event.wait(0.2)
