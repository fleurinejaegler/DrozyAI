# DrowsyAlert: model integration and local run guide

## Project and repository

Working project: `C:\Users\eloyb\OneDrive\Eloy Bonniol\School Work\hackathon_code\DrowsyApp\DrowsyAlert`.

Shared workspace/repository: `C:\Users\eloyb\OneDrive\Eloy Bonniol\School Work\hackathon_code`.

Both folders report the shared repository from `git rev-parse --show-toplevel`.
The watch app is already inside that repository; no move or duplicate is required.
No teammate files under `hackathon_code/src` were changed. The existing model
Python files inspected there are empty placeholders; no trained feature schema or
watch-compatible model was available.

App ID remains `5222d277-26f2-4f31-8df5-77bfe31c4598`.
VS Code's `monkeyC.developerKeyPath` points to the existing
`hackathon_code/developer_key`, also used for these builds. Its contents were never
printed or copied. Root ignore rules cover that key and the app's generated bin
directory. They were already tracked, so their removal from the Git index is
staged; all local files remain on disk. No commit, push, or publication was made.
Untracking does not erase a key from existing Git history.

## Implementation

- `source/DrowsyAlertApp.mc`: initialization, 500 ms timer, one-second feature
  buckets, five-second evaluation, live/demo switching, shutdown.
- `source/DrowsyAlertView.mc`: vitals, unknown/estimated-risk colors, alert display.
- `source/DrowsyAlertDelegate.mc`: MENU, START acknowledgment, normal BACK exit.
- `source/DrowsyAlertMenuDelegate.mc`: labeled warning/high demos, return to live,
  baseline restart.
- `source/SensorCollector.mc`: live inputs and bounded streaming sums.
- `source/FeatureCollector.mc`: at most 60 one-second buckets and baseline sums.
- `source/ModelAdapter.mc`: replaceable trained-model boundary.
- `source/AlertController.mc`: shared timer-driven warning/high/recovery controller.
- `source/Config.mc`: provisional settings. `source/Tests.mc`: simulator tests.

The actual manifest build diagnostic was: Ã¢â‚¬Å“No supported languages are defined.
Language-specific resources will be ignored unless language support is added to
the manifest file.Ã¢â‚¬Â English (`eng`) is now declared. The only added permission is
`Sensor`. The launcher icon now matches fr970's 65 by 65 requirement. The device
definition specifies a round 454 by 454 AMOLED display and API level 6.0.3.
The existing minApiLevel 6.0.0 is preserved.

## Sensor collection and missing data

Verified against installed Connect IQ SDK 9.2.0 documentation and
`Devices/fr970/fr970.api.debug.xml`:

- Heart rate: `Sensor.setEnabledSensors([Sensor.SENSOR_HEARTRATE])` and
  `Sensor.enableSensorEvents`, nominally 1 Hz, bpm. One new event per feature
  bucket at most; previous readings are not repeatedly inserted into the window.
- Accelerometer: `Sensor.registerSensorDataListener`, period 1 second, requested
  25 Hz capped by `getMaxSampleRateForSensorType(:accelerometer)`. Request axis
  timestamps; reject duplicate/out-of-order timestamps when provided. Axis values
  are milligravity units (mg), where 1000 mg = 1 g.
- Optional genuine RR intervals: `SensorData.heartRateData.heartBeatIntervals`,
  milliseconds. If registration with intervals fails, retry accelerometer alone.
  The API's presence does not guarantee the wrist sensor supplies RR intervals;
  a suitable paired sensor may be needed. HR is never converted into RR/HRV.
- Optional SpO2: enable `SENSOR_PULSE_OXIMETRY` separately and read
  `Sensor.Info.oxygenSaturation` (%). Failures fall back to HR alone. Missing
  values show `--`; no SpO2 value is inferred from other signals.

All values have app monotonic receipt timestamps (`System.getTimer()`, ms).
Accelerometer sample timestamps are used for order/deduplication; feature bucket
time is receipt time, not an assumed wall-clock measurement time. HR/SpO2 APIs
used here do not supply a separate measurement-age timestamp. Ã¢â‚¬Å“FreshÃ¢â‚¬Â therefore
means a recent valid callback, not proof of a newly acquired optical measurement.
This limitation must be considered when defining the final model contract.

Core callbacks expire after 3 seconds. Null HR and invalid/nonpositive values are
cleared immediately. SpO2 must be >0 and <=100. Missing samples are never zero
filled, interpolated, or carried into subsequent feature buckets. Display values
can remain visible for the three-second freshness limit. Optional missing inputs
do not block the core display.

## Provisional feature schema (candidate-v1)

