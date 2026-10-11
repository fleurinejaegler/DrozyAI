// Partner integration: replace these values, then rebuild the device PRG.
// .invalid is deliberately nonfunctional; no sensor data is sent to a placeholder.
module WebsiteConfig {
    const UPLOAD_URL = "https://drowsy-placeholder.invalid/garmin/data";
    const API_TOKEN = "replace-with-development-token";
    const READY = false;
    const UPLOAD_INTERVAL_MS = 5000;
}
