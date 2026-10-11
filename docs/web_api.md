# Local web API

Run `python web/app.py` from the repository root, then open
<http://127.0.0.1:8777>. Use `--port 5000` if that port is available. This new
package uses 8777 so the existing dashboard at 8776 can stay running.

All POST bodies are JSON objects with `Content-Type: application/json`.
Invalid values return `{ "error": "..." }` with status 400; unsupported media
types return 415 and requests above 512 KB return 413. No cross-origin access
is enabled. Bluetooth actions additionally require the local page's Origin.
Normal inference requests from local command-line clients do not require Origin.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/` | Live dashboard and recorded-feature model test |
| GET | `/api/health` | Startup-loaded models and unfinished live integrations |
| GET | `/api/models` | Exact feature names, channel order and sequence shape |
| POST | `/api/score` | Teammate watch model, from five measured features |
| POST | `/api/facial` | Small TCN or logistic regression, from matching video features |
| POST | `/api/fusion` | Explicit experimental fusion, including missing-source modes |
| GET | `/api/state` | Current Bluetooth HR status and up to five minutes of readings |
| POST | `/api/scan` | Scan for Bluetooth HR broadcasters; body `{}` |
| POST | `/api/connect` | Connect a device from the last scan; body `{"id":"scan-result-id"}` |
| POST | `/api/disconnect` | Disconnect HR; body `{}` |

## Watch score

The teammate-owned `load_model` is called once at app startup with an absolute
path. `predict_score(features, model=model)` is treated as a black box. No
watch-model training, imputation or modifications are performed.

```sh
curl -X POST http://127.0.0.1:8777/api/score \
  -H 'Content-Type: application/json' \
  -d '{"hr_mean":75.3,"rmssd":0.052,"temp_trend":-0.0001,"eda_peaks":3,"motion_var":8.2}'
```

Response: `{"score":0.0, "model":"teammate_watch_baseline",
"source":"provided_features", "live_garmin_adapter_ready":false}`, where
`score` is the actual saved model's output in [0, 1], not the illustrative 0.0.
A `{"features":{...}}` envelope is also accepted.

| Feature | Training definition / unit |
|---|---|
| `hr_mean` | Mean HR over a 60-second window, BPM |
| `rmssd` | Existing teammate pipeline's successive IBI differences, seconds |
| `temp_trend` | Existing pipeline's skin-temperature slope, degrees C per sample |
| `eda_peaks` | Existing pipeline's EDA local-peak count over the window |
| `motion_var` | Mean of the three existing acceleration-variance columns, dataset units squared |

Use `src/features/watch_features.py` as the authoritative definitions. Garmin
Bluetooth HR does **not** provide all five fields in this app. HRV, EDA,
temperature and acceleration must not be inferred from BPM or filled with
sample values. Missing features return an error. Empatica-to-Garmin transfer
and the watch score's calibration have not been established by this integration.

## Facial score

The default is the existing **small TCN**, rather than the logistic-only
template. Send one 15-channel × 60-second array, **channels first**. Seconds
are ordered from oldest to newest. Channel names must exactly match the list
returned by `/api/models`.

```json
{"model":"small_tcn","channels":["left_eye_openness","... exact remaining names ..."],
 "sequence":[["60 numeric seconds per channel"]]}
```

This abbreviated schema is explanatory, not a valid request. To generate a
valid **synthetic** contract smoke test (not a person or a detection result):

```sh
python - <<'PY'
import json
from urllib.request import urlopen, Request
base = 'http://127.0.0.1:8777'
channels = json.load(urlopen(base + '/api/models'))['facial']['channels']
sequence = [[0.0] * 60 for _ in channels]
for index in (0, 1, 14):
    sequence[index] = [1.0] * 60
body = {'model':'small_tcn', 'channels':channels, 'sequence':sequence}
request = Request(base + '/api/facial', data=json.dumps(body).encode(),
                  headers={'Content-Type':'application/json'})
print(json.load(urlopen(request)))
PY
```

Response fields: `score` in [0, 1], `model`, `score_type:"uncalibrated_score"`,
`source:"provided_features"`, `live_camera_adapter_ready:false`.

The original training scaler is applied per second, in channel order, after
matching float32 input rounding. Coverage needs >=90% across the window and
>=50% in each second. Fractions, nonnegative geometry values, finite numbers,
channel order and dimensions are checked. Correct semantics and capture
timing remain the caller's responsibility; passing validation does not prove
that arbitrary numbers came from the required extraction pipeline.

The alternative `{"model":"logistic_regression","features":{...}}` needs all
22 feature names from `/api/models` and >=90% valid-frame coverage. Its saved
artifact is `facial_model.pkl`; the TCN uses `small_tcn.pt` **and**
`tcn_scaler.joblib`. Do not rename the TCN checkpoint to `.pkl` or omit scaling.

`src/features/video_features.py` preserves the training event definitions and
provides `extract_68point_window(frames)`. It expects a 60 FPS time grid of
68-point image-plane landmarks, with at least 15 seconds of initial
calibration plus 60 seconds of history. Missing frames occupy their original
slots as NaNs. Mouth events are candidate mouth openings, not verified yawns.
Eye closure is an EAR proxy, not validated pupil-based PERCLOS.

The live dashboard currently uses MediaPipe expression coefficients and a
sparse set of landmarks at a different sampling rate. Those are **incompatible**
with the saved TCN contract. No automatic live-camera TCN call is made until a
matching geometry/time adapter and webcam validation are provided. The UI's
file test only calls `/api/facial` on an explicitly selected local feature file.

## Fusion

Compute component scores on the server:

```json
{"watch_features":{"hr_mean":75.3,"rmssd":0.052,"temp_trend":-0.0001,
                   "eda_peaks":3,"motion_var":8.2},
 "facial":{"model":"small_tcn","channels":["..."],"sequence":[["..."]]},
 "strategy":"max"}
```

Alternatively test fusion with **provided example scores**:

```sh
curl -X POST http://127.0.0.1:8777/api/fusion \
  -H 'Content-Type: application/json' \
  -d '{"watch_score":0.2,"facial_score":0.8,"strategy":"max"}'
```

The result includes `fused_score:0.8`, `alert:true`, `traffic_light:"red"`,
`mode:"combined"`, both component scores, strategy and `validated:false`.
`input_source` distinguishes model-feature inference from provided scores.
Do not mix those two input forms in one request.

Use null/omitted values for an unavailable source. Single-source results
identify `watch_only` or `facial_only`. With neither source, `fused_score` is
null, `traffic_light` and `mode` are `unavailable`, and `alert` is false. False
in this unavailable state is **not** evidence of alertness.

`watch_alert_sent` is always false: a model API response does not send a
notification or vibration to a Garmin app. Alert transport is unfinished.
See [fusion_strategy.md](fusion_strategy.md) for boundaries and limitations.