This named dictionary is not a trained feature vector. Dictionary enumeration
order must not be used as model feature order. A future adapter must explicitly
map the following provisional order to the teammate's exact schema.

| Order | Dictionary key | Units | Formula |
| --- | --- | --- | --- |
| 1 | hrMean | bpm | sum(HR) / N |
| 2 | hrStd | bpm | population SD: sqrt(mean(HR squared) - hrMean squared) |
| 3 | hrSlope | bpm/s | least-squares slope against actual bucket elapsed seconds |
| 4 | hrBaselineDelta | bpm | hrMean minus frozen personal baseline HR |
| 5 | accelMean | mg | mean of sqrt(x squared + y squared + z squared) |
| 6 | accelStd | mg | population SD of acceleration magnitudes |
| 7 | stillFraction | 0Ã¢â‚¬â€œ1 fraction | proportion of accepted magnitudes with abs(magnitude - 1000 mg) < 50 mg |
| 8 | rmssd | ms or null | sqrt(mean of squared differences between consecutive valid RR intervals) |

Metadata: `complete` (Boolean), `timestamp` (monotonic ms), `schema`
(`candidate-v1`), `hrCoverage`, `accelCoverage`.

Acceleration retains gravity. Subtracting 1000 mg only defines the provisional
stillness band; it is not vector gravity removal or a validated inactivity
detector. A constant tilted acceleration vector also counts as still.
Accelerometer statistics weight accepted samples, not means of batch means.
The 60-second window uses at most 60 buckets; no unbounded raw arrays are stored.

Minimum data coverage: a window must span at least 59 seconds between first and
last bucket, contain at least 54 distinct valid HR buckets and 54 valid
accelerometer buckets, and have fresh core inputs and a completed baseline.
An accelerometer bucket needs >=80% of the negotiated samples/second to
contribute. Other buckets are excluded, and actual coverage is reported.
The denominator for coverage is always the configured 60-second window,
including gaps. Change these defaults only with corresponding model validation.

Baseline: the first five-minute attempt with >=90% paired valid one-second
buckets (>=270 of 300). Freeze mean HR over accepted paired buckets. If coverage
is insufficient at five minutes, restart that attempt automatically. MENU's
Restart baseline clears the baseline and feature window, without erasing an
active real warning. Baseline is session-local and is not stored across launches.

RMSSD: accept only received RR intervals in the provisional 300Ã¢â‚¬â€œ2000 ms range;
invalid intervals and absent RR batches break adjacency. A receipt gap >3 seconds
also breaks adjacency. Require at least 20 valid adjacent differences in the
window and a fresh RR callback, otherwise return null. Each difference is assigned
to the bucket containing its later interval, so its predecessor may be just
outside the window. This is basic validity filtering, not ectopic-beat correction
or clinical HRV preprocessing. The final artifact must specify its own policy.
Floating-point negative variance from rounding is clamped to zero; missing input
values are never replaced by zero.

## ModelAdapter contract

Location: `source/ModelAdapter.mc`.

```text
evaluate(features: Dictionary) -> Dictionary {
    :riskScore: Number/Float/Double in [0,1], or null,
    :status: :ready | :model_not_connected | :insufficient_data,
    :timestamp: System.getTimer() at evaluation (monotonic milliseconds),
    :modelVersion: String identifier
}
```

The current adapter always returns `:model_not_connected`, a null score, and
`not-connected` version. The app additionally gates predictions on feature
coverage/baseline and current freshness. Invalid, duplicate, out-of-range,
non-numeric, future, or >10-second-old ready results cannot become low estimated
risk. The UI shows 0Ã¢â‚¬â€œ100 only for an accepted result. Missing sensor data during a
real alert hides the score and retains the warning.

No heuristic or invented model coefficients are included. Python/scikit-learn
pickle and Python GRU code cannot execute directly in Monkey C. A compact,
verified linear/tree model could be exported to explicit Monkey C parameters.
A larger model may require an explicitly designed phone/server transport plus
a freshness and failure contract; no such connection or permissions are added
here. Facial/video/fusion models are incompatible with the watch-only candidate
inputs unless retrained or split into a documented sensor-only model.

Required teammate handoff:

1. Exact feature names, ordered vector, required/optional inputs, units, window,
   hop, timestamp conventions, coverage and sensor rates.
2. Exact gravity treatment, normalizers/scalers, baseline rules, RR filtering and
   all preprocessing operations with constants.
3. Missing/stale/optional data policy, including whether RMSSD or SpO2 is required.
4. Exported trained artifact/parameters, runtime size/compute budget, version and
   a license permitting integration. Do not commit signing keys with artifacts.
5. Meaning/calibration of the score and validated thresholds, hysteresis,
   acknowledgment/reminder timing, and performance limitations.
