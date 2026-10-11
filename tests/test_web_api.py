"""Test real artifact inference, its feature contract and local API boundaries."""
import copy
import os
import tempfile
from unittest.mock import patch
import unittest

import numpy as np
import torch

from src.features.facial_sequence import CHANNELS, FEATURES
from src.models.predict import predict_score
from web.app import create_app


class OfflineBridge:
    """No Bluetooth scan or permission request during automated checks."""
    def snapshot(self):
        return {"status": "disconnected", "bpm": None, "samples": []}


class WebAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.logs=tempfile.TemporaryDirectory(prefix="drozy-api-tests-")
        cls.env=patch.dict(os.environ,{"DROZY_LOG_DIRECTORY":cls.logs.name});cls.env.start()
        cls.app = create_app(bridge=OfflineBridge(),llm_enabled=False,relay_enabled=False)
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()
        cls.watch = {"hr_mean": 75.3, "rmssd": .052, "temp_trend": -.0001,
                     "motion_var": 8.2}
        sequence = np.zeros((15, 60))
        sequence[[0, 1, 14]] = 1
        cls.payload = {"model": "small_tcn", "channels": CHANNELS, "sequence": sequence.tolist()}

    @classmethod
    def tearDownClass(cls):
        cls.app.extensions["relay_worker"].close()
        cls.app.extensions["model_service"].close()
        cls.env.stop();cls.logs.cleanup()

    def test_static_dashboard_and_models(self):
        for path in ["/", "/static/style.css", "/static/app.js", "/static/metrics.mjs",
                     "/static/vision-worker.mjs", "/api/health", "/api/models", "/api/state"]:
            with self.client.get(path) as response:
                self.assertEqual(response.status_code, 200, path)
        schema = self.client.get("/api/models").json
        self.assertEqual(schema["facial"]["sequence_shape"], [15, 60])
        self.assertTrue(schema["facial"]["live_adapter_ready"])
        self.assertEqual(self.client.get("/api/state").json["bpm"], None)

    def test_watch_matches_unchanged_teammate_predictor(self):
        result = self.client.post("/api/score", json=self.watch)
        self.assertEqual(result.status_code, 200)
        expected = predict_score(self.watch, model=self.app.extensions["watch_model"])
        self.assertAlmostEqual(result.json["score"], expected)

    def test_sample_explanation_never_changes_live_sessions_or_calls_watch_transport(self):
        service=self.app.extensions['model_service']
        from unittest.mock import Mock
        original=service.explainer
        sessions=dict(service.sessions)
        service.explainer=Mock(return_value={'reason':'Sample camera measurements.','latency_ms':20})
        try:
            response=self.client.post('/api/advisor/sample',json={})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json['advice']['source'],'llm')
            self.assertEqual(response.json['input_source'],'synthetic_demo')
            self.assertFalse(response.json['transport_eligible'])
            self.assertFalse(response.json['watch_alert_sent'])
            self.assertEqual(service.sessions,sessions)
        finally:service.explainer=original

    def test_watch_missing_and_nonfinite_features_are_rejected(self):
        for payload in [{"hr_mean": 72}, {**self.watch, "rmssd": None},
                        {**self.watch, "hr_mean": True}, {**self.watch, "hr_mean": float("inf")}]:
            self.assertEqual(self.client.post("/api/score", json=payload).status_code, 400)

    def test_tcn_matches_original_scaling_and_saved_weights(self):
        response = self.client.post("/api/facial", json=self.payload)
        self.assertEqual(response.status_code, 200)
        bundle = self.app.extensions["facial_models"]
        values = np.asarray(self.payload["sequence"], dtype=np.float32)[None]
        flat = values.transpose(0, 2, 1).reshape(-1, 15)
        scaled = bundle.scaler.transform(flat).reshape(1, 60, 15)
        tensor = torch.from_numpy(np.ascontiguousarray(scaled.transpose(0, 2, 1), dtype=np.float32))
        with torch.inference_mode():
            expected = float(torch.sigmoid(bundle.network(tensor)).item())
        self.assertAlmostEqual(response.json["score"], expected, places=6)
        self.assertEqual(response.json["score_type"], "uncalibrated_score")

    def test_tcn_requires_matching_schema_and_coverage(self):
        for change in ["order", "short", "coverage", "nan", "strings"]:
            body = copy.deepcopy(self.payload)
            if change == "order":
                body["channels"] = list(reversed(CHANNELS))
            elif change == "short":
                body["sequence"] = [[0] * 59] * 15
            elif change == "coverage":
                body["sequence"][14][0] = 0
            elif change == "nan":
                body["sequence"][0][0] = float("nan")
            else:
                body["sequence"][0][0] = "1"
            self.assertEqual(self.client.post("/api/facial", json=body).status_code, 400, change)

    def test_logistic_benchmark_uses_22_features(self):
        features = dict.fromkeys(FEATURES, 0.0)
        features.update(left_eye_mean=1, right_eye_mean=1, valid_frame_fraction=1)
        response = self.client.post("/api/facial", json={"model": "logistic_regression", "features": features})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(0 <= response.json["score"] <= 1)

    def test_fusion_can_compute_both_models_or_handle_unavailable_sources(self):
        body = {"watch_features": self.watch, "facial": self.payload}
        response = self.client.post("/api/fusion", json=body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["mode"], "watch_video")
        self.assertFalse(response.json["watch_alert_sent"])
        self.assertEqual(self.client.post('/api/fusion',json={}).status_code,400)

    def test_cross_site_and_device_actions_are_blocked(self):
        self.assertEqual(self.client.post("/api/score", json=self.watch,
                         headers={"Origin": "https://example.com"}).status_code, 403)
        self.assertEqual(self.client.get("/", headers={"Host": "example.com"}).status_code, 403)
        self.assertEqual(self.client.post("/api/scan", json={}).status_code, 403)
        self.assertEqual(self.client.post("/api/facial", data="{}", content_type="text/plain").status_code, 415)

    def test_private_files_and_large_inputs_are_not_served(self):
        for path in ["/data/processed/baseline_model.pkl", "/.git/config", "/static/../app.py"]:
            self.assertEqual(self.client.get(path).status_code, 404, path)
        response = self.client.post("/api/facial", data=b" " * (512 * 1024 + 1), content_type="application/json")
        self.assertEqual(response.status_code, 413)


if __name__ == "__main__":
    unittest.main()
