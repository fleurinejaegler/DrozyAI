"""Serialized CSV logging with a durable SQLite batch journal and restart recovery."""
from collections import OrderedDict
from copy import deepcopy
import csv
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
from threading import RLock
import time

from .config import Config
from .schema import Batch
from .sensor_processing import RollingRMSSD
from .process_lock import ProcessLock

log = logging.getLogger("garmin")
COMMON = ["device", "session", "batch_id", "sensor_timestamp", "received_timestamp", "watch_callback_ms"]
HEADERS = {
    "heart_rate": COMMON + ["bpm", "status", "timestamp_basis"],
    "accelerometer": COMMON + ["sensor_timestamp_ms", "sample_index", "sample_offset_seconds", "x", "y", "z", "unit", "sample_rate_hz", "timestamp_basis"],
    "ibi": COMMON + ["interval_index", "interval_ms", "valid_for_hrv", "rejection_reason", "timestamp_basis"],
    "temperature": COMMON + ["value_c", "source", "type", "status", "timestamp_basis"],
    "hrv": COMMON + ["rmssd_ms", "interval_count", "pair_count", "window_seconds", "span_seconds", "status"],
    "batches": ["device", "session", "batch_id", "received_timestamp", "created_timestamp", "availability", "dropped"],
}


class BatchConflict(ValueError):
    pass


