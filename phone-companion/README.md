# DrowsyRelay iPhone companion

This app connects the existing DrowsyAlert Forerunner 970 app to your team's Python model and website. It uses Garmin's native iOS SDK for Bluetooth, a bundled website for phone monitoring/manual controls, and a small local HTTP relay for the Python model. No trained model is included, and no teammate model files were edited.

```
Garmin watch ↔ Bluetooth ↔ DrowsyRelay iPhone ↔ local network ↔ laptop relay ↔ Python model / website
```

The Python process cannot run inside the iPhone's embedded website unchanged. The provided local relay is the minimum service required to connect it; it runs on your laptop and does not require public hosting or Docker. The bundled web page can later be replaced with browser-compatible models to remove that laptop/network dependency.

## Open and install on iPhone (Mac required)

1. Copy/clone the shared repository onto your Mac, preserving `phone-companion/` and `DrowsyApp/DrowsyAlert/ios-companion/` as siblings. Open `phone-companion/DrowsyRelay.xcodeproj` in Xcode. The project references the existing watch-link module directly; it does not duplicate it.
2. Let Xcode resolve the official [Garmin Connect IQ SDK package](https://github.com/garmin/connectiq-companion-app-sdk-ios). Select the **DrowsyRelay** scheme. In Signing & Capabilities, select your Apple development team and use a unique bundle identifier if necessary. This is Apple signing, separate from the preserved Garmin developer key.
3. Connect your iPhone, enable Developer Mode if Xcode requests it, select that phone as the run destination, and press Run. Allow Bluetooth and local network access. Garmin Bluetooth needs a physical phone/watch; an iOS simulator cannot establish the physical watch connection.
4. Install the newly built `DrowsyApp/DrowsyAlert/bin/DrowsyAlert.prg` into the watch's `GARMIN/APPS` directory. Open DrowsyAlert and choose **Return to live**.
5. Pair the watch in Garmin Connect on iPhone. In DrowsyRelay, tap **Select watch**, share the device in Garmin Connect, and select the returned watch. The app waits for Bluetooth characteristics and the watch hello/session reply, then sends five-second heartbeats.

The Xcode project includes `-ObjC`, callback URL registration, Bluetooth/local-network/camera descriptions, a shared scheme, and protocol XCTest cases. The supplied source/project has not been compiled with Xcode on this Windows machine. Run Product → Test on the Mac, then validate the hardware steps below. The Debug target allows plain HTTP for the local demo; Release disables the broad HTTP exception, so use a trusted HTTPS endpoint for a hosted release. The app does not bypass TLS validation.

## Start the laptop relay

Install Node.js 18 or newer on the laptop (no npm dependencies are required). Open a terminal in `phone-companion/`.

macOS/Linux:

```sh
HOST=0.0.0.0 node local-relay/server.cjs
```

PowerShell:

```powershell
$env:HOST = '0.0.0.0'
node local-relay/server.cjs
```

It prints a temporary **pairing token** and uses port 8765. By default it binds only `127.0.0.1`; setting HOST permits your iPhone to reach it on the LAN. Allow the laptop firewall's private-network connection if prompted. On iPhone, enter `http://LAPTOP_LAN_IP:8765`, paste the token, and tap **Connect laptop**. Do not enter localhost: on iPhone, that points to the phone. Client ID is **demo** for this single-user demonstration. Pairing tokens stay in phone memory and are not saved to the repository or defaults; enter again after relaunch. The laptop URL is remembered.

Keep the phone/laptop on the same network, with both the iPhone and watch apps foreground. The iPhone polls/uploads every second with one HTTP request at a time; Bluetooth and inference add latency. This is near-live demo transport, not a hard real-time guarantee. No video goes through Bluetooth. No server-side readings are written to disk.

The relay has no classifier or automatic dummy score generator. Its test suite uses fixture scores only; they never enter the live watch feed. To expose a website on a different local origin, set `DROWSY_RELAY_ORIGIN` to its exact origin, e.g. `http://localhost:5173`. A browser caller still supplies the pairing token. Plain HTTP is appropriate only for the private-network demo; for public deployment, terminate TLS, configure authorization, and use HTTPS. Docker alone does not turn a local address into a public endpoint.

## Teammate integration

See [RELAY_CONTRACT.md](RELAY_CONTRACT.md) for both the Python/HTTP and bundled JavaScript interfaces. Start with `local-relay/gateway_client.py` in your existing Python process. It uses only Python's standard library. Do not copy models into the watch or invent missing sensor values.

The phone maintains separate latest model and camera command slots. Camera commands get priority; the SDK has only one Bluetooth send active. Missing/stale inputs, old sessions, invalid scores, and duplicates are rejected. Watch receipts and START acknowledgments are forwarded to the laptop and bundled website. **HTTP 202 or Bluetooth send success is not proof that the watch accepted or played an alert.** Check the final `command_result` and the physical watch.

Watch model scores use the existing demonstration thresholds: warning ≥0.70 for three valid five-second evaluations, high ≥0.90 immediately, recovery <0.55 for three evaluations. These need model validation. Camera/manual commands are independent explicit warning/high decisions; they do not overwrite the vitals risk score. Clear camera alerts explicitly when the camera model recovers. START silences scheduled alarm output while retaining elevated status. Missing watch sensors cannot block camera alerts but do block a low-risk vitals prediction.

## Bundled local website

`Web/index.html` shows live sensors, camera preview, and clearly labeled manual camera-alarm controls. It reports **Model not connected** until your teammate integrates a classifier. Preview alone is not classification. Camera support/permission in the bundled WKWebView must be checked on the target iPhone; failure is shown on the page.

Replace the Web directory's content with your teammate's **static build**, keeping an `index.html`. Use relative asset paths (for Vite, base `./`), include model assets locally if running browser inference, and preserve the `window.DrowsyRelay` contract. The native app injects `bridge.js` automatically; keep that file in the Web directory. A Python/Streamlit application is not a static build and stays on the laptop. This app intentionally does not load arbitrary remote pages into its privileged Bluetooth bridge. Website camera classification on the laptop can POST commands to the local relay instead.

## Validation

```sh
node --test Tests/*.test.cjs
```

These tests cover JavaScript/native message behavior and the local HTTP relay end-to-end, using simulated telemetry/decisions. Xcode's RelayProtocolTests cover native payload validation but must run on your Mac. Monkey C tests cover remote score routing/timestamps/thresholds along with previous sensors/replay/camera alerts.

Physical checklist:

1. Verify real HR/motion readings reach the phone page and `GET /api/state`, with optional missing readings still null.
2. Run the teammate model against an unchanged telemetry snapshot; send its real 0–1 score and verify the watch display and threshold transitions.
3. Send a manual/camera warning and high alert; check screen flashing, sound, vibration, and START acknowledgment.
4. Disconnect the laptop and Bluetooth independently. Confirm stale scores never display low risk, and active warnings remain visible.
5. Restart the watch; old-session commands must be rejected until the handshake and fresh telemetry resume. Verify replay exports no synthetic live telemetry.
6. Pause/background the phone. Relay timers stop, pending commands are dropped, and camera preview stops. After returning, tap Start if paused manually and Connect laptop again. For this demo, keep the app foreground; continuous background operation is not implemented.

No Git commit, push, app publication, or Apple provisioning was performed.
