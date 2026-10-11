# iPhone camera model → DrowsyAlert

A complete companion project now lives at [phone-companion](../../phone-companion/README.md). It also relays laptop Python model scores and camera commands through a local service; use that guide for the current end-to-end setup.

Watch-to-phone live sensor streaming is implemented separately; see [TELEMETRY.md](TELEMETRY.md) for the schema and `onTelemetry` callback. The same companion module handles both directions.

The watch receives companion-app messages through Garmin Connect IQ Bluetooth messaging. No Wi-Fi, web server, or raw video transfer is required. Garmin Connect provides device selection/authorization; the iOS Connect IQ SDK handles the Bluetooth connection. This implementation requires DrowsyAlert and the iPhone camera app to be running in the foreground. Background delivery has not been implemented or validated.

## Included code

- `source/PhoneAlertBridge.mc`: listener, validation, replies, independent phone alert state.
- `ios-companion/DrowsyWatchLink.h` and `.m`: ARC Objective-C module for your existing iPhone camera/model app. This is not a standalone iOS application.
- App UUID is preserved: `5222d277-26f2-4f31-8df5-77bfe31c4598`.

Phone warnings/high alerts enter the same alarm-controller implementation as watch alerts. They work even when watch sensors or the watch model are unavailable. They do not overwrite the watch model's risk score: the screen labels it WATCH RISK SCORE and displays PHONE CAMERA ALERT separately. Phone warning decisions trigger immediately; the camera model must apply its own validated thresholds. A warning cannot downgrade an active high alert.

## Integrate on a Mac with Xcode

1. Add Garmin's [official iOS companion SDK](https://github.com/garmin/connectiq-companion-app-sdk-ios) to the camera app using its documented Swift Package Manager setup. Add both supplied Objective-C files to the app target with ARC enabled. Swift apps can expose the header through their bridging header.
2. Follow Garmin's [SDK setup documentation](https://github.com/garmin/connectiq-companion-app-sdk-ios/blob/main/documentation/ConnectIQ_iOS_SDK.html): configure `-ObjC`, a unique callback URL scheme (for example `drowsyalert-camera`), `CFBundleDisplayName`, `LSApplicationQueriesSchemes` containing `gcm-ciq`, and Bluetooth usage descriptions (`NSBluetoothAlwaysUsageDescription`, plus the SDK's compatibility requirements). Retain the camera permission already required by your video app.
3. Retain a `DrowsyWatchLink` initialized with that callback scheme. Set `onStatus` and `onWatchMessage` to update the phone UI and track delivery. Call `selectWatch` to open Garmin device selection. Route the returned URL from the app/scene URL handler to `devicesFromURL:` after validating the callback scheme and Garmin origin as in Garmin's example; let the user select a returned device and call `attachDevice:`.
4. Schedule `heartbeat` every 5 seconds while foreground monitoring. The module waits for Bluetooth characteristics discovery, sends a hello, and stores the watch's session reply before sending alerts. Keep the watch app open and select Return to live, not Replay TEST DATA.
5. Call the sender on the main thread when your camera model makes a fresh decision:

```objc
[link sendDrowsinessSeverity:@"high" capturedAt:videoResultCaptureDate];
// Or @"warning". Preserve the actual capture time; never retimestamp an old result.
```

`YES` means the message was submitted, not that the watch accepted it. Check `onWatchMessage` for a receipt with `status = accepted` and the corresponding sequence. Display disconnected/failed/missing receipt states on the phone. Do not blindly retry stale decisions. Call `clearPhoneAlertCapturedAt:` only on an explicit fresh recovery decision; it clears only the phone alert, preserving any watch-model alert. Stop the host heartbeat timer and call `stop` when monitoring ends.

## Wire format, protocol 1

Use dictionaries with string keys and integer numbers. `sentAt` is the result capture time in UTC epoch seconds; watch and phone clocks must agree. First send:

```json
{"protocol":1,"source":"phone_video","type":"hello","sentAt":1790000000}
```

The watch replies with `type: hello_reply`, `status: ready`, and `session`. Then send:

```json
{"protocol":1,"source":"phone_video","type":"alert","severity":"high","sentAt":1790000001,"session":"VALUE_FROM_HELLO","sequence":1}
```

The example timestamps are placeholders: use the current capture timestamp. `severity` is `warning` or `high`. `heartbeat` and `clear` use the same envelope without severity. Sequence numbers must increase; the supplied sender persists them. The watch rejects results older than 10 seconds, timestamps over 2 seconds in the future, duplicates, malformed messages, and old sessions. A watch restart requires another hello. Replay rejects alerts with `test_mode`.

Receipts include `status` (`accepted`, `stale`, `duplicate`, `wrong_session`, `invalid`, or `test_mode`) and, when available, sequence. START silences both active alert sources while retaining elevated status and sends `type: user_acknowledged` for the phone alert. Its sequence identifies the latest accepted phone alert. Replies use a bounded pending slot; transport failure can prevent acknowledgment delivery, so phone UI must not assume receipt.

No recent heartbeat for 15 seconds marks the phone signal stale; it retains an existing warning. Flashing lasts up to 10 seconds; tone/vibration repeat at most every 5 seconds for up to 30 seconds. Fresh elevated messages can remind after the configured acknowledgment cooldown. An absent phone connection never creates a low-risk score.

## Build and physical test

Watch simulator and release builds use the existing developer key. Copy `bin/DrowsyAlert.prg` to the watch's `GARMIN/APPS` directory over USB, eject, and open DrowsyAlert. Pair the Forerunner 970 in Garmin Connect on iPhone, allow Bluetooth, launch the camera app, select the watch, and wait for the handshake-ready status. Send a fresh warning and then high alert. Check the screen, tone, vibration, START acknowledgment reply, clear, disconnect/stale behavior, and watch restart handshake. Replay TEST DATA remains a separate offline demonstration.

Six Monkey C simulator tests cover alert behavior, features/replay, and phone protocol handling. Actual iPhone Bluetooth transport, iOS compilation, speaker, and physical vibration still require hardware testing. The Objective-C module was checked against Garmin SDK interfaces but cannot be compiled with Xcode on this Windows machine. Your camera app and its model are not included here.
