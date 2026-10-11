"""Loopback-only dashboard and optional Bluetooth heart-rate bridge."""
import asyncio
from collections import deque
import threading
import time

HR_SERVICE = "0000180d-0000-1000-8000-00805f9b34fb"
HR_MEASUREMENT = "00002a37-0000-1000-8000-00805f9b34fb"


def decode_heart_rate(data):
    """Bluetooth SIG Heart Rate Measurement: flag bit 0 selects 8/16-bit BPM."""
    if len(data) < 2:
        raise ValueError("Incomplete heart-rate packet")
    width = 2 if data[0] & 1 else 1
    if len(data) < 1 + width:
        raise ValueError("Incomplete heart-rate value")
    bpm = int.from_bytes(data[1:1 + width], "little")
    if not 0 < bpm <= 250:
        raise ValueError("Heart-rate reading outside prototype input range")
    # Sensor contact support is flag bit 2; bit 1 reports actual contact.
    contact = bool(data[0] & 2) if data[0] & 4 else None
    return {"bpm": bpm, "contact": contact}


class HeartRateBridge:
    def __init__(self):
        self.lock = threading.Lock()
        self.status = "disconnected"
        self.message = "Turn on Broadcast Heart Rate on your watch, then scan."
        self.name = None
        self.contact = None
        self.samples = deque(maxlen=600)
        self.devices = {}
        self.task = None
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def update(self, status, message):
        with self.lock:
            self.status, self.message = status, message

    def snapshot(self):
        now = time.time()
        with self.lock:
            samples = [s for s in self.samples if now - s["time"] <= 300]
            last = samples[-1] if samples else None
            age = now - last["time"] if last else None
            contact_ok = getattr(self, "contact", None) is not False
            fresh = self.status == "connected" and age is not None and age < 5 and contact_ok
            status = "stale" if self.status == "connected" and not fresh else self.status
            return {"status": status, "message": self.message, "name": self.name,
                    "bpm": last["bpm"] if fresh else None, "sampleAge": age,
                    "samples": samples, "timestampSource": "Mac receipt time"}

    async def scan(self):
        try:
            from bleak import BleakScanner
        except ImportError:
            self.update("unavailable", "Bluetooth reader needs setup. See README → Watch setup.")
            return {"devices": [], "error": self.message}
        if self.task and not self.task.done():
            return {"devices": [], "error": "Disconnect the current watch before scanning."}
        self.update("scanning", "Looking for heart-rate broadcasters…")
        try:
            discovered = await BleakScanner.discover(timeout=8, service_uuids=[HR_SERVICE])
            self.devices = {d.address: d for d in discovered}
            self.update("disconnected", "Choose your watch." if discovered else "No watch found. Enable Broadcast Heart Rate and try again.")
            return {"devices": [{"id": d.address, "name": d.name or "Heart-rate device"} for d in discovered]}
        except Exception as error:
            self.update("unavailable", f"Bluetooth unavailable: {error}. Check macOS Bluetooth permissions.")
            return {"devices": [], "error": self.message}

    async def connect(self, identity):
        if identity not in self.devices:
            raise ValueError("Choose a device from a fresh scan")
        await self.disconnect()
        with self.lock:
            self.samples.clear()
            self.contact = None
            self.name = self.devices[identity].name or "Heart-rate device"
        self.update("connecting", "Connecting to your watch…")
        self.task = asyncio.create_task(self.listen(self.devices[identity]))
        return {"ok": True}

    async def listen(self, device):
        from bleak import BleakClient
        def receive(_, data):
            try:
                reading = decode_heart_rate(data)
            except ValueError:
                return
            if reading["contact"] is False:
                with self.lock:
                    self.contact = False
                self.update("connected", "Watch reports poor skin contact. Adjust its fit.")
                return
            with self.lock:
                self.contact = reading["contact"]
                self.samples.append({"time": time.time(), "bpm": reading["bpm"]})
            self.update("connected", "Receiving live heart rate. Timestamped on this Mac.")
        try:
            async with BleakClient(device, timeout=20) as client:
                await client.start_notify(HR_MEASUREMENT, receive)
                self.update("connected", "Connected; waiting for the first heart-rate reading…")
                while client.is_connected:
                    await asyncio.sleep(0.5)
            self.update("disconnected", "Watch disconnected. Scan to reconnect.")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.update("unavailable", f"Could not read heart rate: {error}")

    async def disconnect(self):
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.task = None
        self.update("disconnected", "Watch disconnected. Scan to connect.")
        return {"ok": True}

    def submit(self, coroutine, timeout=30):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(timeout)
