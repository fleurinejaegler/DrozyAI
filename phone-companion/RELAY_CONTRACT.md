# Relay contract v1

The local service bridges a laptop Python model/website to DrowsyRelay iPhone. All requests require `Authorization: Bearer PAIRING_TOKEN`; JSON requests also use `Content-Type: application/json`. Base URL on laptop is `http://127.0.0.1:8765`. On phone, use the laptop's LAN IP. Use client ID `demo`.

## Python model

Add `phone-companion/local-relay` to your Python import path, then:

```python
import os
from gateway_client import RelayClient

relay = RelayClient("http://127.0.0.1:8765", os.environ["DROWSY_RELAY_TOKEN"])
snapshot = relay.state()
packet = snapshot["telemetry"]
if snapshot["phoneRecent"] and packet is not None:
    # Your existing model, with its exact preprocessing/missing-data policy:
    score = your_model_function(packet)
    relay.send_model_result(snapshot, float(score), "your-model-version")
```

Define `DROWSY_RELAY_TOKEN` to match the token printed by the relay, or set it before launching the relay so both processes share it. `your_model_function` is a placeholder for your teammate's implementation, not supplied here. `score` is a finite probability/risk in **0–1**, not 0–100. If required inputs are absent, send `None` with `status="insufficient_data"`; never send zero as an imputation. Use the original snapshot for both inference and submission, even if new packets arrive. Evaluate about once every 5 seconds, use the newest valid input, and deduplicate repeated `batchId` motion/beat arrays. Do not silently fill dropped packets. The input's capture timestamp/session is preserved; inference taking more than 10 seconds is rejected.

For camera decisions from the laptop website/model:

```python
relay.send_camera_alert(relay.state(), "high", frame_capture_epoch_seconds)
# Or "warning". Clear only following an explicit fresh recovery decision:
relay.clear_camera_alert(relay.state(), recovery_capture_epoch_seconds)
```

Camera commands do not need watch vitals, but do need a recent running phone and valid watch session. Never replace an old frame time with the current send time. Raw video remains on the phone/laptop, not on the watch.

## HTTP endpoints

`GET /api/state?clientId=demo` returns:

```json
{"protocol":1,"watchSession":"WATCH_SESSION","phoneRecent":true,"telemetry":{"type":"telemetry","session":"WATCH_SESSION","sequence":12,"sentAt":1790000000,"heartRateBpm":72,"spo2Percent":null},"events":[]}
```

The abbreviated telemetry object stands for the complete unchanged schema in [TELEMETRY.md](../DrowsyApp/DrowsyAlert/TELEMETRY.md). A missing/stale telemetry snapshot is null. `phoneRecent` requires a running phone exchange in the last 10 seconds. Events retain the last 64 entries in memory; deduplicate retries by commandId/status or watch message sequence.

`POST /api/command` with a vitals-model result:

```json
{"clientId":"demo","command":{"protocol":1,"commandId":"UNIQUE-ID","type":"model_result","watchSession":"WATCH_SESSION","capturedAt":1790000000,"inputTelemetrySequence":12,"riskScore":0.82,"status":"ready","modelVersion":"team-v1"}}
```

The example timestamps are placeholders. `capturedAt` must match the original input/frame capture time, in UTC epoch seconds. Status can be `ready` with 0–1 score, or `insufficient_data` / `model_not_connected` with null score. Versions are nonempty strings up to 64 characters. The input sequence must reference recent telemetry from the same watch session. This is the window-end/latest input timestamp, not necessarily the oldest sample in a 60-second feature window. Input quality and preprocessing remain the model's responsibility.

Camera alert command:

```json
{"clientId":"demo","command":{"protocol":1,"commandId":"UNIQUE-ID","type":"camera_alert","watchSession":"WATCH_SESSION","capturedAt":1790000000,"severity":"high"}}
```

Use `camera_clear` without severity to clear the camera alert only. Both `warning` and `high` trigger immediately through the camera alarm controller. Vitals thresholds are applied by the watch to model scores and do not need a separate camera command.

HTTP 202 means queued in the laptop service. The next phone exchange retrieves commands. Look in `/api/state` events for final `command_result` with the same commandId and `status: accepted`. `queued` and `submitted` are intermediate. Rejection statuses include stale/session/input validation errors, duplicate, insufficient_data, rate_limited, superseded, paused, transport_failed, receipt_timeout, and delivery_unknown. An unknown receipt means delivery is unconfirmed; do not automatically retry old results.

`POST /api/phone/exchange` is used by the native app every second. It uploads protocol, clientId, relaySession, watchSession, running, latest telemetry, and events; the response is `{protocol:1, commands:[...]}`. Queues are bounded and cleared when phone/watch sessions change. There is no guaranteed offline command backlog or persistent storage.

## Bundled website interface

The native app injects `window.DrowsyRelay`. It emits `drowsy:state`, `drowsy:telemetry`, `drowsy:watch`, `drowsy:model`, and `drowsy:delivery` DOM events. Read `event.detail`:

```javascript
window.addEventListener('drowsy:telemetry', async ({ detail: packet }) => {
  // For a future browser-compatible model; never call once per raw accelerometer sample.
  // Schedule actual model evaluation at 5-second intervals and validate its inputs.
  const score = await yourBrowserModel(packet);
  await window.DrowsyRelay.sendModelResult({
    riskScore: score, status: 'ready', modelVersion: 'browser-v1',
    capturedAt: packet.sentAt, inputTelemetrySequence: packet.sequence
  });
});
```

`sendCameraAlert('high', originalFrameCaptureTime)` and `clearCameraAlert(originalRecoveryTime)` return promises that resolve only after an accepted watch receipt. No native bridge exists in an ordinary desktop browser; use the HTTP API for the laptop website. The bundled manual page is a transport demonstration, not a trained model.

## Watch-side mapping

The phone uses `source: phone_relay`; a `model_result` becomes the watch ModelAdapter envelope. UTC age is translated to watch monotonic time without renewing old data. The watch additionally checks actual core sensor freshness, bounds and timestamps, a five-second evaluation limit, and replay mode. Accepted scores update the gauge and existing alert thresholds; missing/stale results reset consecutive counters while retaining warnings. Camera alerts route into the independent phone alert controller. START acknowledges both sources; `user_acknowledged` is sent back to phone/website with source `watch_model`, `phone_video`, or `both`, and corresponding modelSequence/cameraSequence fields. Acknowledgment silences outputs; it does not create a low-risk prediction.
