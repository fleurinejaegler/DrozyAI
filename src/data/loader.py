"""Load and align raw UL-DD session files into a per-second table.

For each subject/session, reads HR, TEMP, EDA, ACC, IBI and Labels,
and produces one row per second with:

    second, heart_rate, temp, eda,
    accel_mean_x, accel_mean_y, accel_mean_z,
    accel_var_x, accel_var_y, accel_var_z,
    ibi_mean, ibi_count, kss, drowsy

Raw file structure (UL-DD Zenodo release):
    {USER}_{SIGNAL}_{SESSION}.csv

Signals:
    HR     1 Hz, single column
    TEMP   4 Hz, single column
    EDA    4 Hz, single column
    ACC    32 Hz, three columns (x, y, z)
    IBI    irregular, two columns (timestamp, ibi)
    Labels one row, ten comma-separated KSS values (one per 4 min)

Label rule:
    drowsy = 1 if kss >= 7.0 else 0
    Each KSS covers 240 seconds (4 minutes).

Note:
    Some sessions have an empty IBI file (e.g. J/A). The loader
    handles this gracefully by filling NaN for that session.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------
SESSION_SECONDS = 2400          # 40 minutes
KSS_INTERVAL_SECONDS = 240      # 4 minutes per KSS value
DROWSY_THRESHOLD = 7.0


# ----------------------------------------------------------------------
# Low-level file readers
# ----------------------------------------------------------------------
def _read_single_column(path: Path, name: str) -> np.ndarray:
    """Read a headerless single-column CSV."""
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path, header=None, names=[name])[name].to_numpy(dtype=float)


def _read_acc(path: Path) -> np.ndarray:
    """Read a headerless 3-column accelerometer CSV. Returns (N, 3)."""
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(
        path, header=None, names=["x", "y", "z"]
    ).to_numpy(dtype=float)


def _read_ibi(path: Path) -> pd.DataFrame:
    """Read a headerless 2-column IBI CSV. Returns DataFrame(t, ibi).

    Handles the case where the file is empty (0 bytes).
    """
    if not path.exists():
        raise FileNotFoundError(path)
    if path.stat().st_size == 0:
        # Empty file: return an empty DataFrame with the right columns
        return pd.DataFrame(columns=["t", "ibi"])
    return pd.read_csv(path, header=None, names=["t", "ibi"])


def _read_labels(path: Path) -> np.ndarray:
    """Read the single-row Labels CSV. Returns the 10 KSS values."""
    if not path.exists():
        raise FileNotFoundError(path)
    text = path.read_text().strip()
    if not text:
        # Empty labels: treat as all zeros (should not happen)
        return np.zeros(10, dtype=float)
    return np.array([float(v) for v in text.split(",")], dtype=float)


# ----------------------------------------------------------------------
# Aggregation helpers
# ----------------------------------------------------------------------
def _resample_mean(values: np.ndarray, source_hz: int, duration_s: int) -> np.ndarray:
    """Resample a uniformly-sampled signal to 1 Hz using per-second means."""
    expected = duration_s * source_hz
    n = min(len(values), expected)
    trimmed = values[:n]
    if n < expected:
        pad = np.full(expected - n, np.nan)
        trimmed = np.concatenate([trimmed, pad])
    return trimmed.reshape(duration_s, source_hz).mean(axis=1)


def _resample_acc(acc: np.ndarray, source_hz: int, duration_s: int) -> dict[str, np.ndarray]:
    """Aggregate 3-axis accelerometer to 1 Hz using mean and variance."""
    expected = duration_s * source_hz
    n = min(len(acc), expected)
    trimmed = acc[:n]
    if n < expected:
        pad = np.full((expected - n, 3), np.nan)
        trimmed = np.concatenate([trimmed, pad])
    reshaped = trimmed.reshape(duration_s, source_hz, 3)
    return {
        "accel_mean_x": reshaped[:, :, 0].mean(axis=1),
        "accel_mean_y": reshaped[:, :, 1].mean(axis=1),
        "accel_mean_z": reshaped[:, :, 2].mean(axis=1),
        "accel_var_x": reshaped[:, :, 0].var(axis=1),
        "accel_var_y": reshaped[:, :, 1].var(axis=1),
        "accel_var_z": reshaped[:, :, 2].var(axis=1),
    }


def _resample_ibi(ibi_df: pd.DataFrame, duration_s: int) -> tuple[np.ndarray, np.ndarray]:
    """Aggregate irregular IBI samples into per-second mean and count."""
    ibi_mean = np.full(duration_s, np.nan)
    ibi_count = np.zeros(duration_s, dtype=int)

    if len(ibi_df) == 0:
        return ibi_mean, ibi_count

    seconds = np.floor(ibi_df["t"].to_numpy()).astype(int)
    seconds = np.clip(seconds, 0, duration_s - 1)
    values = ibi_df["ibi"].to_numpy()

    df = pd.DataFrame({"s": seconds, "ibi": values})
    mean_per_second = df.groupby("s")["ibi"].mean()
    ibi_mean[mean_per_second.index] = mean_per_second.to_numpy()

    count_per_second = df.groupby("s").size()
    ibi_count[count_per_second.index] = count_per_second.to_numpy()

    return ibi_mean, ibi_count


def _expand_kss(kss_values: np.ndarray, duration_s: int) -> tuple[np.ndarray, np.ndarray]:
    """Expand the 10 KSS values into per-second kss and drowsy arrays."""
    kss = np.full(duration_s, np.nan)
    drowsy = np.zeros(duration_s, dtype=int)
    for i, v in enumerate(kss_values):
        start = i * KSS_INTERVAL_SECONDS
        end = min(start + KSS_INTERVAL_SECONDS, duration_s)
        if start >= duration_s:
            break
        kss[start:end] = v
        drowsy[start:end] = 1 if v >= DROWSY_THRESHOLD else 0
    return kss, drowsy


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------
def load_session(user: str, session: str, data_root: Path) -> pd.DataFrame:
    """Load one subject/session and return the aligned per-second table.

    Parameters
    ----------
    user : str
        Subject ID, e.g. "A".
    session : str
        Session ID, "A" (awake) or "D" (drowsy).
    data_root : Path
        Root folder containing the per-subject folders.

    Returns
    -------
    pd.DataFrame
        One row per second.
    """
    session_dir = data_root / user / session
    prefix = f"{user}_"

    hr = _read_single_column(session_dir / f"{prefix}HR_{session}.csv", "heart_rate")
    temp = _read_single_column(session_dir / f"{prefix}TEMP_{session}.csv", "temp")
    eda = _read_single_column(session_dir / f"{prefix}EDA_{session}.csv", "eda")
    acc = _read_acc(session_dir / f"{prefix}ACC_{session}.csv")
    ibi_df = _read_ibi(session_dir / f"{prefix}IBI_{session}.csv")
    kss_values = _read_labels(session_dir / f"{prefix}Labels_{session}.csv")

    duration = SESSION_SECONDS

    df = pd.DataFrame({"second": np.arange(duration)})
    df["heart_rate"] = _resample_mean(hr, source_hz=1, duration_s=duration)
    df["temp"] = _resample_mean(temp, source_hz=4, duration_s=duration)
    df["eda"] = _resample_mean(eda, source_hz=4, duration_s=duration)

    acc_agg = _resample_acc(acc, source_hz=32, duration_s=duration)
    for k, v in acc_agg.items():
        df[k] = v

    ibi_mean, ibi_count = _resample_ibi(ibi_df, duration_s=duration)
    df["ibi_mean"] = ibi_mean
    df["ibi_count"] = ibi_count

    kss, drowsy = _expand_kss(kss_values, duration_s=duration)
    df["kss"] = kss
    df["drowsy"] = drowsy

    df["subject"] = user
    df["session"] = session

    cols = [
        "subject", "session", "second",
        "heart_rate", "temp", "eda",
        "accel_mean_x", "accel_mean_y", "accel_mean_z",
        "accel_var_x", "accel_var_y", "accel_var_z",
        "ibi_mean", "ibi_count",
        "kss", "drowsy",
    ]
    return df[cols]


def list_sessions(data_root: Path) -> list[tuple[str, str]]:
    """Return every (user, session) pair found under data_root."""
    pairs = []
    for user_dir in sorted(data_root.iterdir()):
        if not user_dir.is_dir() or len(user_dir.name) != 1:
            continue
        for session_dir in sorted(user_dir.iterdir()):
            if not session_dir.is_dir() or len(session_dir.name) != 1:
                continue
            pairs.append((user_dir.name, session_dir.name))
    return pairs