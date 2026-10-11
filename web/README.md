# Drowsy dashboard and facial model

This contribution packages Isaac's existing local camera/Garmin dashboard,
the trained small TCN, its scaler, the logistic video benchmark and a Flask
API that calls the existing teammate-owned watch predictor. The server loads
all three models once at startup. It does not retrain the watch model.

## Run locally

Use Python **3.12**, matching the saved model environment. Code uses modern
Python type hints; the pinned dependencies have not been tested on Python 3.10.
From the **DrozyAI repository root**:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r web/requirements.txt
python web/app.py
```

Open <http://127.0.0.1:8777>. To choose a different port:
`python web/app.py --port 5000`. The server binds only to this computer and
debug mode is off. The original dashboard at port 8776 is not replaced.

The pinned browser face-tracking assets are included, with their upstream
license and source/SHA-256 manifest. After dependencies are installed, camera
analysis has no external network requests. The camera stays off until you
press **Start camera** and grant browser permission. No video recording or
frame upload is implemented.

For HR, wear your Forerunner 970, hold the middle-left button, choose **Watch
Settings → Health & Wellness → Wrist Heart Rate → Broadcast Heart Rate**, then
press START. On the dashboard choose **Scan for watch**, allow macOS Bluetooth
access if requested, and select your device. HR packets have been unit tested;
the physical watch connection and camera permissions still need hardware testing.
See the [Garmin manual](https://www8.garmin.com/manuals/webhelp/GUID-025D75CF-3445-49E1-8D81-1AA74AB4E00F/EN-US/GUID-C9AFFA77-2E39-4079-8E55-58280EF8FE00.html).

## What runs now

- Live browser camera tracking and the existing **experimental eye-closure rule**.
- Optional direct Bluetooth **heart rate**, connection status and trend chart.
- `/api/score`: the existing teammate watch model, given all five measured features.
- `/api/facial`: the saved **small TCN**, given its 15 × 60 feature sequence,
  or the saved logistic regression benchmark, given its 22 features.
- `/api/fusion`: max or weighted score fusion, with explicit missing-source modes.
- A separate feature-file test in the dashboard that runs real facial inference.

**Integration remaining:** the live MediaPipe output is not the TCN's training
schema; a matching geometry/time adapter and webcam validation are needed.
Bluetooth HR alone cannot provide the watch model's five inputs. A fused API
response does not yet trigger a Garmin vibration or watch notification. Missing
data is never fabricated. Live camera cues and uploaded model scores are labeled
separately rather than presented as a working multimodal detector.

Select a matching JSON feature file in **Test the trained facial model**. That
explicit action sends the numeric features only to this Mac's local server;
the file is used in memory and not saved. See [the API documentation](../docs/web_api.md)
for schema details and valid synthetic smoke-test commands. The test's 0–100
number is an uncalibrated model score, not a percentage chance of drowsiness.

## Contribution tree

```text
web/
  app.py
  routes/
    __init__.py
    score.py
    facial.py
    fusion.py
    watch.py                  # Existing dashboard Bluetooth bridge
  static/
    index.html
    style.css
    app.js
    metrics.mjs
    vision-worker.mjs
    vendor/
      LICENSE
      README.md
      manifest.json
      vision_bundle.mjs
      face_landmarker.task
      wasm/
        vision_wasm_internal.js
        vision_wasm_internal.wasm
        vision_wasm_nosimd_internal.js
        vision_wasm_nosimd_internal.wasm
  requirements.txt
  README.md
src/features/
  video_features.py            # Original event definitions + 68-point adapter
  fusion.py
src/models/
  facial_baseline.py           # TCN architecture/load/inference + logistic benchmark
data/processed/
  small_tcn.pt
  tcn_scaler.joblib
  facial_model.pkl             # Existing logistic benchmark; not the TCN
  facial_model_manifest.json
docs/
  web_api.md
  fusion_strategy.md
tests/
  test_web_api.py
  test_fusion.py
  test_video_features.py
  test_watch_bridge.py
  metrics.test.mjs
.gitignore                     # Narrow exceptions for the new small artifacts
```

The repository's existing `src/models/predict.py`, `src/models/baseline.py`,
`src/features/watch_features.py` and `data/processed/baseline_model.pkl` remain
unchanged. Existing shared data files are not changed. No new raw datasets,
participant feature exports, notebooks with recordings, videos, camera images,
session exports, credentials, virtual environments or download archives belong
in this contribution. The small model artifacts and upstream browser assets
are the only newly included binary files.

## Verification

```sh
python -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/metrics.test.mjs
```

Node is needed only for the existing browser-metric unit tests, not to run the
dashboard. Tests use synthetic features and local saved models; they never
start a camera, scan Bluetooth or retrain models. Automated checks cover
prediction parity, feature order, shape, finite values, coverage, stale HR,
missing sources, fusion boundaries and local-only HTTP actions.

## Review and Git commands

The prepared local branch is `isaac/web-app`, based on the latest inspected
`main`. Before adding files, review `git diff` and the exact file list. Use
explicit paths so existing local data or environments cannot be added by accident:

```sh
# Use this only in a clean checkout that does not already have the branch.
git fetch origin main
git switch -c isaac/web-app origin/main

git add .gitignore web/ src/features/video_features.py src/features/fusion.py \
  src/models/facial_baseline.py data/processed/small_tcn.pt \
  data/processed/tcn_scaler.joblib data/processed/facial_model.pkl \
  data/processed/facial_model_manifest.json docs/web_api.md docs/fusion_strategy.md \
  tests/test_web_api.py tests/test_fusion.py tests/test_video_features.py \
  tests/test_watch_bridge.py tests/metrics.test.mjs
git diff --cached --stat
git diff --cached --check
git commit -m "Add Drowsy dashboard, small TCN inference and score fusion API"

# Only after Isaac confirms the destination and upload:
git push -u origin isaac/web-app

# With GitHub CLI installed and authenticated, create a draft PR, not a merge:
gh pr create --draft --base main --head isaac/web-app \
  --title "Add Drowsy dashboard, small TCN inference and score fusion API" \
  --body-file /path/to/prepared-pr-description.md
```

If using a fork, set `origin` to that fork and retain the team repository as
`upstream`; do not execute a push to both destinations. Do not force-push or
merge without separate authorization. A working Git author identity and GitHub
authentication are required to commit and push. This folder is a local research
app, not a deployment configuration or an invitation to publish health data.
