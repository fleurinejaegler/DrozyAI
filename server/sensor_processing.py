"""HRV from real intervals only. No average-BPM conversion or imputation."""
from collections import deque
from math import sqrt
from .config import Config
from .schema import Batch


class RollingRMSSD:
    def __init__(self, config: Config):
        self.config = config
        self.beats = deque(maxlen=1000)
        self.last_batch = None
        self.last_callback = None
        self.last_value = None
        self.segment = 0
        self.last_dropped = 0

    def break_segment(self):
        self.segment += 1
        self.last_value = None

    def process(self, batch: Batch):
        if self.last_batch is not None and batch.batch_id != self.last_batch + 1:
            self.break_segment()
        if batch.dropped.ibi != self.last_dropped:
            self.break_segment()
        self.last_dropped = batch.dropped.ibi
        self.last_batch = batch.batch_id
        accepted = []
        for block in batch.ibi:
            t = batch.epoch(block.t)
            if self.last_callback is not None and (t < self.last_callback or t - self.last_callback > self.config.gap_seconds):
                self.break_segment()
            if not block.values_ms:
                self.break_segment()
            for index, value in enumerate(block.values_ms):
                valid = value is not None and 300 <= value <= 2000
                reason = "valid" if valid else ("missing" if value is None else "outside_300_2000_ms")
                if not valid:
                    self.break_segment()
                else:
                    self.beats.append((t, value, self.segment))
                    self.last_value = value
                accepted.append((block, index, valid, reason))
            self.last_callback = t
        now = batch.epoch(batch.created_watch_ms)
        while self.beats and self.beats[0][0] < now - self.config.window_seconds:
            self.beats.popleft()
        # Only the current contiguous segment is eligible, even if old valid values remain.
        current = [b for b in self.beats if b[2] == self.segment]
        pairs = len(current) - 1
        span = current[-1][0] - current[0][0] if current else 0
        fresh = self.last_callback is not None and 0 <= now - self.last_callback <= self.config.gap_seconds
        ready = fresh and len(current) >= self.config.min_intervals and span >= self.config.min_window_seconds
        rmssd = sqrt(sum((b[1] - a[1]) ** 2 for a, b in zip(current, current[1:])) / pairs) if ready else None
        status = "ready" if ready else ("unavailable" if not fresh or not current else "insufficient_data")
        return accepted, {"rmssd_ms": rmssd, "interval_count": len(current), "pair_count": max(0, pairs),
                          "window_seconds": self.config.window_seconds, "span_seconds": span,
                          "timestamp": now, "status": status}
