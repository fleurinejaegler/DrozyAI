# Integration verification — October 11, 2026

The connected software was installed and tested from this repository with its own `.venv-demo` Python 3.12 environment. These checks establish software integration and the physical telemetry connection. They do not establish detection accuracy, complete model inputs or alarm playback.

| Check | Result |
|---|---|
| Python model, feature, API, advisor and relay-return tests | 50 passed |
| Separate preparation compatibility tests | 34 passed |
| Browser feature/metric and phone relay tests | 18 passed |
| Actual model → real isolated HTTP relay → simulated phone receipt | Passed |
| Actual watch + TCN → asynchronous installed Llama advisor → Python weighted fusion | Passed with and without baseline |
| Local Llama response times in those two synthetic integration cases | 2.77 s initially; 0.82 s with baseline context |
| Null temperature sequence | Last real value retained for 75 s; original age preserved; reset on new session |
| Forerunner 970 release compilation | Passed; `DrowsyApp/DrowsyAlert/bin/DrowsyAlert.prg` |
| Unsigned iOS simulator build | Passed |
| Unsigned physical-iOS-device target build | Passed |
| Signed physical-iOS-device target build with selected Personal Team | Passed; `xcodebuild` reported `BUILD SUCCEEDED` |
| Physical iPhone install and launch | Passed after runtime search-path fix; process stayed alive and user confirmed controls visible |
| App icon packaging | Opaque 1024 px icon compiled; built plist contains `CFBundleIcons` |
| Repository diff whitespace check | Passed |
| Fitted model/scaler SHA-256 comparison | Unchanged |
| Physical Garmin → iPhone → laptop telemetry | Passed: actual watch handshake, accepted heartbeat replies, live HR, temperature and raw sensor packets on laptop |
| Watch-link scheduling and reconnect checks | 17 passed using the real Objective-C module with a fake Garmin transport |
| Raw beat intervals | Appeared in later live packets; feature quality and training-data equivalence remain experimental |
| Camera permission and alarm playback | Not established by this connection test |

The smaller `llama3.2:3b` local model was installed because the previously available 27B Qwen model exceeded the five-second update cycle. The launcher prefers the original Llama model when present, supports an explicit `LLM_MODEL` override, and never downloads models automatically. Valid immediate deterministic advice remains available; late/invalid/failed LLM replies are discarded.

The current dashboard runs at http://127.0.0.1:8778/ and the phone relay uses port 8766, preserving existing services on 8777/8765. Pairing tokens are temporary and must be obtained from **Show phone pairing details**. Restart from this folder with:

```sh
.venv-demo/bin/python run_demo.py --port 8778 --relay-port 8766
```

See [CONNECTION_GUIDE.md](CONNECTION_GUIDE.md) for Apple signing/install, Garmin sideload and the physical round trip. Live Garmin-to-Empatica and RGB-to-Dlib feature transfer remain experimental. Genuine IBI and an initial real temperature are required for the watch model. Scores are uncalibrated, not percentage chances or model accuracy.

## iPhone installation follow-up

Xcode had opened the older project at `../phone-companion/DrowsyRelay.xcodeproj`. Its obsolete `IQApp appWithUUID:device:` call was corrected to `appWithUUID:storeUuid:device:`. The user-selected Personal Team was applied to this integrated project, which passed a signed Debug device-target build. The integrated project is open in Xcode with the physical iPhone selected. Developer Mode and certificate trust were completed by the user. A physical launch then exposed `Library not loaded: @rpath/ConnectIQ.framework/ConnectIQ`, with `no LC_RPATH's found`. Runtime framework search paths were added to Debug and Release configurations. The corrected signed app was reinstalled and launched on the physical iPhone; the process stayed alive across subsequent checks, and the user confirmed **Select watch** and **Connect laptop** controls were visible. An opaque icon asset catalog was also added and verified in the built app. Physical Garmin message exchange and laptop telemetry were subsequently confirmed as described below. Complete model inputs and alarm playback remain separate checks.

Use `/Users/isaacoliva/Desktop/UCSC Hackathon/DrozyAI/DrozyAI/phone-companion/DrowsyRelay.xcodeproj` for this integration. Git author name/email is only required to make commits and does not block building or installing the app.

## Saved artifact verification

- `baseline_model.pkl`: `fd836d93c310c75bfef24a1f5144fa502bc140411a25308cd5c7f740b31fc739`
- `small_tcn.pt`: `57ee60a0b7f440188e90c6e8c0fc1c88917ec3c52f830eb654400eb0c6f7ed3f`
- `facial_model.pkl`: `7439d1ecdbc3f678a1e4b8afb9df82aef8ed7971a163fa468c73ca8b817e73cf`
- `tcn_scaler.joblib`: `d730f337a67deef90d9cabe6ee02b5a88709768aa8e53d7fc8166402d70b8d16`

## Physical watch connection follow-up

The iPhone's Garmin Connect callback omitted `UIApplicationOpenURLOptionsSourceApplicationKey`.
The former source-application requirement therefore rejected the callback without attaching a watch.
Device-console evidence after the fix showed source **not supplied**, **one shared device**, Bluetooth
characteristics discovery, a successful `hello_reply`, and repeated **accepted** watch receipts.
The user confirmed **live telemetry enabled** and **laptop connected**. The laptop independently
received real telemetry: HR 55 bpm, a temperature reading and 57 buffered watch packets at the
first inspection. Genuine IBI was absent in that snapshot, and HR/motion coverage was still below
the model's required coverage. The model correctly withheld its score; receiving telemetry is
not equivalent to having a complete valid model window. Sensor.Info temperature is not established
as skin temperature. A subsequent inspection recorded raw intervals in 12 one-second bins,
so intervals did begin arriving; HR/motion coverage remained insufficient. The laptop then
reported no recent phone/watch exchange while the watch continued accepting heartbeats,
consistent with the phone relay needing to remain foreground and connected to the laptop.

The repaired callback requires the app's own URL scheme, validates Garmin's source when iOS
supplies it, and parses devices through Garmin's SDK. A single shared watch now attaches directly;
multiple watches are presented only after the app is active. The last authorized selection uses
secure coding for reconnect after relaunch; any new selection response replaces the previous one.
Keepalives wait for characteristics discovery and silently coalesce while a send is outstanding.
Connection errors now identify the connection stage rather than combining unavailable/busy states.

Run the native behavior checks on macOS using the official SDK headers from Xcode's resolved
ConnectIQ package:

```sh
python3 phone-companion/Tools/check_watch_link.py --sdk-headers /path/to/ConnectIQ.framework/Headers
```

These 17 checks exercise no-selection keepalives, discovery ordering, in-flight coalescing,
transport success versus watch acceptance, reconnect races, missing-app failures, stale alerts
and disconnect invalidation. They use fake Bluetooth and do not replace the physical checks.
