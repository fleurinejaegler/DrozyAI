"""Optional blueprint for the existing Flask backend. No replacement web app."""
import atexit
import json
import time

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from .runner import RuntimeRunner
from .schemas import ClockSync, Stream, VideoBatch, WatchBatch
from .telemetry import ingest_relay_snapshot


def register_runtime(app, runtime=None):
    if 'realtime_runtime' in app.extensions:
        return app.extensions['realtime_runtime']
    runner = RuntimeRunner(runtime)
    app.extensions['realtime_runtime'] = runner
    atexit.register(runner.close)
    router = Blueprint('realtime_runtime', __name__)
    existing_limit = app.config.get('MAX_CONTENT_LENGTH')
    app.config['MAX_CONTENT_LENGTH'] = min(existing_limit, runner.runtime.settings.max_body_bytes) if existing_limit else runner.runtime.settings.max_body_bytes
    rt = runner.runtime

    @router.errorhandler(ValidationError)
    def invalid_schema(exc):
        return jsonify(error='Invalid message', detail=json.loads(exc.json(include_input=False))), 422

    @router.errorhandler(ValueError)
    def invalid_input(exc):
        return jsonify(error=str(exc)), 422

    @router.errorhandler(KeyError)
    def missing_session(exc):
        return jsonify(error=str(exc)), 404

    @router.errorhandler(OverflowError)
    def full_sessions(exc):
        return jsonify(error=str(exc)), 429

    def body():
        if not request.is_json:
            raise ValueError('Content-Type application/json is required')
        value = request.get_json()
        if not isinstance(value, dict):
            raise ValueError('Send a JSON object')
        return value

    def identity(message):
        return Stream(**message.model_dump(include={'device_id', 'session_id', 'data_origin'}))

    @router.get('/health')
    def health():
        return runner.invoke(lambda: {'status': 'ok', 'models': rt.models.status(),
                                     'logging': rt.journal.status(), 'server_id': rt.server_id})

    @router.get('/clock/ping')
    def ping():
        stream = Stream.model_validate(request.args.to_dict())
        return runner.invoke(rt.streams.ping, stream)

    @router.post('/clock/sync')
    def sync():
        payload = ClockSync.model_validate(body())
        def run():
            mapping = rt.streams.synchronize(payload)
            return {'status': mapping.quality, 'offset_ms': mapping.offset_ms,
                    'uncertainty_ms': mapping.uncertainty_ms, 'clock_revision': mapping.revision}
        return runner.invoke(run)

    @router.post('/garmin/data')
    def garmin():
        payload = body()
        batch = WatchBatch.model_validate(payload) if 'telemetry' not in payload else None
        started = time.perf_counter()
        client_id = request.args.get('client_id', 'demo')
        def run():
            # State changes and snapshots remain on the runtime's event loop.
            if batch is None:
                current = ingest_relay_snapshot(rt, payload, client_id)
                if current is None:
                    return {'status': 'collecting', 'verdict': 'INSUFFICIENT_DATA',
                            'score': None, 'reason': 'PHONE_OR_TELEMETRY_UNAVAILABLE'}
                return rt.latest(current, (time.perf_counter() - started) * 1000)
            current = rt.streams.get(identity(batch), create=True)
            accepted = current.ingest_watch(batch, rt.clock.now_ms())
            return {**rt.latest(current, (time.perf_counter() - started) * 1000),
                    'batch_id': batch.batch_id, 'batch_accepted': accepted}
        return runner.invoke(run)

    @router.get('/prediction/latest')
    def latest():
        arguments = request.args.to_dict()
        return runner.invoke(lambda: rt.latest(rt.streams.get(Stream.model_validate(arguments))))

    @router.get('/prediction/status')
    def status():
        arguments = request.args.to_dict()
        return runner.invoke(lambda: rt.status(rt.streams.get(Stream.model_validate(arguments))))

    @router.post('/video/start')
    def video_start():
        stream = Stream.model_validate(body())
        def run():
            current = rt.streams.get(stream, create=True)
            current.toggle_video(True)
            return {'video_enabled': True, 'camera_started': False, 'camera_status': current.camera_status}
        return runner.invoke(run)

    @router.post('/video/stop')
    def video_stop():
        stream = Stream.model_validate(body())
        def run():
            current = rt.streams.get(stream)
            current.toggle_video(False)
            rt.latest(current)
            return {'video_enabled': False, 'camera_started': False}
        return runner.invoke(run)

    @router.post('/video/features')
    def video_features():
        batch = VideoBatch.model_validate(body())
        def run():
            current = rt.streams.get(identity(batch))
            accepted = current.ingest_video(batch, rt.clock.now_ms())
            return {'batch_accepted': accepted, 'prediction': rt.latest(current)}
        return runner.invoke(run)

    app.register_blueprint(router)
    return runner
