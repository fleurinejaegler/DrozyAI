"""Compare saved-model predictions across hosts using synthetic inputs only."""
from pathlib import Path
import argparse
import hashlib
import json
import math
import sys
from importlib.metadata import version

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import torch
from src.features.facial_sequence import CHANNELS, FEATURES
from src.models.predict import load_model, predict_score
from src.models.facial_baseline import FacialModels

ARTIFACTS = ['baseline_model.pkl', 'small_tcn.pt', 'tcn_scaler.joblib', 'facial_model.pkl']
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--write-reference', action='store_true')
args = parser.parse_args()
torch.set_num_threads(1)
watch = load_model(ROOT / 'data/processed/baseline_model.pkl')
video = FacialModels.load(ROOT / 'data/processed')
watch_inputs = [
    dict(hr_mean=75, rmssd=0.05, temp_trend=0.0001, motion_var=5),
    dict(hr_mean=60, rmssd=0.015, temp_trend=-0.02, motion_var=1),
    dict(hr_mean=90, rmssd=0.12, temp_trend=0.02, motion_var=50),
]
scores = {'watch': [predict_score(values, model=watch) for values in watch_inputs], 'video_tcn': [], 'video_logistic': []}
for eye, closed, mouth in [(1, 0, 0.2), (0.2, 0.8, 0.7), (0.7, 0.25, 0.4)]:
    sequence = np.zeros((15, 60), dtype=np.float32)
    sequence[0:2] = eye
    sequence[2:4] = closed
    sequence[9] = mouth
    sequence[14] = 1
    features = dict.fromkeys(FEATURES, 0.0)
    features.update(left_eye_mean=eye, right_eye_mean=eye, eye_closed_fraction=closed,
                    long_closure_fraction=closed, mouth_ratio_mean=mouth, valid_frame_fraction=1.0)
    scores['video_tcn'].append(video.predict_tcn(sequence, CHANNELS))
    scores['video_logistic'].append(video.predict_logistic(features))
result = {
    'artifacts': {name: hashlib.sha256((ROOT / 'data/processed' / name).read_bytes()).hexdigest() for name in ARTIFACTS},
    'scores': scores,
    'versions': {name: version(name) for name in ['numpy', 'pandas', 'scipy', 'scikit-learn', 'joblib', 'torch']},
    'data_origin': 'synthetic_migration_check',
}
reference_path = ROOT / 'deployment/model_reference.json'
if args.write_reference:
    reference_path.write_text(json.dumps(result, indent=2) + '\n')
    print('Saved reference predictions; no live sensor data was used.')
else:
    reference = json.loads(reference_path.read_text())
    if result['artifacts'] != reference['artifacts']:
        raise SystemExit('Model/scaler checksum mismatch')
    errors = []
    for model, expected in reference['scores'].items():
        errors.extend(abs(a-b) for a,b in zip(result['scores'][model], expected, strict=True))
    if not all(math.isfinite(x) and x <= 1e-6 for x in errors):
        raise SystemExit(f'Prediction parity failed: max error {max(errors)}')
    print(json.dumps({'model_checksums_match': True, 'predictions_compared': len(errors),
                      'maximum_absolute_difference': max(errors), 'versions': result['versions']}, indent=2))
