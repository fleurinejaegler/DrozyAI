"""Facial feature extraction for the DrozyAI vision model.

Reads the pre-extracted facial landmarks (68 points, Dlib format) from
the UL-DD dataset and produces one row per 60-second window with:

    - Eye openness  : left_ear_mean, right_ear_mean
    - Eye closure   : perclos, longest_closure_sec
    - Blink timing  : blink_rate_per_min, blink_duration_mean,
                      inter_blink_interval_mean
    - Mouth opening : mar_mean, yawn_count, max_yawn_duration
    - Tracking      : tracking_coverage

The window layout matches src.features.watch_features (60-second
window, 5-second step) so that the two feature tables can be joined
on (subject, session, window_start).

Input:
    data/raw/Extracted_Features/Extracted_Features/{user}/{session}/
        {user}_FL_{session}.csv   137 columns: Frame, X1, Y1, ..., X68, Y68

Output:
    data/processed/video_features.parquet

Usage:
    python -m src.features.video_features
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
WINDOW_SECONDS = 60
STEP_SECONDS = 5
VIDEO_FPS = 60

# Dlib 68-point landmark indices (1-based, matching CSV column names).
# Right eye = points 37-42; Left eye = points 43-48.
RIGHT_EYE = [37, 38, 39, 40, 41, 42]
LEFT_EYE = [43, 44, 45, 46, 47, 48]

# Mouth: outer corners 49 and 55; top and bottom of inner lip 63 and 67.
MOUTH_LEFT = 49
MOUTH_RIGHT = 55
MOUTH_TOP = 63
MOUTH_BOTTOM = 67

# Threshold on EAR to declare the eye closed.
EAR_CLOSED_THRESHOLD = 0.21
# Threshold on MAR to declare a yawn.
MAR_YAWN_THRESHOLD = 0.60

# A blink is a closed interval between these two durations (in seconds).
MIN_BLINK_SEC = 0.05
MAX_BLINK_SEC = 0.50

# A yawn must last at least this long (seconds).
MIN_YAWN_SEC = 1.5

FEATURE_COLUMNS = [
    "left_ear_mean",
    "right_ear_mean",
    "perclos",
    "longest_closure_sec",
    "blink_rate_per_min",
    "blink_duration_mean",
    "inter_blink_interval_mean",
    "mar_mean",
    "yawn_count",
    "max_yawn_duration",
    "tracking_coverage",
]


# ----------------------------------------------------------------------
# Landmark loading
# ----------------------------------------------------------------------
def _load_fl(path: Path) -> pd.DataFrame:
    """Read an FL CSV. Returns DataFrame with columns Frame_Number, X1..Y68."""
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path)


def _point(df: pd.DataFrame, idx: int) -> np.ndarray:
    """Return the (N, 2) array for landmark index idx (1-based)."""
    return df[[f"X{idx}", f"Y{idx}"]].to_numpy(dtype=float)


def _ear(eye_points: list[int], df: pd.DataFrame) -> np.ndarray:
    """Eye Aspect Ratio for one eye. Returns an array of shape (N,).

    EAR = (|p2 - p6| + |p3 - p5|) / (2 * |p1 - p4|)

    With Dlib indexing for a 6-point eye:
        p1 = corner 1, p2 = top 1, p3 = top 2,
        p4 = corner 2, p5 = bottom 2, p6 = bottom 1
    """
    p1 = _point(df, eye_points[0])
    p2 = _point(df, eye_points[1])
    p3 = _point(df, eye_points[2])
    p4 = _point(df, eye_points[3])
    p5 = _point(df, eye_points[4])
    p6 = _point(df, eye_points[5])

    v1 = np.linalg.norm(p2 - p6, axis=1)
    v2 = np.linalg.norm(p3 - p5, axis=1)
    h = 2.0 * np.linalg.norm(p1 - p4, axis=1)
    ear = np.where(h > 1e-6, (v1 + v2) / h, np.nan)
    return ear


def _mar(df: pd.DataFrame) -> np.ndarray:
    """Mouth Aspect Ratio. Returns an array of shape (N,)."""
    left = _point(df, MOUTH_LEFT)
    right = _point(df, MOUTH_RIGHT)
    top = _point(df, MOUTH_TOP)
    bottom = _point(df, MOUTH_BOTTOM)
    horizontal = np.linalg.norm(left - right, axis=1)
    vertical = np.linalg.norm(top - bottom, axis=1)
    mar = np.where(horizontal > 1e-6, vertical / horizontal, np.nan)
    return mar


# ----------------------------------------------------------------------
# Event detection
# ----------------------------------------------------------------------
def _count_blinks(closed_mask: np.ndarray) -> tuple[int, float, float]:
    """Detect blinks from a boolean 'eyes closed' mask.

    A blink is a run of closed frames lasting between MIN_BLINK_SEC and
    MAX_BLINK_SEC.

    Returns (n_blinks, mean_duration_sec, mean_inter_blink_sec).
    """
    # Find start and end of each closed run
    runs = []
    n = len(closed_mask)
    i = 0
    while i < n:
        if closed_mask[i]:
            start = i
            while i < n and closed_mask[i]:
                i += 1
            end = i
            duration_sec = (end - start) / VIDEO_FPS
            if MIN_BLINK_SEC <= duration_sec <= MAX_BLINK_SEC:
                runs.append((start, end, duration_sec))
        else:
            i += 1

    if not runs:
        return 0, float("nan"), float("nan")

    durations = [r[2] for r in runs]
    starts = [r[0] for r in runs]
    intervals = [
        (starts[k + 1] - starts[k]) / VIDEO_FPS for k in range(len(starts) - 1)
    ]
    return (
        len(runs),
        float(np.mean(durations)),
        float(np.mean(intervals)) if intervals else float("nan"),
    )


def _longest_closure(closed_mask: np.ndarray) -> float:
    """Longest run of consecutive closed frames, in seconds."""
    longest = 0
    current = 0
    for v in closed_mask:
        if v:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest / VIDEO_FPS


def _count_yawns(yawn_mask: np.ndarray) -> tuple[int, float]:
    """Detect yawns from a boolean 'mouth open' mask.

    A yawn is a run of open frames lasting at least MIN_YAWN_SEC.

    Returns (n_yawns, max_duration_sec).
    """
    runs = []
    n = len(yawn_mask)
    i = 0
    while i < n:
        if yawn_mask[i]:
            start = i
            while i < n and yawn_mask[i]:
                i += 1
            end = i
            duration_sec = (end - start) / VIDEO_FPS
            if duration_sec >= MIN_YAWN_SEC:
                runs.append(duration_sec)
        else:
            i += 1
    if not runs:
        return 0, float("nan")
    return len(runs), float(max(runs))


# ----------------------------------------------------------------------
# Per-window feature computation
# ----------------------------------------------------------------------
def _window_features(
    left_ear: np.ndarray,
    right_ear: np.ndarray,
    mar: np.ndarray,
    frame_valid: np.ndarray,
) -> dict[str, float]:
    """Compute the 11 facial features over one 60-second window."""

    # Tracking coverage
    coverage = float(np.mean(frame_valid)) if len(frame_valid) else float("nan")

    # Eyes
    ear_mean = np.nanmean(
        np.vstack([left_ear, right_ear]), axis=0
    )  # average of both eyes per frame
    closed_mask = (ear_mean < EAR_CLOSED_THRESHOLD) & frame_valid
    perclos = float(np.mean(closed_mask)) if len(closed_mask) else float("nan")
    longest_closure = _longest_closure(closed_mask)

    # Blinks
    n_blinks, blink_dur, inter_blink = _count_blinks(closed_mask)
    window_minutes = len(closed_mask) / (VIDEO_FPS * 60.0)
    blink_rate = n_blinks / window_minutes if window_minutes > 0 else float("nan")

    # Mouth
    yawn_mask = (mar > MAR_YAWN_THRESHOLD) & frame_valid
    n_yawns, max_yawn = _count_yawns(yawn_mask)

    return {
        "left_ear_mean": float(np.nanmean(left_ear)),
        "right_ear_mean": float(np.nanmean(right_ear)),
        "perclos": perclos,
        "longest_closure_sec": longest_closure,
        "blink_rate_per_min": blink_rate,
        "blink_duration_mean": blink_dur,
        "inter_blink_interval_mean": inter_blink,
        "mar_mean": float(np.nanmean(mar)),
        "yawn_count": float(n_yawns),
        "max_yawn_duration": max_yawn,
        "tracking_coverage": coverage,
    }


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------
def build_features_for_session(
    user: str, session: str, root: Path
) -> pd.DataFrame:
    """Build the facial feature table for one (user, session)."""
    fl_path = root / user / session / f"{user}_FL_{session}.csv"
    df = _load_fl(fl_path)

    # Valid frames: no NaN in the required landmarks
    required_cols = []
    for idx in RIGHT_EYE + LEFT_EYE + [MOUTH_LEFT, MOUTH_RIGHT, MOUTH_TOP, MOUTH_BOTTOM]:
        required_cols.extend([f"X{idx}", f"Y{idx}"])
    frame_valid = ~df[required_cols].isna().any(axis=1).to_numpy()

    left_ear = _ear(LEFT_EYE, df)
    right_ear = _ear(RIGHT_EYE, df)
    mar = _mar(df)

    # Window loop: 60 s with 5 s step at 60 fps
    window_frames = WINDOW_SECONDS * VIDEO_FPS
    step_frames = STEP_SECONDS * VIDEO_FPS
    n = len(df)
    records = []
    for start in range(0, n - window_frames + 1, step_frames):
        end = start + window_frames
        feats = _window_features(
            left_ear[start:end],
            right_ear[start:end],
            mar[start:end],
            frame_valid[start:end],
        )
        records.append(
            {
                "subject": user,
                "session": session,
                "window_start": start // VIDEO_FPS,
                "window_end": end // VIDEO_FPS,
                **feats,
            }
        )
    return pd.DataFrame(records)


def build_feature_table(root: Path) -> pd.DataFrame:
    """Build the facial feature table for all (user, session) pairs."""
    frames = []
    for user_dir in sorted(root.iterdir()):
        if not user_dir.is_dir() or len(user_dir.name) != 1:
            continue
        for session_dir in sorted(user_dir.iterdir()):
            if not session_dir.is_dir() or len(session_dir.name) != 1:
                continue
            user = user_dir.name
            session = session_dir.name
            try:
                df = build_features_for_session(user, session, root)
                frames.append(df)
                print(f"  {user}/{session}: {len(df)} windows")
            except FileNotFoundError as exc:
                print(f"  {user}/{session}: SKIP ({exc})")
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


# ----------------------------------------------------------------------
# CLI entry point
# ----------------------------------------------------------------------
def main() -> None:
    in_root = Path("data/raw/Extracted_Features/Extracted_Features")
    out_path = Path("data/processed/video_features.parquet")

    print(f"Scanning {in_root} ...")
    features = build_feature_table(in_root)
    print(f"  Total: {len(features)} windows")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(out_path, index=False)
    print(f"Wrote {out_path}")

    print("\nFeature summary:")
    print(features[FEATURE_COLUMNS].describe())

    print("\nMissing values:")
    print(features[FEATURE_COLUMNS].isna().sum())


if __name__ == "__main__":
    main()