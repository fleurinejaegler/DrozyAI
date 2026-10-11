// Partner integration: replace these values, then rebuild the device PRG.
// .invalid is deliberately nonfunctional; no sensor data is sent to a placeholder.
module WebsiteConfig {
    // Completed model guide uses DrowsyRelay -> laptop, not direct HTTPS uploads.
    // The relay discovers this app UUID and exchanges telemetry/model_result messages.
    const USE_PHONE_RELAY = true;
    const UPLOAD_URL = "https://drowsy-placeholder.invalid/garmin/data";
    const API_TOKEN = "replace-with-development-token";
    const READY = false;
    const UPLOAD_INTERVAL_MS = 5000;
}