class Store:
    def __init__(self, config: Config):
        self.config = config
        self.lock = RLock()
        config.data_dir.mkdir(parents=True, exist_ok=True)
        self.process_lock = ProcessLock(config.data_dir / ".receiver.lock")
        self.db = sqlite3.connect(config.data_dir / "garmin_batches.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS batches (session TEXT, batch_id INTEGER, digest TEXT, received REAL, payload TEXT, PRIMARY KEY (session,batch_id))")
        self.db.commit()
        self.calculators = OrderedDict()
        self.last_received = None
        self.last_hrv = None
        # CSVs are exports of the journal: replay fixes partial writes after process/power loss.
        for name, header in HEADERS.items():
            with self.path(name).open("w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(header)
        for payload, received in self.db.execute("SELECT payload,received FROM batches ORDER BY rowid"):
            batch = Batch.model_validate_json(payload)
            rows, hrv = self.rows(batch, received)
            self.append(rows)
            self.last_received, self.last_hrv = received, hrv

    def path(self, name: str) -> Path:
        return self.config.data_dir / f"garmin_{name}.csv"

    def calculator(self, session):
        if session not in self.calculators:
            self.calculators[session] = RollingRMSSD(self.config)
        self.calculators.move_to_end(session)
        while len(self.calculators) > 16:
            self.calculators.popitem(last=False)
        return self.calculators[session]

    def rows(self, batch, received):
        result = {name: [] for name in HEADERS}
        def common(t, epoch=None):
            return [batch.device, batch.session, batch.batch_id, batch.epoch(t) if epoch is None else epoch, received, t]
        for s in batch.heart_rate:
            result["heart_rate"].append(common(s.t) + [s.v, "missing" if s.v is None else "received", "callback_clock_anchor"])
        for block in batch.accelerometer:
            for i, (x, y, z, sensor_ms) in enumerate(zip(block.x, block.y, block.z, block.sensor_ms)):
                # Do not silently equate sensor timestamp origin to System.getTimer().
                # Keep original ms and separate rate-based offsets; epoch stays callback time.
                offset = (i - len(block.x) + 1) / block.rate_hz
                result["accelerometer"].append(common(block.t) + [sensor_ms, i, offset, x, y, z, "mg", block.rate_hz, "callback_clock_anchor"])
        intervals, hrv = self.calculator(batch.session).process(batch)
        for block, i, valid, reason in intervals:
            result["ibi"].append(common(block.t) + [i, block.values_ms[i], valid, reason, "callback_clock_anchor_no_individual_beat_time"])
        for s in batch.temperature:
            result["temperature"].append(common(s.t, s.epoch_s) + [s.v, s.source, s.type, "missing" if s.v is None else "received", "sensor_history_epoch" if s.epoch_s is not None else "callback_clock_anchor"])
        result["hrv"].append(common(batch.created_watch_ms) + [hrv[k] for k in ("rmssd_ms", "interval_count", "pair_count", "window_seconds", "span_seconds", "status")])
        result["batches"].append([batch.device, batch.session, batch.batch_id, received, batch.epoch(batch.created_watch_ms), json.dumps(batch.availability.model_dump()), json.dumps(batch.dropped.model_dump())])
        return result, hrv

    def append(self, rows):
        for name, records in rows.items():
            with self.path(name).open("a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerows(records)

    def ingest(self, batch: Batch, received=None):
        received = time.time() if received is None else received
        payload = batch.model_dump_json()
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with self.lock:
            old = self.db.execute("SELECT digest FROM batches WHERE session=? AND batch_id=?", (batch.session, batch.batch_id)).fetchone()
            if old:
                if old[0] != digest:
                    raise BatchConflict("Batch ID was already used with different measurements")
                return {"status": "duplicate", "session": batch.session, "batch_id": batch.batch_id}
            latest = self.db.execute("SELECT batch_id,payload FROM batches WHERE session=? ORDER BY batch_id DESC LIMIT 1", (batch.session,)).fetchone()
            if latest:
                previous = Batch.model_validate_json(latest[1])
                if batch.batch_id <= latest[0] or batch.created_watch_ms < previous.created_watch_ms:
                    raise BatchConflict("Out-of-order batch; start a new session after a watch restart")
                if (batch.anchor_epoch_s, batch.anchor_watch_ms) != (previous.anchor_epoch_s, previous.anchor_watch_ms):
                    raise BatchConflict("Clock anchor changed within session")
            before = deepcopy(self.calculators)
            offsets = {name: self.path(name).stat().st_size for name in HEADERS}
            try:
                rows, hrv = self.rows(batch, received)
                self.db.execute("INSERT INTO batches VALUES (?,?,?,?,?)", (batch.session, batch.batch_id, digest, received, payload))
                self.append(rows)
                self.db.commit()
            except Exception:
                self.db.rollback()
                self.calculators = before
                for name, offset in offsets.items():
                    with self.path(name).open("r+b") as f:
                        f.truncate(offset)
                raise
            self.last_received, self.last_hrv = received, hrv
            hr = next((s.v for s in reversed(batch.heart_rate) if s.v is not None), None)
            temp = next((s.v for s in reversed(batch.temperature) if s.v is not None), None)
            log.info("Garmin 970 | batch %s | HR: %s BPM | ACC: %s samples | IBI: %s intervals | Temp: %s C | RMSSD: %s ms (%s)",
                     batch.batch_id, hr if hr is not None else "missing", len(rows["accelerometer"]), len(rows["ibi"]),
                     temp if temp is not None else "missing", hrv["rmssd_ms"] if hrv["rmssd_ms"] is not None else "unavailable", hrv["status"])
            unavailable = [k + ":" + v for k, v in batch.availability.model_dump().items() if v != "receiving"]
            if unavailable:
                log.info("Sensor availability | %s", ", ".join(unavailable))
            if any(batch.dropped.model_dump().values()):
                log.warning("Watch cumulative dropped counts | %s", batch.dropped.model_dump())
            return {"status": "accepted", "session": batch.session, "batch_id": batch.batch_id}

    def status(self):
        with self.lock:
            age = None if self.last_received is None else max(0, time.time() - self.last_received)
            return {"status": "ok", "watch": "connected" if age is not None and age <= 15 else "waiting" if age is None else "stale",
                    "last_upload_epoch_s": self.last_received, "last_upload_age_seconds": age}

    def close(self):
        self.db.close()
        self.process_lock.close()
