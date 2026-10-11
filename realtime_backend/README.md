> **Current default:** the models and phone return path are now connected through `python run_demo.py`. Use [CONNECTION_GUIDE.md](../CONNECTION_GUIDE.md). The following describes the retained, separate `--prepare-only` compatibility mode; do not run its CLI sender alongside the connected demo. Previous pending-schema statements refer to that preparation implementation, not the current connected server.

# Prepared real-time integration — models intentionally disconnected

This package prepares the existing **DrozyAI Flask page, Connect IQ app and
iPhone relay** for independent watch and video inference. It does not select,
load, train, replace or enable either model, start a camera, install an LLM, or
send a prediction to a physical watch during testing. Existing HTML/CSS/JS is
unchanged. The project uses Flask and a Node/iPhone relay, not the FastAPI server
assumed in the original brief; this contribution extends those components.

## Run the existing page in preparation mode

From `/Users/isaacoliva/Desktop/UCSC Hackathon/DrozyAI/DrozyAI`, with Python 3.12:

```sh
python3.12 -m venv .venv-streaming
.venv-streaming/bin/python -m pip install -r realtime_backend/requirements.txt
.venv-streaming/bin/python web/app.py --prepare-only --port 8777
```

Open <http://127.0.0.1:8777/>. Preparation mode serves the original page and
Bluetooth controls. Cameras/Bluetooth remain off until the user starts them.
`/api/health` reports `models_loaded: []`. Feature-file inference endpoints
return HTTP 503 with `MODEL_NOT_CONFIGURED` and a null score. They never return
fabricated demonstration scores. This mode needs only Flask and Pydantic,
without importing Torch, sklearn, NumPy or model artifacts.

The default `web/app.py` mode uses the connected ModelService and the experimental Garmin/RGB adapters. `--prepare-only` intentionally keeps those model connections disabled.

## Existing watch transport

```text
Garmin DrowsyAlert → existing iPhone companion → existing Node relay
                                                   ↓
                                  Python bounded raw telemetry buffer
                                                   ↓
                       [watch adapter pending] + [video adapter pending]
                                                   ↓
                           freshness / window checks → existing fusion
                                                   ↓
                             existing RelayClient → iPhone → Garmin
```

Use the unchanged setup in `phone-companion/README.md` and
`phone-companion/RELAY_CONTRACT.md`. The relay uses its own pairing token;
the Python code never logs it. Do not enter the Mac's localhost address on the
phone; use the existing relay's LAN address and pairing setup.

To receive/buffer real telemetry once the companion is ready:

```sh
# Set DROWSY_RELAY_TOKEN in your terminal to the EXISTING relay pairing token.
.venv-streaming/bin/python -m realtime_backend --relay-url http://127.0.0.1:8765
```

This worker adds **no HTTP server** and defaults to receiving only. The optional
`--send-status` flag sends the existing `model_result` envelope with
`riskScore: null`, `status: model_not_connected`, and the original input's
session/sequence/time. It sends no drowsiness prediction. Never run two workers
that send results for the same client. HTTP 202 means queued; watch delivery
still requires an accepted receipt from the existing relay.

The optional Flask blueprint and the CLI worker own separate in-memory runtimes.
Use one as the inference owner. In Flask, relay snapshots can be submitted to
`POST /garmin/data`; a future relay forwarder should use that route instead of
also starting the CLI worker. No relay forwarding was enabled automatically.

## Prepared interfaces

Preparation mode registers these routes on the **existing Flask application**:

| Route | Purpose |
| --- | --- |
| `GET /health` | Runtime/model/logging readiness |
| `POST /garmin/data` | Existing relay snapshot, or future timestamped raw batch |
| `GET /prediction/latest` | Compact current verdict; requires device/session |
| `GET /prediction/status` | Sensor/clock/model/buffer status |
| `GET /clock/ping`, `POST /clock/sync` | Optional explicit clock exchange |
| `POST /video/start` | Enable receiving external extracted features |
| `POST /video/stop` | Disable video, clear its history/prediction |
| `POST /video/features` | Timestamped extracted features, no raw frames |

Use `device_id` and `session_id` query parameters for prediction routes;
`data_origin=synthetic_test` selects an explicitly synthetic software-test
stream. The existing page's loopback/Origin checks are preserved. Phone traffic
continues through the existing authenticated relay, rather than bypassing those
checks or changing the Flask server's host restrictions.