6. Reference raw inputs, intermediate features, and expected outputs, including
   gaps, missing optional sensors, baseline restart and stale-result cases.

## Demonstration and alert behavior

MENU -> Test warning injects 0.75 immediately, then every five seconds. It takes
three consecutive valid evaluations: approximately 10 seconds from selection.
MENU -> Test high (DEMO) injects 0.95 and alerts immediately. These use the same
`AlertController.evaluate` as the real adapter, bypassing sensor/model readiness
only in this separate mode. Ã¢â‚¬Å“DEMO - simulated riskÃ¢â‚¬Â remains prominent.
Return to live clears demonstration state and restores live vitals and unknown
model risk. Selecting Return to live while already live preserves real warnings.

Demonstration defaults in Config (not validated detection thresholds):

- Warning >=0.70 for three consecutive evaluations.
- High >=0.90 immediately; a warning escalates immediately.
- Recovery <0.55 for three consecutive evaluations. Values between recovery and
  warning preserve elevated state.
- Invalid/stale/duplicate results reset consecutive counters and retain any
  elevated state. Required live input loss does the same.
- Red/dark display alternates every 500 ms (one cycle/second), for 10 seconds,
  followed by a static elevated status.
- `Attention.playTone(Attention.TONE_ALARM)` and one
  `Attention.VibeProfile(80, 300)` (80%, 300 ms), repeated at most once every
  five seconds, for at most 30 seconds. API checks and independent exception
  handling protect unsupported/disabled outputs. No physical flashlight API.
- START acknowledges an elevated alert, cancels scheduled flashing and subsequent
  tone/vibration calls, and retains score/elevated status. A short pattern already
  dispatched completes; these Attention APIs expose no cancellation method.
  The next fresh high result after the 60-second acknowledgment cooldown can
  start a reminder. Invalid or missing results never trigger a reminder.
- BACK on the main screen exits normally; BACK in MENU returns to monitoring.
  Shutdown stops the sole timer, unregisters both listeners, and disables sensors.

## Build and run (Windows PowerShell)

Open a PowerShell terminal in the existing DrowsyAlert folder:

```powershell
Set-Location 'C:\Users\eloyb\OneDrive\Eloy Bonniol\School Work\hackathon_code\DrowsyApp\DrowsyAlert'
$sdkPath = (Get-Content "$env:APPDATA\Garmin\ConnectIQ\current-sdk.cfg" -Raw).Trim()
& "$sdkPath\bin\monkeyc.bat" -f monkey.jungle -d fr970 -o bin\DrowsyAlert-sim.prg -y ..\..\developer_key -w
& "$sdkPath\bin\connectiq.bat"
& "$sdkPath\bin\monkeydo.bat" bin\DrowsyAlert-sim.prg fr970
```

Alternatively use VS Code Run -> Run Without Debugging (Ctrl+F5), choose Monkey C and fr970.
For simulator MENU, uppercase M (Shift+M) was verified; Enter selects/acknowledges,
arrow keys move through the native menu, and Escape backs out. On the watch hold
UP/MENU to open the menu.

Physical-device release build:

```powershell
& "$sdkPath\bin\monkeyc.bat" -f monkey.jungle -d fr970 -o bin\DrowsyAlert.prg -y ..\..\developer_key -w -r
```

