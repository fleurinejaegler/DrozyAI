# Live watch → iPhone Bluetooth telemetry (schema 1)

Watch code is implemented now; your future iPhone app consumes it through `ios-companion/DrowsyWatchLink`'s `onTelemetry` callback. It uses Garmin Connect IQ companion messaging, sharing the existing Bluetooth link used for phone alerts. No new phone project or placeholder model was created. See PHONE_BLUETOOTH.md for SDK, permissions, pairing, and handshake setup.

## Start streaming

Keep DrowsyAlert open in live mode. The iPhone host performs device selection/hello and calls `heartbeat` every 5 seconds. After a valid session-bound phone heartbeat or alert, the watch sends telemetry approximately once per second while the phone signal remains recent (15 seconds). Hello alone does not start streaming. Replay/DEMO never exports simulated readings as live telemetry. Leaving the watch app stops sensors and transmission.

Add this callback to your future iPhone app on the main thread:

```objc
link.onTelemetry = ^(NSDictionary *packet) {
    id hr = packet[@"heartRateBpm"];
    if ([hr isKindOfClass:[NSNumber class]]) {
        // Update the phone UI/model with [hr doubleValue].
    } else {
        // Missing: show -- and apply the model's explicit missing-data policy.
    }
    // Consume the remaining keys according to the contract below.
};
```

The callback receives Foundation dictionaries/arrays/numbers, with `NSNull` for missing values. The supplied module rejects old, duplicate, and wrong-session telemetry envelopes. Compile it in your future iOS target on a Mac; iOS compilation and actual Bluetooth throughput have not been tested on this Windows machine.

## Envelope and readings

All dictionary keys are strings. `protocol: 1`, `type: telemetry`, `schema: 1`, `source: watch_sensors`. `session` is the hello token; `sequence` increases for each submitted telemetry packet. `sentAt` is UTC epoch seconds at send, not the time each sensor measured. `watchUptimeMs` is watch monotonic milliseconds at send.

| Key | Meaning / units |
| --- | --- |
| `heartRateBpm` | Latest valid heart rate in bpm, or null |
| `heartRateAtMs` | Watch uptime when HR callback received valid data; null before first reading |
| `spo2Percent`, `spo2AtMs` | Optional oxygen saturation in %, and valid callback receipt time |
| `temperatureC`, `temperatureAtMs` | Optional Sensor.Info temperature in °C and callback receipt time; sensor source unspecified, **not labeled body/core/skin temperature** |
| `accelerometer` | Latest one-second axes batch in mg (1000 mg = 1 g); gravity retained |
| `gyroscope` | Latest one-second axes batch in deg/s |
| `batchId` | Incremented at each sensor-data callback; deduplicate repeated motion/beat batches by session + batchId |
| `batchReceivedAtMs` | Watch uptime at latest sensor-data callback |
| `beatIntervalsMs` | Optional genuine beat-to-beat intervals in ms from the latest batch (up to 8), or null |
| `hrvRmssdMs` | Optional rolling RMSSD in ms from genuine intervals only, or null |
| `hrvWindowSeconds` | 60 |

Motion objects contain `unit`, `sampleRateHz` (requested supported rate), `x`, `y`, `z`, `sensorTimestampMs`, `inputCount`, and `truncated`. Axes preserve sample order and null samples. Sensor timestamps are Garmin's millisecond timestamps; do not assume UTC or the watch uptime clock. Null timestamps remain null. Actual rates/gaps must be inferred from samples/timestamps, not silently filled. Each axes array is capped at 25 samples; inputCount/truncated report whether a longer batch was cut. Accelerometer and gyroscope are requested at up to 25 Hz, queried against the runtime supported maximum, with one-second listener batches. Optional gyroscope/beat registration failures fall back without disabling core accelerometer collection.

Scalar/motion readings older than 3 seconds by callback receipt time become null. Receipt timestamps are not proof that the underlying sensor produced a new measurement. SpO₂ and temperature may be sparse or absent; no periodic measurement is fabricated or forced. The installed fr970 definition exposes the relevant API fields, but hardware, firmware, sensor connections, and permissions determine which values arrive. An enabled API does not guarantee optical beat intervals or live temperature/SpO₂ availability.

## HRV preprocessing

RMSSD = sqrt(mean((RR[i] − RR[i−1])²)). Only genuine integer intervals of 300–2000 ms contribute. Invalid intervals or callback gaps over 3 seconds break continuity. No HR-to-RR conversion is used. The bounded history holds at most 256 beats from the last 60 seconds, using callback receipt times (multiple beats can share one time). A score requires at least 31 beats and a receipt-time span of at least 54 seconds, with no inter-callback gap over 3 seconds; otherwise null. This is a provisional coverage rule, not a clinically validated HRV measure. Raw intervals can include null/out-of-range values; the phone must apply its own explicit preprocessing and must not treat filtered gaps as adjacent beats. The latest interval array is capped at 8 entries per one-second batch; do not use it for lossless recording.

Telemetry buffers are separate from the watch feature/model buffers. Gyroscope and temperature have not been added to the existing drowsiness model feature contract. Your teammate must define their use and preprocessing before inference consumes them.

## Delivery and validation

There is one in-flight watch send, one bounded pending reply slot, and no telemetry backlog. Alarm receipts/START acknowledgment have priority. Busy transport drops telemetry opportunities; the next opportunity sends the latest snapshot. A send taking more than 5 seconds marks a link error and does not launch overlapping sends. The phone must display missing/stale connection states and tolerate gaps, repeated batch IDs, and reconnects. This is a live display/model feed, not guaranteed continuous archival recording.

Simulator tests check unavailable/stale scalars, motion truncation and missing samples, HRV from known genuine intervals, and gap/reset behavior, alongside existing alarm/replay/protocol tests. Physical-watch validation remains required: pair iPhone, enter live mode, verify received units/arrays and gaps, disconnect, restart the watch app and handshake again, and verify phone-triggered alarms still work during telemetry traffic.

API references: [Sensor listener/options](https://developer.garmin.com/connect-iq/api-docs/Toybox/Sensor.html), [gyroscope units](https://developer.garmin.com/connect-iq/api-docs/Toybox/Sensor/GyroscopeData.html), [scalar readings](https://developer.garmin.com/connect-iq/api-docs/Toybox/Sensor/Info.html), [genuine intervals](https://developer.garmin.com/connect-iq/api-docs/Toybox/Sensor/HeartRateData.html).
