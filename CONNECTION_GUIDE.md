# Connect the watch, video models and local advisor

## Start the laptop

Use Python 3.12, matching the saved artifacts, from the repository root:

```sh
python3.12 -m venv .venv-demo
.venv-demo/bin/python -m pip install -r web/requirements.txt
.venv-demo/bin/python run_demo.py --check
.venv-demo/bin/python run_demo.py
```

Node.js is needed for the existing phone relay; it has no npm dependencies. `DROWSY_NODE` can point to a Node executable. The launcher also recognizes the bundled Codex runtime on this Mac. `--check` loads and validates the actual saved models without starting servers or hardware.

The page is http://127.0.0.1:8777/. If occupied, use `--port 8778`. Choose `--relay-port 8766` if 8765 is occupied. The launcher starts the authenticated LAN relay and the model server together, checks occupied ports, and stops only its own children on Ctrl+C. It creates a temporary pairing token in memory; click **Show phone pairing details** on the local page to reveal it. The phone URL uses the Mac's LAN address and the chosen relay port. Entering localhost on the iPhone would point at the phone.

## Pair the real devices

On this Mac, use `/Users/isaacoliva/Desktop/UCSC Hackathon/DrozyAI/DrozyAI/phone-companion/DrowsyRelay.xcodeproj`. There is an older duplicate one folder higher. The integrated project has the selected Personal Team and has passed a signed device build. If Xcode says **Developer Mode disabled**, enable it under iPhone **Settings → Privacy & Security → Developer Mode**, restart and confirm on the phone, then unlock the phone and Run again.

1. Install `DrowsyApp/DrowsyAlert/bin/DrowsyAlert.prg` into `GARMIN/APPS` on the Forerunner 970. Open **DrowsyAlert**, and choose **Return to live** if replay mode is active. The compiled app UUID is the one used by the iPhone project.
2. Pair the watch with Garmin Connect on your iPhone. Open `phone-companion/DrowsyRelay.xcodeproj` in Xcode. Select your Apple development team under Signing & Capabilities, choose the physical iPhone, enable Developer Mode if requested, and Run. Allow Bluetooth and local-network access. This requires your Apple signing identity; the simulator cannot pair to a physical Garmin.
3. In DrowsyRelay, choose **Select watch**, share/select the watch through Garmin Connect, then enter the phone URL, client ID **demo**, and temporary pairing token from the Mac page. Tap **Connect laptop**.
4. Keep iPhone and Mac on the same network, and keep DrowsyRelay and DrowsyAlert foreground. The phone/watch exchange is near-live and can drop sensor batches while a Bluetooth receipt is in flight. Watch sensor coverage and missing-field reasons are shown on the page.
5. Start the Mac page's camera and allow browser permission. Camera frames stay in the browser. Only numeric geometry/event features are posted to the local Python model. No camera frames travel over Garmin Bluetooth.

Unsigned iOS simulator and physical-device target builds, plus a Forerunner 970 release compiler build, were verified on this Mac. These do not prove physical pairing, sensor availability or alarm playback. Apple device signing/install and the physical checks below remain necessary.

## What computes the score

- **Watch:** the unchanged fitted `data/processed/baseline_model.pkl` pipeline, RobustScaler plus HistGradientBoostingClassifier, using `hr_mean`, `rmssd`, `temp_trend`, `motion_var`. No EDA input is required. The extractor reuses `src/features/watch_features.py` over a 60-second, one-row-per-second table.
- **Video:** `small_tcn.pt` and `tcn_scaler.joblib`, using the original 15-channel × 60-second event sequence. `facial_model.pkl` remains callable as the 22-feature logistic benchmark. Live inference uses the TCN. The recovered original training schema is in `src/features/facial_sequence.py`; the separate existing `video_features.py` file is preserved.
- **Time:** trailing 60-second windows on five-second UTC boundaries, oldest to newest. The first watch packet anchors uptime to watch UTC at one-second resolution. Set the watch/phone/Mac clocks correctly. Both model windows must be fresh (at most 10 seconds old), from the same session, and their ends must be within two seconds to fuse.
- **Fusion:** the existing `src/features/fusion.py`, default 50/50 average. One available source runs alone. Missing/stale windows are unavailable, never low-risk placeholder scores.
- **Advisor:** `local_explanation.py` explains fresh watch-only, camera-only or combined results asynchronously. Python fixes the fusion score and alert action before the LLM call; LLM output cannot change either. Invalid, late or failed responses retain deterministic advice. Advisor action thresholds are 0.50 for a break and 0.75 for stopping safely. The watch's original numeric gauge thresholds remain 0.70/0.90; video/fused advisor alerts also use its separate camera-alert channel.

The page shows the score multiplied by 100. This is an **uncalibrated research score**, not accuracy or a calibrated percentage chance of drowsiness. Both model artifacts were trained on other sensors/cameras; this integration has not measured real Garmin/webcam detection accuracy.

## Temperature and other sensor details

A null temperature uses the **last real value in that watch session**. The original reading time is preserved, so the page shows its age and whether it was carried. Before the first real temperature, it remains unavailable. A new watch session clears it. Long flat carried history can make temperature slope approximately zero; carrying does not prove the driver or sensor stayed at that temperature.

