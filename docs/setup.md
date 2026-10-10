# Project Setup

This document records the initial setup of the DrozyAI project.

## 1. Project Skeleton

The repository is organized around the six stages of the plan: capture, features, models, advisor, dashboard, and driver app.

## 2. Configuration Files

- requirements.txt — Python dependencies
- .gitignore — excludes data, models, secrets, caches
- docs/plan.md — project plan and deliverables checklist

## 3. End-to-End Placeholder Pipeline

src/main.py implements a minimal version of the full pipeline.

Run it with:

    python3 src/main.py

Expected output:

    [1] Capture: watch + webcam (placeholder)
    [2] Feature extraction (placeholder)
    [3] Prediction (placeholder)
    [4] Nemotron advice (placeholder)

    Risk: 0.30 -> Advice: continue

## 4. First Commit

The initial commit was 8d25c8d Set up project skeleton for DrozyAI drowsiness detection.

## 5. Next Steps

1. Create and activate a Python virtual environment.
2. Install dependencies from requirements.txt.
3. Implement src/capture/webcam.py using MediaPipe.
4. Implement src/capture/watch.py using bleak.
5. Build the Streamlit dashboard skeleton.
6. Wire up the Nemotron advisor.