`/video/start` does **not** initialize a webcam. It reports `camera_started:
false` and `external_extractor_pending`. The page's existing MediaPipe eye rule
is separate from an ML feature adapter. Its outputs are not silently supplied
to the TCN. The eventual extractor must provide its feature schema ID, camera
identity, timestamps, sampling rate and missing values. Stop/start clears the
source history; an in-flight result from a stopped source is discarded.

## Buffers and clocks

Raw schema-1 relay packets retain `sentAt` (watch UTC seconds), `watchUptimeMs`,
all scalar callback times, Garmin motion sensor timestamps, arrays/nulls,
truncation flags, units, requested rates, raw intervals, session and sequence,
plus the Mac's reception timestamp. Repeated telemetry sequence numbers are
ignored. Motion/IBI batches retain their own `batchId` for deduplication by the
eventual preprocessing adapter; a repeated array must not become new beats.
Device ID is the relay client ID until the companion supplies a hardware ID.

Watch uptime, sensor timestamps and Mac time are **different clock domains**.
No motion/beat timestamps are synthesized. Existing relay epoch timestamps are
screened for gross staleness, but that is not proof of clock synchronization.
Live raw telemetry is not currently model-ready: precise timestamp mapping,
coverage/truncation policy and model feature conversion remain pending.

For a future direct-upload integration, the prepared clock handshake records
four times: watch request send `d0`, server receive `s1`, server send `s2`, and
watch response receive `d3`. Server-minus-watch offset is
`((s1-d0)+(s2-d3))/2`; uncertainty includes half the network round trip and
timestamp resolution. Tokens are session-bound, single-use, bounded and expire
after 60 seconds. A provisional 100-ppm drift allowance grows between syncs.
This exchange has **not** been wired into the current phone/watch firmware.
Unsynchronized inputs cannot be fused. Epoch/video timestamps use the runtime's
epoch anchor plus monotonic elapsed time to avoid wall-clock jumps.

Default bounds are 600 seconds, 30,000 normalized samples per source, 2,048 raw
telemetry packets per stream, eight active streams, 2,048 observations per
request, and 512 KB per HTTP request. Missing values remain null. Retention or
capacity drops are counted. Source sampling rates are never assumed equal.

`alignment.py` supplies optional timestamp-based 1-Hz mean/population-variance
helpers inspired by `loader.py`, plus raw-consecutive-IBI RMSSD with explicit
gap breaks. They are **not** the model preprocessing pipeline and are never
automatically applied. In particular, the existing watch training RMSSD is
based on per-second IBI means and must not be replaced with beat-level RMSSD
without changing the trained model contract.

## Connect models later

`ModelSlots()` starts with **watch=None, video=None**. There is no directory
scanning, auto-selection, ML import, checkpoint loading or inference endpoint
that accepts arbitrary client-supplied predictions. Supply one trusted adapter
per modality only when integration is authorized. `AdapterSpec` requires exact
training feature order/units, input schema, preprocessing version, target,
missing-value policy and window. The adapter owns training-compatible feature
engineering, scaling, artifact loading once, and the model's actual threshold.

The runtime schedules separate watch/video executors, targets five-second
intervals, measures inference time and validates identities/output timestamps.
The adapter must reject insufficient coverage rather than fabricate features.
If an adapter fails, its old prediction is cleared; later inputs can recover.
Threads cannot forcibly cancel a stuck native inference call. For an untrusted
or potentially hanging model, use a process with an explicit termination policy
when that model is added.

The provided sources are recorded in `source_contracts.json`:

- Watch: `src/models/baseline.py`, `src/models/predict.py`, and
  `src/features/watch_features.py`; four selected features are `hr_mean`,
  `rmssd`, `temp_trend`, `motion_var`, 60-second windows, five-second steps.
- Facial: `src/models/facial_baseline.py`; TCN requires 15 × 60 channels and its
  scaler; logistic benchmark requires its original 22 features. The current
  `src/features/video_features.py` instead exports 11 different
  `FEATURE_COLUMNS`, without the `CHANNELS`/`FEATURES` imports required by the
  facial loader. Reconcile those versions before enabling facial inference.
- The watch training script saves scaler + HGB, while isotonic calibration is
  applied only to the exported evaluation score table. The saved pipeline is
  therefore not established as calibrated by that code. Fitted-artifact feature
  width/versions and end-to-end parity have not been tested in this contribution.
