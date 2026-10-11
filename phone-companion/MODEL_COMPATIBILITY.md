# Current model and live-device compatibility

The actual saved watch pipeline was loaded and inspected: **four inputs**, RobustScaler plus HistGradientBoostingClassifier, classes [0,1]. Its order is `hr_mean`, `rmssd`, `temp_trend`, `motion_var`. EDA is not required. The artifact and training procedure were not changed or retrained. Isotonic calibration from evaluation is not part of the final saved pipeline, so scores remain uncalibrated.

The default connected server now uses `web/garmin_features.py` and `web/relay_worker.py`. They aggregate real sensor packets into 60-second/five-second windows and call `src/models/predict.py`, then the existing fusion and advisor code. The older standalone `repo_model_adapter.py` remains conservative for raw packets and is not the launcher's inference owner.

| Input | Connected implementation | Transfer limitation |
|---|---|---|
| HR mean | Mean of observed per-second BPM, ≥90% coverage | Different wearable sensor |
| RMSSD | Genuine intervals ms→seconds, callback-bin per-second means, original successive-difference extractor | Missing intervals block inference; callback time is not the actual beat timestamp |
| Temperature trend | Last real value carried through null packets in the same session, original slope extractor | Sensor.Info temperature is not established as skin temperature; first value required; carrying can flatten slope |
| Motion variance | Timestamped nontruncated 25-Hz mg samples →64 counts/g; per-second variance across axes | E4 training used 32 Hz; dropped batches and units/rate transfer need validation |

Every model quality record identifies this experimental transfer and temperature age. First-packet UTC is only one-second resolution. Camera uses the recovered original 15-channel geometry/event schema and saved TCN/scaler; MediaPipe RGB geometry is an experimental proxy for the original 68-point camera source. The original separate `src/features/video_features.py` is preserved.

No BPM-derived IBI, fabricated initial temperature, EDA placeholder or invented dense camera frames are introduced. Video-only inference can still produce an independent watch alarm when telemetry transport exists. Physical watch availability and Garmin/webcam detection accuracy have not been established by compiler/unit tests.

See [CONNECTION_GUIDE.md](../CONNECTION_GUIDE.md) for setup, sensor prerequisites and actual-device checks. The local HTTP relay keeps the original authenticated protocol, input session/sequence and capture time. Queued commands require a watch receipt before being called accepted.
