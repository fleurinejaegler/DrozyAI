"""Optional transport-level summaries inspired by loader.py, NOT model preprocessing.

No helper is automatically connected to an ML adapter. Its training contract must
first establish units, windows, coverage and missing-data behavior.
"""
import math


def _mean(values):
    return math.fsum(values) / len(values) if values else None


def aggregate_watch_seconds(window):
    """Use explicit timestamps for 1-Hz mean/population variance, with null gaps.

    Unlike the offline loader's fixed 1/4/32-Hz reshape, live sample rates remain
    separate. No clipping late/out-of-range events into the first or last bin.
    """
    groups = {}
    for timestamp, observation in zip(window.aligned_timestamps_ms, window.observations):
        second = timestamp // 1000
        groups.setdefault(second, []).append(observation.payload)
    rows = []
    for second in range(window.start_ms // 1000, math.ceil(window.end_ms / 1000)):
        samples = groups.get(second, [])
        row = {'timestamp_ms': second * 1000}
        for sensor, key, name in [('heart_rate', 'bpm', 'heart_rate'),
                                  ('temperature', 'celsius', 'temp'),
                                  ('ibi', 'seconds', 'ibi_mean')]:
            values = [s.values[key] for s in samples if s.sensor == sensor]
            valid = [v for v in values if v is not None]
            row[name] = _mean(valid) if sensor == 'ibi' or len(valid) == len(values) else None
            row[f'{sensor}_observed_count'] = len(values)
            row[f'{sensor}_valid_count'] = len(valid)
        for axis in 'xyz':
            values = [s.values[axis] for s in samples if s.sensor == 'acceleration']
            valid = [v for v in values if v is not None]
            mean = _mean(valid) if len(valid) == len(values) else None
            row[f'accel_mean_{axis}'] = mean
            row[f'accel_var_{axis}'] = _mean([(v - mean) ** 2 for v in valid]) if mean is not None else None
        rows.append(row)
    return rows


def rmssd_from_raw_ibi(window, max_gap_ms):
    """Seconds, from consecutive raw IBI events; invalid events/gaps break pairs.

    The caller must specify the permitted gap from the training contract.
    This never uses average BPM or per-second IBI averages.
    """
    if max_gap_ms <= 0:
        raise ValueError('A positive gap limit is required')
    differences, previous = [], None
    for timestamp, observation in zip(window.aligned_timestamps_ms, window.observations):
        sample = observation.payload
        if sample.sensor != 'ibi':
            continue
        value = sample.values['seconds']
        if value is None or value <= 0:
            previous = None
            continue
        if previous is not None and 0 < timestamp - previous[0] <= max_gap_ms:
            differences.append((value - previous[1]) ** 2)
        previous = timestamp, value
    mean = _mean(differences)
    return math.sqrt(mean) if mean is not None else None
