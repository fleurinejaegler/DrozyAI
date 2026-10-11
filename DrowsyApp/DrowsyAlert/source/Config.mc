module Config {
    function min(a, b) { return a < b ? a : b; }
    function max(a, b) { return a > b ? a : b; }
    const WINDOW_SECONDS = 60;
    const EVALUATION_MS = 5000;
    const BASELINE_SECONDS = 300;
    const COVERAGE = 0.90;
    const ACCEL_RATE = 25;
    const GYRO_RATE = 25;
    const TELEMETRY_MS = 1000;
    const TELEMETRY_MAX_SAMPLES = 25;
    const SENSOR_FRESH_MS = 3000;
    const RESULT_FRESH_MS = 10000;
    const WARNING = 0.70;
    const HIGH = 0.90;
    const RECOVERY = 0.55;
    const CONSECUTIVE = 3;
    const FLASH_MS = 10000;
    const SIGNAL_MS = 30000;
    const SIGNAL_INTERVAL_MS = 5000;
    const REMINDER_MS = 60000;
    const STILL_MG = 50.0;
}
