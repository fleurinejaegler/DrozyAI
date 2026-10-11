"""Local Flask dashboard, optional Garmin HR bridge and frozen model inference."""
from __future__ import annotations

import argparse
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
import torch

from src.features.video_features import CHANNELS, FEATURES
from src.models.facial_baseline import FacialModels
from src.models.predict import FEATURE_COLUMNS, load_model
from web.routes import json_object
from web.routes.facial import router as facial_router
from web.routes.fusion import router as fusion_router
from web.routes.score import router as score_router
from web.routes.watch import HeartRateBridge


def create_app(*, watch_model: Any = None, facial_models: Any = None,
               bridge: Any = None) -> Flask:
    """Load trusted artifacts once and expose only the static web directory."""
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config.update(MAX_CONTENT_LENGTH=512 * 1024, JSON_SORT_KEYS=False)
    torch.set_num_threads(1)
    app.extensions["watch_model"] = load_model(ROOT / "data/processed/baseline_model.pkl") if watch_model is None else watch_model
    app.extensions["facial_models"] = FacialModels.load() if facial_models is None else facial_models
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

    @app.errorhandler(HTTPException)
    def http_error(error: HTTPException) -> Any:
        return jsonify(error=error.description), error.code

    @app.get("/")
    def index() -> Any:
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "models_loaded": ["teammate_watch_baseline", "small_tcn", "logistic_regression"],
                "live_camera_tcn": False, "live_watch_model": False, "watch_alert_transport": False}

    @app.get("/api/models")
    def models() -> dict[str, Any]:
        return {"watch": {"features": FEATURE_COLUMNS, "window_seconds": 60,
                          "live_note": "Bluetooth HR alone does not supply all five watch features."},
                "facial": {"channels": CHANNELS, "sequence_shape": [15, 60],
                           "seconds_order": "oldest_to_newest", "logistic_features": FEATURES,
                           "score_type": "uncalibrated_score", "live_adapter_ready": False,
                           "note": "Use original 68-point geometry extraction; blendshapes are incompatible."}}

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

    for router in (score_router, facial_router, fusion_router):
        app.register_blueprint(router)
    return app


def main() -> None:
    """Run on loopback without the interactive debugger or a second model load."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8777)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    app = create_app()
    print(f"Drowsy packaged app: http://127.0.0.1:{args.port}/", flush=True)
    try:
        app.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False, threaded=True)
    finally:
        bridge = app.extensions["watch_bridge"]
        bridge.submit(bridge.disconnect())
        bridge.loop.call_soon_threadsafe(bridge.loop.stop)


if __name__ == "__main__":
    main()
