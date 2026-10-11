# Garmin 970 website sensor receiver (Windows or Mac)

This receiver implements the sensor-streaming brief in the existing DrowsyAlert app.
The route is **Forerunner 970 -> existing DrowsyAlert -> Garmin Connect Mobile HTTPS bridge -> public HTTPS tunnel -> MacBook FastAPI -> terminal and CSV**.
It needs the normal Garmin Connect phone app, not the custom DrowsyRelay iOS app or Xcode.
The existing custom iPhone companion remains available for the separate camera/model/alarm relay.
No model training, camera processing, feature fusion, or changes to `src/data/loader.py` are included.
Existing watch alarm and phone-alert behavior is preserved.

## 1. Start the receiver on the Mac

Copy or clone this repository to the Mac. Open Terminal in the repository root
(the folder containing `server`, `src`, and `DrowsyApp`). Use Python 3.11 or newer:

```sh
python3 -m venv server/.venv
source server/.venv/bin/activate
python -m pip install -r server/requirements.txt
python -m server
```

Keep this terminal running. The receiver listens on `127.0.0.1:8000` and prints a
temporary **watch API token**. The generated token changes whenever the server
restarts. Copy it into the watch as described below. To keep a token across
restarts, supply `GARMIN_API_TOKEN` through your terminal environment before
starting; it must be at least 12 characters. No credentials are stored in source.

In another terminal:

```sh
curl http://127.0.0.1:8000/health
```

Expect `{"status":"ok","service":"garmin_receiver","schema_version":1}`.
Run one receiver process/worker per data directory. A process lock prevents
another instance from rewriting the same CSV exports.

On Windows, the equivalent development commands are:

```powershell
uv venv server/.venv
uv pip install --python server/.venv/Scripts/python.exe -r server/requirements.txt
& server/.venv/Scripts/python.exe -m server
```

## 2. Give the watch a public HTTPS endpoint

