# Website and model partner handoff

The wearer opens DrowsyAlert. Sensor collection and baseline collection start
automatically. Website upload starts automatically when the build is configured.
No URL or token is entered on the watch.

## Enable your website

Edit `DrowsyApp/DrowsyAlert/source/WebsiteConfig.mc`:

```monkeyc
const UPLOAD_URL = "https://YOUR-WEBSITE/garmin/data";
const API_TOKEN = "YOUR-DEVELOPMENT-TOKEN";
const READY = true;
const UPLOAD_INTERVAL_MS = 5000;
```

Use a real HTTPS API endpoint, not the website homepage. Token must be at least
12 characters. Set the same token in the receiver's `GARMIN_API_TOKEN` environment
variable before starting `python -m server`. Rebuild for `fr970` and copy only
`bin/DrowsyAlert.prg` into the watch's `GARMIN/APPS`. Existing app-storage settings
are ignored; changing this file requires rebuilding and reinstalling.

The committed placeholder uses the nonfunctional `.invalid` domain and `READY=false`.
This intentionally prevents network requests and upload buffering while the website
is unfinished. Real sensors and existing alert handling continue to operate.
Do not use a real credential in committed source; the compiled development token is
shared and is not a production per-user authentication design.

## Website contract

- Accept `POST /garmin/data`, JSON, and `Authorization: Bearer <token>`.
- See [SCHEMA.md](SCHEMA.md) for the complete sensor payload and timestamps.
- The included FastAPI receiver already validates, deduplicates, saves raw data,
  exports CSV, and computes RMSSD where real IBI is available.
- Return HTTP 200 with `{"status":"accepted","session":"<incoming session>","batch_id":<incoming batch_id>}`.
  For a repeated identical batch, return `status:"duplicate"` with the same identifiers.
- Preserve missing readings as null and never infer IBI from BPM.
- Garmin Connect on a paired, internet-connected phone supplies the HTTPS bridge.
  The watch app must remain running; foreground requests are required by this implementation.

## Model integration is still separate work

Uploading sensor data does not itself deliver a prediction to the watch. The
current HTTP acknowledgment handler only confirms receipt. `ModelAdapter.evaluate`
still returns `model_not_connected`; this change does not add a fake live score.

Your model must use the real sensor stream, identify the session, and return fresh
predictions with a score in 0..1, status and model version. A future HTTPS response
integration must add prediction fields to the acknowledgment and route validated
results to `DrowsyAlertApp.acceptModelResult`, translating prediction age to the
watch's monotonic clock and rejecting stale results. Do not pass Unix epoch
milliseconds as the existing watch result timestamp.

There is also a separate phone relay protocol with `model_result` messages in
`PhoneAlertBridge.mc`, covered by watch tests. That path requires the custom phone
relay; the normal Garmin Connect HTTPS path does not implement those messages.

Validate actual watch -> phone -> website ingestion first, then model delivery and
yellow/red alarms. Placeholder and simulator tests do not verify that physical path.
