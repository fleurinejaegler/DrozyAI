"""Bounded, rotating CSV logging on its own thread, independent of ingestion."""
import csv
import logging
from pathlib import Path
from queue import Full, Queue
from threading import Thread

FIELDS = ['timestamp_ms', 'device_id', 'session_id', 'data_origin', 'watch_prediction',
          'watch_score', 'watch_score_kind', 'watch_window_start_ms', 'watch_window_end_ms',
          'watch_prediction_timestamp_ms', 'video_prediction', 'video_score', 'video_score_kind',
          'video_window_start_ms', 'video_window_end_ms', 'video_prediction_timestamp_ms',
          'raw_final_prediction', 'final_prediction', 'final_score', 'inference_mode',
          'prediction_latency_ms', 'watch_data_age_ms', 'video_data_age_ms',
          'watch_model_version', 'video_model_version', 'video_enabled', 'reason']


class PredictionJournal:
    def __init__(self, directory, capacity=2048, max_file_bytes=5_000_000):
        self.directory = Path(directory)
        self.queue = Queue(maxsize=capacity)
        self.max_file_bytes = max_file_bytes
        self.dropped = 0
        self.error = None
        self.thread = None

    def start(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.thread = Thread(target=self._run, name='prediction-log', daemon=True)
        self.thread.start()

    def enqueue(self, row):
        try:
            self.queue.put_nowait(row)
        except Full:
            self.dropped += 1

    def _append(self, row):
        path = self.directory / 'predictions.csv'
        if path.exists() and path.stat().st_size >= self.max_file_bytes:
            for index in range(4, 0, -1):
                source = self.directory / f'predictions.{index}.csv'
                if source.exists():
                    source.replace(self.directory / f'predictions.{index+1}.csv')
            path.replace(self.directory / 'predictions.1.csv')
        new = not path.exists() or not path.stat().st_size
        with path.open('a', newline='') as handle:
            writer = csv.DictWriter(handle, FIELDS)
            if new:
                writer.writeheader()
            writer.writerow(row)

    def _run(self):
        while True:
            row = self.queue.get()
            try:
                if row is None:
                    return
                self._append(row)
                self.error = None
            except Exception as exc:
                self.error = type(exc).__name__
                self.dropped += 1
                logging.getLogger(__name__).error('Prediction logging failed: %s', self.error)
            finally:
                self.queue.task_done()

    def close(self):
        if self.thread is not None:
            try:
                self.queue.put(None, timeout=2)
            except Full:
                self.error = 'ShutdownQueueFull'
                return
            self.thread.join(timeout=3)

    def status(self):
        return {'queued': self.queue.qsize(), 'dropped': self.dropped, 'error': self.error}
