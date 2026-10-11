"""Offline fixtures only. Tests never transmit invented readings to a real watch."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from .config import Config
from .main import create_app
from .schema import Batch
from .sensor_processing import RollingRMSSD
from .storage import Store

TOKEN = "offline-test-token-1234"
AUTH = {"Authorization": "Bearer " + TOKEN}


def fixture(batch_id=1, start=0, count=5):
    return {"schema_version": 1, "device": "garmin_forerunner_970", "session": "offline-fixture",
            "batch_id": batch_id, "anchor_epoch_s": 1791690000, "anchor_watch_ms": 1000,
            "created_watch_ms": (start + count) * 1000,
            "heart_rate": [{"t": (start + i + 1) * 1000, "v": 72} for i in range(count)],
            "accelerometer": [{"t": (start + count) * 1000, "rate_hz": 25,
                               "x": [1, None], "y": [2, 2], "z": [1000, 1001], "sensor_ms": [40, 80]}],
            "ibi": [{"t": (start + i + 1) * 1000, "values_ms": [1000 if (start+i) % 2 == 0 else 1100]} for i in range(count)],
            "temperature": [{"t": (start + count) * 1000, "v": 27.4, "source": "watch_onboard_history", "type": "unknown", "epoch_s": 1791690000}],
            "availability": {"heart_rate": "receiving", "accelerometer": "receiving", "ibi": "receiving", "temperature": "receiving"},
            "dropped": {"heart_rate": 0, "accelerometer": 0, "ibi": 0, "temperature": 0, "expired_batches": 0}}


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.config = Config(TOKEN, Path(self.temp.name))
        self.app = create_app(self.config)
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def post(self, payload, headers=AUTH):
        return self.client.post("/garmin/data", json=payload, headers=headers)

    def rows(self, kind):
        with (self.config.data_dir / f"garmin_{kind}.csv").open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def test_health_auth_and_validation(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.post(fixture(), {}).status_code, 401)
        self.assertEqual(self.client.get("/garmin/status").status_code, 401)
        self.assertEqual(self.client.post("/garmin/data", content="{", headers=AUTH).status_code, 422)
        value = fixture(); value["heart_rate"][0]["v"] = 0
        self.assertEqual(self.post(value).status_code, 422)
        value = fixture(); value["accelerometer"][0]["y"] = [2]
        self.assertEqual(self.post(value).status_code, 422)
        value = fixture(); value["heart_rate"][0]["t"] = value["created_watch_ms"]+1
        self.assertEqual(self.post(value).status_code, 422)
        value = fixture(); value["temperature"][0]["source"] = "phone"
        self.assertEqual(self.post(value).status_code, 422)
        value = fixture(); value["created_watch_ms"] = True
        self.assertEqual(self.post(value).status_code, 422)
        self.assertEqual(self.client.post("/garmin/data", content=b"x"*65537, headers=AUTH).status_code, 413)

    def test_csv_original_values_and_timestamps(self):
        value = fixture(); value["heart_rate"][0]["v"] = None
        self.assertEqual(self.post(value).json()["status"], "accepted")
        heart = self.rows("heart_rate")
        self.assertEqual(heart[0]["bpm"], "")
        self.assertEqual(float(heart[0]["sensor_timestamp"]), value["anchor_epoch_s"])
        self.assertGreater(float(heart[0]["received_timestamp"]), 0)
        axes = self.rows("accelerometer")
        self.assertEqual(axes[1]["x"], "")
        self.assertEqual(float(axes[0]["z"]), 1000)
        self.assertEqual(axes[0]["sensor_timestamp_ms"], "40")
        self.assertEqual(float(axes[0]["sample_offset_seconds"]), -.04)
        temperature = self.rows("temperature")[0]
        self.assertEqual(float(temperature["value_c"]), 27.4)
        self.assertEqual(temperature["type"], "unknown")
        self.assertEqual(self.rows("hrv")[0]["rmssd_ms"], "")

    def test_duplicate_conflict_concurrency_and_restart(self):
        value = fixture()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.post(value).json()["status"], range(8)))
        self.assertEqual(results.count("accepted"), 1)
        self.assertEqual(len(self.rows("heart_rate")), 5)
        conflict = deepcopy(value); conflict["heart_rate"][0]["v"] = 80
        self.assertEqual(self.post(conflict).status_code, 409)
        newer = fixture(2, 5); self.assertEqual(self.post(newer).status_code, 200)
        older = fixture(1, 1); self.assertEqual(self.post(older).status_code, 409)
        self.client.__exit__(None, None, None)
        # Simulate a crashed export: journal recovery restores the exact rows.
        with (self.config.data_dir / "garmin_heart_rate.csv").open("a") as f:
            f.write("partial crash row\n")
        self.app = create_app(self.config); self.client = TestClient(self.app); self.client.__enter__()
        self.assertEqual(self.post(value).json()["status"], "duplicate")
        self.assertEqual(len(self.rows("heart_rate")), 10)

    def test_storage_failure_retry_does_not_duplicate(self):
        store = self.app.state.store
        original = store.append
        def partial_then_fail(rows):
            original(rows)
            raise OSError("offline disk failure fixture")
        with patch.object(store, "append", side_effect=partial_then_fail):
            self.assertEqual(self.post(fixture()).status_code, 503)
        self.assertEqual(self.rows("heart_rate"), [])
        self.assertEqual(self.post(fixture()).json()["status"], "accepted")
        self.assertEqual(len(self.rows("heart_rate")), 5)

    def test_rmssd_known_sequence_and_missing_gaps(self):
        for i in range(7):
            self.assertEqual(self.post(fixture(i+1, i*5)).status_code, 200)
        last = self.rows("hrv")[-1]
        self.assertEqual(last["status"], "ready")
        self.assertEqual(float(last["rmssd_ms"]), 100)
        self.assertEqual(int(last["interval_count"]), 35)
        missing = fixture(8, 35); missing["ibi"][0]["values_ms"] = [None]
        self.post(missing)
        self.assertEqual(self.rows("hrv")[-1]["rmssd_ms"], "")
        self.assertEqual(self.rows("ibi")[-5]["rejection_reason"], "missing")
        invalid = fixture(9, 40); invalid["ibi"][0]["values_ms"] = [250, 1000]
        self.post(invalid)
        self.assertEqual(self.rows("ibi")[-6]["interval_ms"], "250.0")
        self.assertEqual(self.rows("ibi")[-6]["valid_for_hrv"], "False")

    def test_disconnect_status(self):
        self.assertEqual(self.client.get("/garmin/status", headers=AUTH).json()["watch"], "waiting")
        self.post(fixture())
        self.assertEqual(self.client.get("/garmin/status", headers=AUTH).json()["watch"], "connected")
        self.app.state.store.last_received -= 20
        self.assertEqual(self.client.get("/garmin/status", headers=AUTH).json()["watch"], "stale")

    def test_second_receiver_cannot_corrupt_exports(self):
        self.post(fixture())
        with self.assertRaises(RuntimeError):
            Store(self.config)
        self.assertEqual(len(self.rows("heart_rate")), 5)


class HRVTests(unittest.TestCase):
    def test_no_cross_gap_pairs(self):
        config = Config(TOKEN, Path("unused"), min_intervals=2, min_window_seconds=1)
        for change in ("callback_gap", "batch_gap", "drop", "empty", "invalid"):
            with self.subTest(change=change):
                calc = RollingRMSSD(config)
                _, good = calc.process(Batch.model_validate(fixture()))
                self.assertIsNotNone(good["rmssd_ms"])
                value = fixture(2, 5, 1)
                if change == "callback_gap": value = fixture(2, 20, 1)
                if change == "batch_gap": value["batch_id"] = 3
                if change == "drop": value["dropped"]["ibi"] = 1
                if change == "empty": value["ibi"][0]["values_ms"] = []
                if change == "invalid": value["ibi"][0]["values_ms"] = [None,1100]
                _, hrv = calc.process(Batch.model_validate(value))
                self.assertIsNone(hrv["rmssd_ms"])

    def test_bpm_only_does_not_create_hrv(self):
        calc = RollingRMSSD(Config(TOKEN, Path("unused")))
        value = fixture(); value["ibi"] = []
        _, hrv = calc.process(Batch.model_validate(value))
        self.assertIsNone(hrv["rmssd_ms"])
        self.assertEqual(hrv["interval_count"], 0)


if __name__ == "__main__":
    unittest.main()