Genuine `beatIntervalsMs` values are converted from milliseconds to seconds and aggregated into the original per-second IBI means before the original RMSSD calculation. The watch's precomputed beat-level HRV and HR-derived synthetic intervals are not substituted. No real IBI means no watch model result; video-only predictions can still trigger the independent watch alert path.

Accelerometer mg values are converted to E4 raw counts using 64 counts/g before per-second axis variances. The app requests 25 Hz and training used 32 Hz; the transfer is approximate. The existing protocol sends at most the latest 25 samples per packet, so dropped or truncated batches can prevent sufficient coverage. The latest interval batch is callback-timed because actual beat timestamps are not exported. Sensor.Info temperature is not established as skin temperature. These differences are recorded in model quality metadata.

Garmin documents optional/null sensor fields and Celsius/mg in [Sensor.Info](https://developer.garmin.com/connect-iq/api-docs/Toybox/Sensor/Info.html); genuine interval units/device support are described in [HeartRateData](https://developer.garmin.com/connect-iq/api-docs/Toybox/Sensor/HeartRateData.html). API support does not guarantee non-null intervals during your particular optical-sensor session. Training used Empatica and 68-point camera features; see the [UL-DD paper](https://arxiv.org/html/2507.13403v1).

Camera startup needs approximately 15 seconds of visible-face geometry calibration plus 60 seconds of history, then updates every five seconds. Missing-face gaps are not interpolated into full coverage. Mouth events are candidate mouth openings, not verified yawns. MediaPipe geometry is an experimental proxy for the original Dlib geometry. Expression coefficients remain auxiliary display cues; they are not sent to the saved model as training channels.

## Local LLM

The advisor defaults to `LLM_BASE_URL=http://127.0.0.1:11434/v1`, `LLM_MODEL=llama3.2:3b` and a four-second timeout (`LLM_TIMEOUT`). On the GX10 it uses Ollama's native local chat endpoint with a 2048-token context, a 64-token output limit and a 30-minute keep-alive. Other compatible endpoints use chat completions. The launcher selects an already-installed local Ollama model when `LLM_MODEL` is unset, preferring Llama 3.2 3B. No model download is automatic. Set `DROZY_LLM_DISABLED=1` for deterministic advice only. Failed/unavailable LLM calls do not block prediction or watch return.

The website's **Local AI advisor** panel shows the generated explanation, compute host, model and response time. It works with either valid modality; missing measurements are not manufactured. The first measured windows still build descriptive baseline data, but this explanation-only advisor does not change thresholds or fusion weights. Late replies are discarded. **Try a sample explanation → Run sample** uses explicit synthetic inputs and the actual saved video model and local LLM, separately from live sessions, prediction logs and watch alerts. The original meta-advisor remains available in source for separate experiments.

## Verify the physical round trip

1. Confirm **Phone relay** is connected, real HR is visible, and temperature shows an original reading and increasing age through null packets.
2. After at least 60 seconds, confirm a **Watch model** score only if genuine IBI, timestamped motion and sufficient coverage exist. The page lists missing inputs otherwise. After camera warm-up, confirm **Video TCN** and then **Watch + video** with both component scores.
3. Confirm the page's delivery state progresses from **queued delivery unconfirmed** to an accepted watch `command_result`. Queuing or Bluetooth send completion alone does not prove the watch played an alarm. Check screen, vibration/sound and the START acknowledgment physically.
4. Disconnect/reconnect phone and watch independently. Stale scores must become unavailable; restarting the watch must clear carried temperature and reject old-session inputs. Camera stop must not fabricate a low-risk recovery.

Existing watch alarms remain latched until acknowledgment/recovery according to the app. Video alerts clear after three distinct fresh continue windows, not merely when the camera stops. A video-only model can send its independent alarm when a watch telemetry session exists, even if watch-model sensors are missing.

Numeric prediction CSVs rotate under `realtime_backend/data/` (override `DROZY_LOG_DIRECTORY`). No images or pairing token are logged. Explicit feature-file tests run in memory and never enter the live watch return path. Do not run preparation-mode/legacy senders alongside the launcher.

## Software validation

```sh
python -B -m unittest discover -s tests -q
node --test tests/*.test.mjs
node --test phone-companion/Tests/*.test.cjs
python -B tests/relay_roundtrip.py
```

The preparation-only suite is separate and should run in a clean process: `python -B -m unittest discover -s realtime_backend/tests -q`. Synthetic tests and mocked receipts do not claim physical device success. The Garmin SDK is pinned for the iPhone build. Developer signing key contents and Apple credentials are not bundled.

## Watch selection returns immediately to DrowsyRelay

This can be normal when Garmin Connect shares one paired watch. DrowsyRelay now attaches it
automatically. Allow DrowsyRelay's Bluetooth permission and keep DrowsyAlert open on the watch.
**Watch handshake ready** confirms the watch replied. **Live telemetry enabled** plus fresh
sensor readings confirms the next stage. Connect the laptop after selecting the watch, because
leaving DrowsyRelay for Garmin Connect pauses the laptop connection. The updated status identifies
Bluetooth permission, connection, discovery, missing watch app or pending handshake separately.

The October 11 physical test confirmed watch → iPhone → laptop telemetry. A model score still
requires a complete window and genuine IBI; missing intervals are never inferred from HR.
