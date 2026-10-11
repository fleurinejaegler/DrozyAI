from collections import deque
import threading
import time
import unittest
from unittest.mock import patch

from web.routes.watch import decode_heart_rate, HeartRateBridge


class HeartRateTests(unittest.TestCase):
    def test_uint8_and_uint16(self):
        self.assertEqual(decode_heart_rate(bytes([0, 72])), {"bpm": 72, "contact": None})
        self.assertEqual(decode_heart_rate(bytes([1, 180, 0]))["bpm"], 180)

    def test_contact_flags(self):
        self.assertFalse(decode_heart_rate(bytes([4, 72]))["contact"])
        self.assertTrue(decode_heart_rate(bytes([6, 72]))["contact"])

    def test_reject_truncated_and_zero(self):
        for packet in [b"", bytes([0]), bytes([1,72]), bytes([0,0])]:
            with self.assertRaises(ValueError):
                decode_heart_rate(packet)

    def test_stale_and_disconnected_bpm_is_unavailable(self):
        bridge = HeartRateBridge.__new__(HeartRateBridge)
        bridge.lock = threading.Lock()
        bridge.status, bridge.message, bridge.name = "connected", "test", "test device"
        bridge.samples = deque([{"time":100,"bpm":72}])
        with patch('web.routes.watch.time.time',return_value=102):
            self.assertEqual(bridge.snapshot()["bpm"],72)
        with patch('web.routes.watch.time.time',return_value=106):
            self.assertIsNone(bridge.snapshot()["bpm"])
            self.assertEqual(bridge.snapshot()["status"],"stale")
        bridge.status = "disconnected"
        with patch('web.routes.watch.time.time',return_value=102):
            self.assertIsNone(bridge.snapshot()["bpm"])

    def test_poor_contact_immediately_hides_previous_heart_rate(self):
        bridge = HeartRateBridge.__new__(HeartRateBridge)
        bridge.lock = threading.Lock()
        bridge.status, bridge.message, bridge.name = "connected", "poor contact", "test device"
        bridge.contact = False
        bridge.samples = deque([{"time":100,"bpm":72}])
        with patch('web.routes.watch.time.time',return_value=101):
            self.assertIsNone(bridge.snapshot()["bpm"])


if __name__ == "__main__":
    unittest.main()