The watch endpoint must not be `localhost` or a private LAN address. Garmin's
[asynchronous makeWebRequest API](https://developer.garmin.com/connect-iq/api-docs/Toybox/Communications.html#makeWebRequest-instance_function)
supports a paired phone over Bluetooth or supported Wi-Fi. The documented phone
bridge is the primary route here; direct watch Wi-Fi has not been tested.

Install Cloudflare's `cloudflared` following its
[installation documentation](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/).
For Macs with Homebrew, `brew install cloudflared` installs the CLI. Then, in a
second terminal, start a [Quick Tunnel](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/):

```sh
cloudflared tunnel --url http://127.0.0.1:8000
```

Cloudflare prints a temporary URL such as `https://YOUR-NAME.trycloudflare.com`.
Verify it from your phone browser or a third terminal:

```sh
curl https://YOUR-NAME.trycloudflare.com/health
```

The **full watch upload URL** is:

```text
https://YOUR-NAME.trycloudflare.com/garmin/data
```

Keep the server, tunnel, and Mac awake. Restarting a Quick Tunnel can change its
URL; update the watch afterward. The token authenticates uploads and status
requests; `/health` exposes liveness only. TLS terminates at the tunnel provider,
then forwards to the loopback receiver. This is a hackathon setup, not a clinical
or production data service.

## 3. Install the updated watch app and configure it

The app ID is unchanged: `5222d277-26f2-4f31-8df5-77bfe31c4598`. The target is
`fr970`, minimum API 6.0.0. Copy `DrowsyApp/DrowsyAlert/bin/DrowsyAlert.prg`
directly into the watch's `GARMIN/APPS`, replace the old file, finish copying,
then unplug and reopen DrowsyAlert.

1. Pair the watch to the phone in **Garmin Connect**, enable Bluetooth, and let
   Garmin Connect run with network access. During initial validation keep it open.
2. Remove/unpair **external heart-rate and temperature sensors** in the watch's
   sensor settings. This uploader conservatively blocks HR/IBI or temperature if
   an external sensor of that type is registered, even if currently inactive.
   It does not substitute chest straps or tempe sensors.
3. Open DrowsyAlert and choose **Return to live**. Demo and replay uploads are blocked.
4. The watch now uses build-time website configuration and starts uploads automatically.
   There are no URL, token, upload toggle, or cadence controls on the watch.
5. Until the partner enables a real endpoint, the main screen and **Sensors / website**
   show `WEBSITE: COMING SOON`. No placeholder requests or upload buffering occur.
6. Follow [the partner handoff](PARTNER_HANDOFF.md) to set the endpoint and receiver
   token, rebuild, and install. Older stored watch settings are ignored.
7. Once enabled, **Sensors / website** shows the last upload, sensor availability,
   errors and dropped samples. Successful acknowledgments show `COMPUTER: CONNECTED`.

The default upload cadence is five seconds. Each app launch starts a new session.
The initial setup instructions above describe starting the receiver and obtaining
its endpoint/token; these values now go in `WebsiteConfig.mc`, not a watch text picker.
For preconfigured builds, use a stable endpoint and set `GARMIN_API_TOKEN` before
starting the receiver so restarts do not change the credential.

## 4. Verify live data on the Mac

The receiver prints summaries of **received** measurements, counts, missing
sensors, and RMSSD readiness. No dummy classifier or fixture feed runs in live
mode. Expect missing values until sensors supply readings; optical IBI may never
arrive. HR is the first milestone; missing IBI/temperature does not block it.

Files are written beneath `server/data/` by default:

- `garmin_heart_rate.csv`: BPM and missing observations.
- `garmin_accelerometer.csv`: original X/Y/Z in **mg**, raw sensor ms, callback
  timing, array order, rate, and rate-based offsets.
- `garmin_ibi.csv`: original intervals in **ms**, order, validity and rejection reason.
- `garmin_temperature.csv`: original Celsius reading, source, type, timing.
- `garmin_hrv.csv`: server-derived RMSSD, counts, window, span and status.
- `garmin_batches.csv`: availability and cumulative dropped counts for every batch.
- `garmin_batches.sqlite3`: durable raw batch journal and deduplication keys.

Missing numeric values are empty CSV cells, never zero. Temperature is labeled
`unknown` unless a source explicitly establishes its type. History samples may
be minutes old; their original epoch timestamp is retained. The status screen
marks temperature unavailable if the last observation is more than five minutes
old. A received temperature reading is not automatically skin/body temperature.

The SQLite journal preserves full accepted JSON and reception times. CSVs are
rebuilt from it at startup to recover interrupted exports. Under normal operation
CSV writes and duplicate handling are serialized, and failed writes are rolled
back before acknowledgment. A retry of an accepted `(session, batch_id)` returns
`duplicate` without extra rows. Reusing that ID with changed measurements or
sending an out-of-order batch returns HTTP 409.

Use another terminal to inspect receiver status:

```sh
read -r -s GARMIN_API_TOKEN
# Paste the receiver token and press Enter; the input is hidden.
curl -H "Authorization: Bearer $GARMIN_API_TOKEN" http://127.0.0.1:8000/garmin/status
```

Status becomes `stale` after 15 seconds without an accepted upload. This is
transport freshness, not a sensor or health assessment.

## Data and timestamp contract

See [SCHEMA.md](SCHEMA.md) for the compact request and acknowledgment format.
The watch preserves each sensor callback's `System.getTimer()` millisecond time
and the original accelerometer timestamp array. A session-start UTC seconds/
uptime anchor maps callback time to an approximate watch epoch time. The anchor
has only second precision, and watch/Mac clock offset and drift remain unknown.

Accelerometer sensor timestamp origins are not silently equated with callback
uptime. CSV stores both. `sample_offset_seconds` is a **rate-derived estimate**
relative to the end of the callback block, not a measured UTC sample time.
Individual IBI beat timestamps are not provided by the API, so all intervals in
one callback retain that callback time plus their original order. Reception time
is recorded independently and includes network latency. Do not treat reception
minus watch time as a measured clock correction.

`src/data/loader.py` loads UL-DD dataset sessions into session-relative per-second
rows, aggregates axes with means/variances, and preserves missing measurements as
NaN. It is unchanged. The new CSVs keep raw readings for a future explicit
alignment/resampling step. Garmin ACC rate/units and onboard temperature must
not be assumed interchangeable with the training dataset's 32 Hz ACC and TEMP.
No 5-second feature fusion or resampling is performed in this task.

## RMSSD on Python

The receiver uses the square root of the mean squared difference between
consecutive **valid original intervals**. It never derives IBI from BPM or uses
the watch's legacy `hrvRmssdMs` telemetry field.

Default rolling window: 60 seconds; at least **30 valid intervals spanning 30
seconds** in the current continuous segment are required. RMSSD remains missing
until then. API intervals below 300 or above 2000 ms, or null, remain in raw CSV
but break the derived segment. This is a basic artifact rule, not a validated
physiological filter. No interpolation or ectopic-beat correction is applied.
An empty IBI callback, callback gap over three seconds, sequence gap, or increase
in dropped IBI count also breaks continuity. No differences span those gaps.
No fresh intervals within three seconds means HRV is unavailable. Exact beat
timing is unknown, so rolling-window membership uses callback timestamps.

Optional environment settings before launching:

```sh
export GARMIN_DATA_DIR="server/data"
export GARMIN_HRV_WINDOW_SECONDS="60"
export GARMIN_HRV_MIN_INTERVALS="30"
export GARMIN_HRV_MIN_SPAN_SECONDS="30"
```

## Batching, losses, and retries

The watch requests 25 Hz ACC (or the lower maximum reported by the device) and
one-second callbacks. HR is event driven; its actual observed rate is not promised.
Temperature is polled every five seconds at the API's actual history rate and
each history observation is queued only once. IBI uses only API-returned data.

At most ten 25-sample ACC callback blocks (250 samples), 32 HR observations,
32 IBI callbacks of up to eight intervals, and 32 temperature observations are
buffered, plus one frozen pending request. Each default request takes at most
five callback blocks/observations from each queue (125 ACC samples); one-second
mode takes one. Buffers are independent of the legacy phone telemetry buffers.
The oldest queued records are removed on overflow, with per-sensor counters.
An unusually large callback is capped at 25 ACC samples/eight IBI values and
the excess is counted. Counters are displayed/logged; no large data loss is hidden.

Requests have a 30-second watchdog. After an error the same frozen batch retries
at 5, 10, 20, 40, then at most 60 seconds, without changing IDs or timestamps.
Cancellation invalidates stale callbacks. Pending batches expire after two
minutes and every expired observation is added to the dropped counts. New raw
collection continues within the limits during outages. Leaving live mode or
stopping uploads discards queued data with counts; it never exports replay/demo
readings. The server accepts at most 64 KiB per request, returns a small JSON ACK,
and validates array lengths, numeric values, source labels, ordering and clocks.
Watch buffers are in memory: closing/restarting the app loses unsent observations
and starts fresh session counters. It is not an on-watch persistent recorder.

Garmin documents `BLE_REQUEST_TOO_LARGE` (-102),
`NETWORK_RESPONSE_TOO_LARGE` (-402), and `NETWORK_RESPONSE_OUT_OF_MEMORY` (-403).
The public API reference does not provide a definitive FR970 request byte limit.
Small bounded chunks and the 1s option are used instead of claiming an unverified
limit. Inspect actual traffic and dropped counts on hardware. This transport is
near-real-time and not a lossless recorder during long outages.

## Build and automated validation

Windows, from `DrowsyApp/DrowsyAlert`:

```powershell
$sdkPath = (Get-Content "$env:APPDATA\Garmin\ConnectIQ\current-sdk.cfg").Trim()
& "$sdkPath\bin\monkeyc.bat" -f monkey.jungle -d fr970 -o bin\DrowsyAlert.prg -y ..\..\developer_key -w -r
& "$sdkPath\bin\monkeyc.bat" -f monkey.jungle -d fr970 -o bin\DrowsyAlert-tests.prg -y ..\..\developer_key -w -t
& "$sdkPath\bin\monkeydo.bat" bin\DrowsyAlert-tests.prg fr970 /t
```

Alternatively open that app folder in VS Code, use **Monkey C: Build for Device**,
select Forerunner 970, and save `bin/DrowsyAlert.prg`. Use your existing signing
key; do not copy it to the watch or commit it. On a Mac the SDK's `bin/monkeyc`
and `bin/monkeydo` take the same arguments with POSIX paths.

From the repository root, in the receiver's activated environment:

```sh
python -m pip install -r server/requirements-test.txt
python -m unittest server.test_receiver server.test_live_http -v
```

These tests use explicitly offline fixtures in temporary directories. They cover
local HTTP, authentication, malformed payloads, original values/timestamps/CSVs,
known RMSSD, invalid/missing/gap behavior, duplicate/concurrent requests,
storage failure rollback, process exclusion, and restart recovery. Tests do not
send fixture readings to a watch or the live data directory.

See [COMPATIBILITY.md](COMPATIBILITY.md) for documentation versus compilation,
simulator, server and physical validation status.

## Physical test sequence and troubleshooting

1. Start server and tunnel; verify `/health` locally and from the phone.
2. Install the new PRG, enter endpoint/token, remove external sensors, select
   live mode and start uploads. Keep watch app/Connect open and wear the watch.
3. Confirm actual HR appears in the **Mac terminal** and `garmin_heart_rate.csv`.
   Inspect missing markers rather than expecting a fabricated BPM.
4. Move the watch; confirm X/Y/Z change in `garmin_accelerometer.csv`. Measure
   ACC timestamp deltas where provided (25 Hz target is about 40 ms). Check the
   sensor timestamp origin and six static watch orientations before assigning
   anatomical/world axis directions. Raw native axes are unchanged by the code.
5. With no external HR sensor paired, check if original IBI intervals arrive.
   If they do not, leave IBI/RMSSD unavailable. If they do, inspect variability,
   units, cadence and artifacts; an API array alone is not clinical validation
   of optical beat-to-beat accuracy. Wait for the documented minimum HRV coverage.
6. Check temperature/history timestamps and source. Do not relabel the measured
   sensor temperature as skin temperature. If unavailable, keep it missing.
7. Stop the tunnel. Observe upload failure/backoff, disconnected/stale status,
   bounded queues and dropped counts. Restart it, update the URL if it changes,
   and verify recovery. Retries must not duplicate CSV rows.
8. Acknowledge a warning/high alarm with START, check sound/vibration/display,
   and verify sensor uploading does not break the existing alarm behavior.
9. Select replay: no replay samples may enter the Mac CSVs. Return to live and
   confirm fresh watch measurements resume. Restart the watch; its new session
   must be distinct. Finally background/close the watch app and observe stale
   status. Continuous background acquisition is not implemented.

Errors: **401** means wrong/expired token; **404** usually means missing
`/garmin/data`; **422** means incompatible data/schema; **413/-102** means reduce
batch size with the 1s setting; **409** means conflicting sequence/session data;
**503** means disk/journal storage failed. Negative Garmin codes may indicate
phone connectivity, TLS, request size or response memory. A tunnel health check
does not prove Bluetooth works. `external_blocked` means unpair the corresponding
external sensor; `unavailable` means the watch has supplied no fresh reading.

The generated code has been tested locally, not on a Mac or through your physical
watch/phone/tunnel. Your earlier successful on-watch alarm test does not establish
that the newly added sensor-to-Mac path or IBI/temperature works on hardware.
