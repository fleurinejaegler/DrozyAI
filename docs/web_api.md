# Connected local web API

Start from the repository root with `python run_demo.py`. Default dashboard: http://127.0.0.1:8777/. The launcher also starts the existing authenticated phone relay, default port 8765. See [CONNECTION_GUIDE.md](../CONNECTION_GUIDE.md).

All POST bodies are JSON objects with `Content-Type: application/json`. Invalid input returns 400, unsupported media types 415, and bodies above 512 KB 413. The web server accepts loopback Host names and rejects cross-origin actions. Bluetooth actions and pairing details require the local page's Origin. The pairing token is never included in health/state output.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health`, `/health` | Loaded models, live adapter/transport configuration |
| GET | `/api/models` | Exact feature/channel names and dimensions |
| POST | `/api/score` | Watch artifact inference from four measured features |
| POST | `/api/facial` | Video TCN or logistic artifact inference |
| POST | `/api/fusion` | Server computes both component scores from features |
| POST | `/api/live/watch`, `/api/live/video` | Timestamped, same-session measured model inputs |
| POST | `/api/live/watch/stop`, `/api/live/video/stop` | Invalidate that modality and discard pending advice |
| GET | `/api/live/state` | Fresh scores, fusion, advice and phone-delivery state |
| POST | `/api/baseline` | Explicit numeric driver baseline |
| POST | `/garmin/data` | Existing relay snapshot intake; launcher already polls it |
| POST | `/api/watch/send` | Queue latest eligible result; receipt still required |
| POST | `/api/setup` | Explicit same-origin pairing details; keep token private |
| GET | `/api/state` | Optional direct Bluetooth HR status/history |
| POST | `/api/scan`, `/api/connect`, `/api/disconnect` | Existing direct Bluetooth HR controls |

## Four-feature watch model

`POST /api/score` accepts this object or a `features` envelope:

```json
{"hr_mean":75.3,"rmssd":0.052,"temp_trend":-0.0001,"motion_var":8.2}
```

These are illustrative inputs for contract testing, not a live driver's measurements. HR is BPM; RMSSD is seconds from successive *per-second IBI means*, not the watch's beat-level RMSSD; temperature trend follows the original compacted-sample slope; motion variance is the mean per-second variance across E4-count acceleration axes. The authoritative extractor is `src/features/watch_features.py`. The saved pipeline has exactly four inputs and does not require EDA.

Response fields include `score` in [0,1], `drowsiness_score` (score ×100), model/version, features, `score_type:uncalibrated_score`, and `source:provided_features`. The Garmin adapter is ready but device transfer is unvalidated. Offline inference never sends a watch command. Missing/nonfinite features are rejected.

## Video model

The default `small_tcn` needs a channels-first 15 ×60 numeric sequence, oldest second first. Exact channel order comes from `/api/models`. `logistic_regression` takes all 22 named summary features in a `features` dictionary. The TCN uses `small_tcn.pt` and its original `tcn_scaler.joblib`; logistic uses `facial_model.pkl`.

```json
{"model":"small_tcn","channels":["exact names from /api/models"],"sequence":[["60 numeric values per channel"]]}
```

This abbreviated example is explanatory, not a runnable request. Coverage must be at least 90% overall and 50% in every second. Fractions, finite values, nonnegative event/geometry values, order and dimensions are validated. `src/features/facial_sequence.py` preserves the recovered original training definitions and a 68-point extractor. Live `web/static/model-features.mjs` uses observed-time MediaPipe geometry as an experimental RGB transfer. Arbitrary expression coefficients are not accepted as a substitute for training channels.

## Offline fusion

`POST /api/fusion` takes `watch_features` and/or `facial` as above, with optional `strategy` (`mean`, `weighted`, `max`, `product`) and `watch_weight` in [0,1]. Both component scores are computed by the server. Client-supplied `watch_score` or `facial_score` are rejected. At least one source is required.

The response includes `score`, `drowsiness_score`, `watch_score`, `facial_score`, `mode` (`watch_only`, `video_only`, `watch_video`), components and deterministic advice. `transport_eligible:false` and `watch_alert_sent:false` distinguish feature-file tests from live watch return.

## Live windows

Both live endpoints also require:

```json
{"device_id":"demo","session_id":"actual-watch-session","data_origin":"live",
 "window":{"start_ms":1790000040000,"end_ms":1790000100000},
 "schema_id":"watch.garmin.transfer.v1","features":{"hr_mean":75.3,"rmssd":0.052,"temp_trend":0,"motion_var":8.2}}
```

Use actual current Mac/watch UTC times, exactly 60,000 ms apart. Five-second UTC boundaries are used by built-in adapters. End time must be current or at most ten seconds old, never future. Use the same device/session/origin for both modalities; synthetic test streams use `data_origin:synthetic_test` and never enter the live return path. Watch schema IDs: `watch.uldd.four.v1` and experimental `watch.garmin.transfer.v1`; video IDs: `facial.uldd.tcn15.v1` and experimental `facial.rgb.geometry.v1`. Video live body also contains its model, channels/sequence and preferably all 22 summaries for advisor context.

`GET /api/live/state?device_id=demo&session_id=...&data_origin=live` gives current state. Omit identity to use the connected relay's watch session. Fresh ends must be within two seconds to combine; otherwise the watch score is used and `reason:VIDEO_WINDOW_NOT_ALIGNED` explains it. No fresh model yields `status:collecting` and null score. Every result includes remaining `valid_for_ms`; clients must stop displaying an expired score.

The local advisor runs asynchronously only when both real model components are present. Python validates/recomputes weights; immediate deterministic advice is always available. Temperature quality contains the last real Celsius value, original age and carry flag. Null packets do not renew the temperature timestamp; new watch sessions reset it. Missing genuine IBI blocks watch inference.

`POST /api/baseline` uses stream identity plus a numeric `baseline` dictionary. Baseline standard deviations cannot be negative. Automatic descriptive baseline rows do not assert alertness.

The relay worker sends fresh watch/fused results through the original `RelayClient`, preserving capture time and input sequence. Independent video alarms can operate with missing watch-model features when watch telemetry/session transport exists. `queued_delivery_unconfirmed` means only transport acceptance; a later watch `command_result` supplies final status. No HTTP response proves physical alarm playback.

Preparation mode (`web/app.py --prepare-only`) intentionally does not load models and retains the separate [preparation contracts](../realtime_backend/README.md).
