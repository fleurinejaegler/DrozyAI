# Watch configuration for the completed local-model guide

This watch build defaults to `WebsiteConfig.USE_PHONE_RELAY = true`.
It starts its phone listener and sends live telemetry automatically on launch.
Fresh `phone_relay` / `model_result` messages are routed explicitly to
`DrowsyAlertApp.acceptModelResult`; stale/invalid results invalidate the score.
Camera/fusion alarm messages continue to use the independent alert channel.
The main screen shows phone connection status instead of WEBSITE: COMING SOON.
Direct HTTPS upload is disabled in this mode to avoid running two pipelines.
No laptop URL, pairing token or model artifact belongs on the watch.

## One-time device setup

1. Install `DrowsyApp/DrowsyAlert/bin/DrowsyAlert.prg` in `GARMIN/APPS` on the fr970.
2. Pair the watch with Garmin Connect on the iPhone.
3. Build/install the existing DrowsyRelay iPhone project with Xcode and Apple signing.
4. Start the completed website's `run_demo.py` on the model laptop.
5. On its page, reveal phone pairing details. In DrowsyRelay select the watch,
   enter the laptop LAN relay URL, client ID `demo`, and the displayed pairing token.
6. Keep phone and model laptop on the same network, and both watch and phone apps
   foreground. Start the laptop browser camera if using video predictions.

Temporary laptop pairing tokens may require re-pairing after a launcher restart.
This change removes watch setup, not the phone/laptop pairing required by the guide.
The current native companion is iOS; building/installing it requires a Mac with Xcode.
This is different from the optional Windows-compatible HTTPS sensor receiver.

## Verification boundary

The guide's `run_demo.py` and `realtime_backend/` are absent from this Windows
checkout. Its existing `web/app.py` and relay model adapter are older: they do not
implement the completed live model pipeline described in the guide. Obtain the
completed partner code before trying to launch it here. Do not substitute the old
web app and claim the model round trip works.

Compiler/simulator verification checks the watch protocol, not physical phone
pairing or real model inference. Verify live sensor data, accepted model messages,
screen/sound/vibration, acknowledgment, and stale/disconnect behavior on hardware.
