# Garmin sensor/transport verification

Inspected 2026-10-11: existing app `DrowsyApp/DrowsyAlert`, entry point
`DrowsyAlertApp`, existing views/alarms, `SensorCollector`, `TelemetryCollector`,
`PhoneAlertBridge`, manifest/jungle, `src/data/loader.py`, root/web Python
requirements, and existing `phone-companion`. Installed SDK:
**Connect IQ 9.2.0, build 2026-06-09-92a1605b2**. Manifest target: **fr970**,
minimum API **6.0.0**, watch app with existing UUID. Added `SensorHistory` permission
alongside existing `Sensor` and `Communications`.

| Feature | Official public API / minimum API | FR970 docs | Requested rate / units | Permissions | Implementation and validation |
| --- | --- | --- | --- | --- | --- |
| HR | `Sensor.Info.heartRate`, `setEnabledSensors`, `enableSensorEvents`; 1.0.0 | Supported sensor interfaces; optical readings must be tested | Event callbacks, roughly 1 Hz target; BPM | Sensor | Raw callback observations queued; compiles; buffer/server fixture tests pass; physical provenance/cadence/readings unverified |
| ACC X/Y/Z | `registerSensorDataListener` / `AccelerometerData`; 2.3.0; `getMaxSampleRateForSensorType` 3.4.5; timestamp array 5.1.1 | FR970 listed | Request min(25 Hz, reported device maximum), one-second callbacks; mg | Sensor | Native raw axes and API timestamps preserved; compiles; null/buffer tests pass; physical 25 Hz/timestamp origin/axis orientation unverified |
| Raw IBI | `HeartRateData.heartBeatIntervals`; 3.0.0 and listener interval option | FR970 listed for class; **no guarantee that onboard optical IBI is supplied** | Irregular beat intervals; ms; callback time/order only | Sensor | Preserves raw intervals or missing status; external HR sensors blocked; compile/tests pass; real optical IBI unavailable until demonstrated on hardware |
| Temperature | `Sensor.Info.temperature` 1.0.0; `SensorHistory.getTemperatureHistory` 2.1.0 | FR970 listed for history method | API-driven history, poll every 5s; Celsius | Sensor, SensorHistory | Prefer history original timestamps; info fallback only without registered external temp sensor; source/type explicit; compile/server tests pass; actual onboard reading/cadence unverified |
| RMSSD | Python original consecutive IBI values; no model | Depends on real usable IBI | 60s rolling window, 30 valid intervals/30s span minimum; ms | None on Python | Known sequence, null/invalid/gap/drop/stale tests pass; no physical or physiological validation |
| HTTPS upload | `Communications.makeWebRequest` 1.3.0; cancellation 1.2.0 | General supported watch/phone or Wi-Fi API | 5s target (1s option), asynchronous, compact ACK | Communications | Compiles; simulator state-machine and localhost HTTP tests pass; actual Garmin Connect/phone/tunnel path unverified |

## Evidence levels

- **Documentation:** reviewed the official APIs linked below and installed SDK reference.
- **Compilation:** successful FR970 release and test builds. This proves API/type compatibility only.
- **Simulator:** deterministic buffer/drop/retry/timeout/stale-callback/test-mode
  checks plus existing threshold/alarm/replay/phone protocol tests. These use
  offline fixtures; they do not establish onboard sensor availability.
- **Receiver:** schema/auth/CSV/timestamp/RMSSD/concurrent duplicate/restart/disk
  failure/process-lock tests plus actual localhost HTTP serving. This proves
  receiver behavior, not Bluetooth or physical watch acquisition.
- **Physical hardware:** the user reported the earlier alarm app works on the
  watch. No newly added uploader, HR source, ACC rate, IBI, temperature, phone
  bridge, public tunnel, or Mac execution has been physically verified here.

No external strap/tempe fallback is introduced. Registered external HR or
temperature sensors conservatively block their groups. If source enumeration
fails, those groups also remain blocked. Remove paired external sensors for the
onboard-only validation. ACC is acquired via the native onboard motion listener.

The reference gives mg units and timestamp milliseconds but does not establish
the relationship between that timestamp origin and application uptime for this
implementation. It does not establish anatomical/world X/Y/Z orientation on the
FR970. Original arrays/order are retained; six-orientation physical checks and
callback-clock comparison are required before making those claims.

The temperature API alone does not prove skin/ambient type. History documentation
describes onboard sensors; polling it does not turn an old history sample into a
new real-time measurement. All exposed readings retain source/timing and are
labeled `unknown` type. No weather, phone, Mac, or external temperature source
enters this receiver path.

## Primary references

- [Sensor and listener configuration](https://developer.garmin.com/connect-iq/api-docs/Toybox/Sensor.html)
- [Sensor.Info BPM and Celsius units](https://developer.garmin.com/connect-iq/api-docs/Toybox/Sensor/Info.html)
- [AccelerometerData units, arrays and timestamp API](https://developer.garmin.com/connect-iq/api-docs/Toybox/Sensor/AccelerometerData.html)
- [HeartRateData interval units and device list](https://developer.garmin.com/connect-iq/api-docs/Toybox/Sensor/HeartRateData.html)
- [Onboard sensor history and temperature history](https://developer.garmin.com/connect-iq/api-docs/Toybox/SensorHistory.html)
- [History sample timestamps](https://developer.garmin.com/connect-iq/api-docs/Toybox/SensorHistory/SensorSample.html)
- [Asynchronous network APIs, supported transports and error constants](https://developer.garmin.com/connect-iq/api-docs/Toybox/Communications.html)
- [Cloudflare Quick Tunnel setup](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