- Watch temperature source, accelerometer mg/25-Hz versus training units/32-Hz,
  and per-second-mean versus beat-level IBI definitions still need an explicit
  transfer decision. The watch extractor still reads an unused EDA column even
  though the selected four-feature model excludes EDA. Do not invent an EDA
  signal to satisfy that dead read.
- Existing web score routes expect `checked_score` and a dictionary-returning
  fusion helper, while the current `src/features/fusion.py` exports numerical
  array fusion. Preparation mode bypasses these incompatible inference imports;
  model-loaded web mode needs a compatible adapter/version when enabled.

## Fusion, scores and recommendations

`RepositoryFunctions.fuse_scores` delegates lazily to the user's
`src/features/fusion.py`. Runtime fusion first checks stream/target identity,
prediction age (10 seconds), window-end skew (2 seconds), overlap (at least half
the shorter window), and clock uncertainty (at most 1 second). Defaults use
weighted fusion with 0.5/0.5 and threshold 0.5, **provisional, not validated**.
Only compatible calibrated probabilities are averaged as a probability.
Otherwise watch classification is retained with a null display probability.
Stale/disabled/missing video falls back to watch; stale/missing watch yields
`INSUFFICIENT_DATA`. No implicit video-only mode is used for watch feedback.

The response carries verdict, score kind, mode, reason, server instance,
monotonic response sequence, original prediction timestamp and remaining
validity. A future direct-upload watch client must ignore older responses and
subtract transport time before retaining a result. The current relay preserves
the original telemetry sequence/time; it cannot receive a class-only result
through its numeric risk gauge, so an incompatible score remains null.

Optional consecutive-window confirmation defaults to one window (off). Set
`DROZY_CONFIRMATION_WINDOWS=3` for nominal 10-second additional delay at a
five-second cadence. Repeated HTTP reads never count as extra windows. Missing
data, mode/model changes and stale inputs reset confirmation. Raw labels and
smoothed verdicts remain separate; a probability is hidden when it contradicts
the held smoothed label.

`advice.py` prepares a validation wrapper around `src/advisor/llm_meta_advisor.py`
and `src/advisor/fallback.py`. No LLM requests are enabled. The wrapper rejects
invalid weights/confidence, recomputes weighted scores using Python/existing
fusion, and uses the existing deterministic fallback's action thresholds.
The current meta-advisor uses 0.40/0.70, while fallback uses 0.50/0.75; a narrative
for a contradictory action is discarded. Missing model risk returns null
action instead of `continue`. LLM confidence is explicitly self-reported, not
measured accuracy. The current meta-advisor fills absent feature inputs with
zero, so this wrapper calls it only with complete actual features in its own
schema. Do not rename normalized eye openness to raw EAR to make it fit.
The eventual caller must run LLM advice separately and discard late/stale advice;
LLM-generated weights are experimental and require validation before controlling
live fusion or watch alerts.

## Logging and verification

`data/predictions.csv` records original per-model labels, score kinds/scores,
window and prediction timestamps, raw/smoothed final labels, model versions,
mode, missingness reason, data ages, video state and source origin. Null scores
are empty CSV fields. Logging uses a bounded independent writer and rotates five
5-MB backups; failures/drops are exposed in status. `prediction_latency_ms`
means elapsed time from the oldest retained component's window end, including
input age; it is not a pure CPU inference benchmark. Individual `inference_ms`
is measured separately in each validated model output.

```sh
.venv-streaming/bin/python -m unittest discover -s realtime_backend/tests -v
```

34 software tests passed on Python 3.12 with synthetic payloads/stub adapters.
They cover original-page preservation, disabled model startup, input validation,
clock exchange, stale/missing/fallback behavior, smoothing, bounded buffering,
raw IBI handling, logging, slow-video isolation, video stop races, adapter
recovery and advisor validation. Physical watch/iPhone transport, actual model
inference/calibration, webcam transfer, LLM latency and end-to-end hardware
detection latency remain untested. No accuracy results are claimed here.

Official API references: [Garmin asynchronous communications](https://developer.garmin.com/connect-iq/api-docs/Toybox/Communications.html),
[Flask blueprints](https://flask.palletsprojects.com/en/stable/blueprints/).