Connect the Forerunner 970 by USB, open its storage in File Explorer, copy only
`bin/DrowsyAlert.prg` into `GARMIN/APPS`, safely disconnect, then launch
DrowsyAlert from the watch's activity/app list. Do not copy the signing key or
debug/test executables. See Garmin's official
[Your First App / device installation](https://developer.garmin.com/connect-iq/connect-iq-basics/your-first-app/).

Simulator tests (start the simulator first):

```powershell
& "$sdkPath\bin\monkeyc.bat" -f monkey.jungle -d fr970 -o bin\DrowsyAlert-tests.prg -y ..\..\developer_key -w -t
& "$sdkPath\bin\monkeydo.bat" bin\DrowsyAlert-tests.prg fr970 /t
```

## Validation and physical-watch checklist

Simulator and release builds succeed with SDK 9.2.0 for fr970, with no compiler
warnings. Five simulator tests pass, including the synthetic tracking replay: threshold/escalation/recovery/acknowledgment/flash phases,
invalid/stale/duplicate results, baseline/feature values/window bounds,
and HR slope with insufficient coverage. Native simulator layout was inspected
for unknown values, warning/high states, acknowledgment, and round-screen margins;
button hints were shortened and separated from alert text. Both manual demo menu
actions were exercised, with risks 75 and 95 and elevated state retained on START.
Red and dark alert frames and the shortened acknowledgment text were inspected.

Physical sensor acquisition, actual speaker audibility and motor output still
require a watch. The simulator's empty sensor stream correctly shows `--` and
Sensor data missing; it must not be interpreted as a failed model or zero inputs.

On the physical watch, test while stationary:

1. Launch, check HR and movement when supplied; optional SpO2 may remain `--`.
   Wait for the five-minute baseline if validating collection.
2. Hold UP/MENU -> Test warning. Confirm DEMO and risk 75; after approximately
   10 seconds confirm the alert, red/dark flash, alarm and short vibration.
3. Confirm flashing becomes static after 10 seconds of the alert and output
   repetitions cease after 30 seconds. START stops scheduled outputs sooner
   while preserving risk/elevated text.
4. Test high risk: immediate high alert/risk 95. START acknowledges. If left
   in high demo mode, a reminder is permitted after the 60-second cooldown.
5. Return to live: risk becomes unknown until an actual model is connected.
   Restart baseline and ensure it collects again. BACK exits without further
   scheduled alert outputs.
6. Validate core sensor loss/freshness and optional-sensor absence. The automated
   controller tests cover warning retention on invalid data; live high-risk
   sensor-loss testing requires a connected validated model or a test harness.

## API references

The installed SDK documentation is the compile-time source of truth for this
device; online references explain the same APIs:

- [Sensor registration](https://developer.garmin.com/connect-iq/api-docs/Toybox/Sensor.html)
- [SensorData and genuine intervals](https://developer.garmin.com/connect-iq/api-docs/Toybox/Sensor/SensorData.html)
- [Accelerometer units and timestamps](https://developer.garmin.com/connect-iq/api-docs/Toybox/Sensor/AccelerometerData.html)
- [Sensor.Info / SpO2](https://developer.garmin.com/connect-iq/api-docs/Toybox/Sensor/Info.html)
- [Attention tones and vibration](https://developer.garmin.com/connect-iq/api-docs/Toybox/Attention.html)

## TEST DATA replay and future score delivery

`source/TEST_DATA_Replay.mc` is clearly labeled synthetic TEST DATA. These are
Garmin-style metrics, not recordings collected from a Garmin or model predictions.
Columns are HR (bpm), acceleration magnitude (mg, including gravity), optional
SpO2 (%), and assumed model score (0..1). No raw accelerometer samples, beat
intervals, or feature vectors are invented. Each row lasts five seconds; held
fixture vitals are published at the 500 ms UI timer rate. The 90-second sequence
loops: low 0-20 s, rising 20-40 s (controller warning at 30 s), immediate high
40-60 s, missing core data/result 60-70 s (warning retained), recovery 70-90 s
(controller clears elevated state at 80 s after three valid low results).

Start with MENU -> Replay TEST DATA. The display is explicitly labeled TEST.
START acknowledges alerts while playback continues. Return to live stops replay,
restarts actual Garmin listeners with empty readings, and restarts the real baseline.
Replay never mixes fixture vitals into real sensor collection or baseline features.
The separate Test warning/high entries continue to use actual live sensor readings
with an injected score. Normal app startup always uses actual Garmin sensors.

For a watch-compatible model, implement `ModelAdapter.evaluate(features)` with
its exact validated preprocessing. `ModelAdapter.resultFromScore(score, timestamp,
version)` builds the common envelope; thresholds and display need no changes.

For an off-watch model, a future receiver can call
`getApp().acceptModelResult(payload)` using the same Symbol-keyed Dictionary:
`{:riskScore=>0.78, :status=>:ready, :timestamp=>watchMonotonicMs,
:modelVersion=>"your-model-version"}`. The score must be 0..1 (not 0..100).
Deliver distinct fresh results at the configured five-second interval. Missing
scores use null and :insufficient_data. Timestamp means inference/capture time in
this watch's System.getTimer() clock; remote epoch time needs synchronization and
age conversion, never simply retimestamp old predictions as fresh.

The hook validates results through the shared AlertController and requires fresh
actual core sensor data. Once invoked it prevents the unconnected local adapter
from overwriting received results; sensor loss and result timeout still clear the
score and retain an active warning. Return to live leaves this receiver mode.
No Bluetooth/phone/HTTP transport is implemented or selected here. A Python model
cannot send directly to this hook without a watch-compatible receiver/companion.
The teammate must agree on sensor export, transport, timestamps, inference window,
feature schema and missing-data rules before remote integration is complete.

VS Code launch: open a .mc file in this project, use Run -> Run Without Debugging
(Ctrl+F5), select Monkey C and fr970 if prompted. Simulator: focus window, Shift+M opens
MENU, arrows select, Enter starts/acknowledges. The previous guide's command-palette
name "Monkey C: Run Without Debugging" was incorrect; use VS Code's Run command.
