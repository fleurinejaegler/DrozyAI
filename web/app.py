"""Local Flask dashboard, optional Garmin HR bridge and frozen model inference."""
from __future__ import annotations

import argparse
import ast
import atexit
import os
import json
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlsplit

# Support `python web/app.py` without changing the teammate-owned src package.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from web.routes import json_object
from web.routes.watch import HeartRateBridge


def create_app(*, watch_model: Any = None, facial_models: Any = None,
               bridge: Any = None, prepare_only: bool = False,
               llm_enabled: bool | None = None, relay_enabled: bool = True) -> Flask:
    """Load trusted artifacts once and expose only the static web directory."""
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config.update(MAX_CONTENT_LENGTH=512 * 1024, JSON_SORT_KEYS=False)
    if prepare_only:
        # Inspect source declarations only; never import/load/choose ML artifacts.
        feature_columns = []
        tree = ast.parse((ROOT / 'src/models/baseline.py').read_text(encoding='utf-8-sig'))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'FEATURE_COLUMNS' for t in node.targets):
                feature_columns = ast.literal_eval(node.value)
        channels, facial_features = [], []
        routers = ()
        app.extensions['watch_model'] = None
        app.extensions['facial_models'] = None
    else:
        import torch
        from src.features.facial_sequence import CHANNELS, FEATURES
        from src.models.facial_baseline import FacialModels
        from src.models.predict import FEATURE_COLUMNS, load_model
        from web.routes.facial import router as facial_router
        from web.routes.fusion import router as fusion_router
        from web.routes.score import router as score_router
        torch.set_num_threads(1)
        feature_columns, channels, facial_features = FEATURE_COLUMNS, CHANNELS, FEATURES
        from web.routes.live import router as live_router
        routers = (score_router, facial_router, fusion_router, live_router)
        app.extensions['watch_model'] = load_model(ROOT / 'data/processed/baseline_model.pkl') if watch_model is None else watch_model
        app.extensions['facial_models'] = FacialModels.load() if facial_models is None else facial_models
        from web.model_service import ModelService
        from web.relay_worker import RelayWorker
        service = ModelService(app.extensions['watch_model'], app.extensions['facial_models'], ROOT,
            llm=(os.getenv('DROZY_LLM_DISABLED','0') != '1') if llm_enabled is None else llm_enabled)
        relay = RelayWorker(service, ROOT, token=os.getenv('DROWSY_RELAY_TOKEN') if relay_enabled else None,
            url=os.getenv('DROWSY_RELAY_URL','http://127.0.0.1:8765'),
            client_id=os.getenv('DROWSY_RELAY_CLIENT_ID','demo'))
        app.extensions['model_service'], app.extensions['relay_worker'] = service, relay
        atexit.register(service.close)
        atexit.register(relay.close)
        relay.start()
    app.extensions["watch_bridge"] = HeartRateBridge() if bridge is None else bridge

    @app.before_request
    def local_request() -> Any:
        """Reject cross-site actions and Host headers outside local loopback."""
        host = urlsplit("http://" + request.host).hostname
        if host not in {"localhost", "127.0.0.1"}:
            return jsonify(error="Use the local dashboard address"), 403
        if request.method == "POST":
            origin = request.headers.get("Origin")
            if origin is not None and origin != request.host_url.rstrip("/"):
                return jsonify(error="Cross-origin actions are not allowed"), 403
            if request.path in {"/api/scan", "/api/connect", "/api/disconnect"} and origin is None:
                return jsonify(error="Open Bluetooth actions from the local dashboard"), 403
            if request.mimetype != "application/json":
                return jsonify(error="Content-Type application/json is required"), 415
        return None

    @app.after_request
    def local_headers(response: Any) -> Any:
        """Avoid caches of readings and disable unused browser permissions."""
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "Permissions-Policy": "camera=(self), microphone=(), geolocation=()"})
        return response

    @app.errorhandler(ValueError)
    def invalid_input(error: ValueError) -> Any:
        return jsonify(error=str(error)), 400

    from pydantic import ValidationError
    @app.errorhandler(ValidationError)
    def invalid_schema(error: ValidationError) -> Any:
        return jsonify(error='Invalid input schema', detail=json.loads(error.json(include_input=False))), 400

    @app.errorhandler(HTTPException)
    def http_error(error: HTTPException) -> Any:
        return jsonify(error=error.description), error.code

    @app.get("/")
    def index() -> Any:
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        from src.advisor.local_explanation import MODEL as llm_model
        return {"ok": True, "compute_host": os.getenv("DROWSY_COMPUTE_LABEL", "local"), "models_loaded": [] if prepare_only else ["teammate_watch_baseline", "small_tcn", "logistic_regression"],
                "local_llm": {"enabled": not prepare_only and app.extensions['model_service'].explainer is not None,
                              "model": llm_model, "role": "explanation_only"},
                "prepare_only": prepare_only,
                "live_camera_tcn": not prepare_only, "live_watch_model": not prepare_only,
                "watch_features_required": True,
                "watch_alert_transport": not prepare_only and app.extensions['relay_worker'].relay is not None,
                "score_type": "uncalibrated_score", "rgb_transfer_validated": False}

    if not prepare_only:
        app.add_url_rule('/health', 'connected_health', health)

    @app.get("/api/models")
    def models() -> dict[str, Any]:
        return {"watch": {"features": feature_columns, "window_seconds": 60,
                          "live_note": "Bluetooth HR alone does not supply the watch model's complete feature window."},
                "facial": {"channels": channels, "sequence_shape": [15, 60],
                           "seconds_order": "oldest_to_newest", "logistic_features": facial_features,
                           "score_type": "uncalibrated_score", "live_adapter_ready": not prepare_only,
                           "note": "Original 68-point features accepted. Live RGB mesh geometry is an experimental transfer; blendshape scores are not model inputs."}}

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        return app.extensions["watch_bridge"].snapshot()

    @app.post("/api/<action>")
    def watch_action(action: str) -> Any:
        body = json_object()
        reader = app.extensions["watch_bridge"]
        if action == "scan":
            operation = reader.scan()
        elif action == "connect":
            operation = reader.connect(body.get("id"))
        elif action == "disconnect":
            operation = reader.disconnect()
        else:
            return jsonify(error="Unknown action"), 404
        try:
            return reader.submit(operation)
        except ValueError:
            raise
        except Exception:
            return jsonify(error="Bluetooth action did not finish; check the watch and Mac permissions"), 503

    if prepare_only:
        @app.post('/api/score')
        @app.post('/api/facial')
        @app.post('/api/fusion')
        def pending_inference() -> Any:
            return jsonify(error='Models are intentionally disconnected in preparation mode',
                           status='MODEL_NOT_CONFIGURED', score=None), 503
        from realtime_backend.flask_routes import register_runtime
        from realtime_backend.repository import RepositoryFunctions
        from realtime_backend.service import Runtime
        register_runtime(app, Runtime(score_fuser=RepositoryFunctions(ROOT).fuse_scores))
    for router in routers:
        app.register_blueprint(router)
    return app


def main() -> None:
    """Run on loopback without the interactive debugger or a second model load."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8777)
    parser.add_argument('--prepare-only', action='store_true',
                        help='Use the existing page with model connections disabled and streaming interfaces ready')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    app = create_app(prepare_only=args.prepare_only)
    print(f"Drowsy packaged app: http://127.0.0.1:{args.port}/", flush=True)
    try:
        app.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False, threaded=True)
    finally:
        if 'relay_worker' in app.extensions:
            app.extensions['relay_worker'].close()
            app.extensions['model_service'].close()
        if 'realtime_runtime' in app.extensions:
            app.extensions['realtime_runtime'].close()
        bridge = app.extensions["watch_bridge"]
        bridge.submit(bridge.disconnect())
        bridge.loop.call_soon_threadsafe(bridge.loop.stop)


if __name__ == "__main__":
    main()
