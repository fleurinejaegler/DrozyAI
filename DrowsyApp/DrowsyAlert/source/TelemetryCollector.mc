import Toybox.Lang;
import Toybox.Math;
// Latest batch only. HRV history is independent of the model's feature buffers.
class TelemetryCollector {
    var acceleration = null; var gyroscope = null; var intervals = null;
    var batchAt = null; var batchId = 0;
    var beats as Array<Array<Number>> = []; var lastBeatAt = null;
    function initialize() {}
    function axes(data as Toybox.Sensor.AccelerometerData or Toybox.Sensor.GyroscopeData or Null, rate, unit) {
        if (data == null) { return null; }
        return encodeAxes(data.x, data.y, data.z, data.timestamp, rate, unit);
    }
    function encodeAxes(xs as Array, ys as Array, zs as Array, stamps as Array?, rate, unit) {
        var n = Config.min(xs.size(), Config.min(ys.size(), zs.size())).toNumber();
        if (n == 0) { return null; }
        var count = Config.min(n, Config.TELEMETRY_MAX_SAMPLES).toNumber();
        var x = []; var y = []; var z = []; var timestamps = [];
        for (var i = 0; i < count; i += 1) {
            // Preserve positions and null samples; no interpolation.
            x.add(xs[i]); y.add(ys[i]); z.add(zs[i]);
            timestamps.add(stamps != null && i < stamps.size() ? stamps[i] : null);
        }
        return {"unit" => unit, "sampleRateHz" => rate, "x" => x, "y" => y, "z" => z,
            "sensorTimestampMs" => timestamps, "inputCount" => n, "truncated" => n > count};
    }
    function addIntervals(values as Array?, now as Number) {
        if (lastBeatAt != null && now - lastBeatAt > Config.SENSOR_FRESH_MS) { beats = []; }
        intervals = null;
        if (values == null) { return; }
        intervals = values.size() > 0 ? values.slice(0, Config.min(values.size(), 8).toNumber()) : null;
        for (var i = 0; i < values.size() && i < 8; i += 1) {
            var rr = values[i];
            if (!(rr instanceof Number) || rr < 300 || rr > 2000) { beats = []; continue; }
            beats.add([now, rr]); lastBeatAt = now;
        }
        trim(now);
    }
    function trim(now) {
        while (beats.size() > 0) {
            var first = beats[0];
            if (beats.size() <= 256 && now - first[0] <= 60000) { break; }
            beats = beats.slice(1, beats.size());
        }
    }
    function collect(data as Toybox.Sensor.SensorData, now, accelRate, gyroRate) {
        acceleration = axes(data.accelerometerData, accelRate, "mg");
        gyroscope = axes(data.gyroscopeData, gyroRate, "deg/s");
        addIntervals(data.heartRateData == null ? null : data.heartRateData.heartBeatIntervals, now);
        batchAt = now; batchId += 1;
    }
    function hrv(now) {
        if (lastBeatAt == null || now - lastBeatAt > Config.SENSOR_FRESH_MS) { return null; }
        trim(now);
        if (beats.size() < 31 || beats[beats.size()-1][0] - beats[0][0] < 54000) { return null; }
        var sum = 0.0;
        for (var i = 1; i < beats.size(); i += 1) {
            if (beats[i][0] - beats[i-1][0] > Config.SENSOR_FRESH_MS) { return null; }
            var delta = beats[i][1] - beats[i-1][1]; sum += delta * delta;
        }
        return Math.sqrt(sum / (beats.size()-1));
    }
    function packet(sensors as SensorCollector, now, utc, sequence, session) as Dictionary {
        var fresh = sensors.fresh(batchAt, now);
        return {"protocol" => 1, "type" => "telemetry", "schema" => 1, "source" => "watch_sensors",
            "session" => session, "sequence" => sequence, "sentAt" => utc, "watchUptimeMs" => now,
            "batchId" => batchId, "batchReceivedAtMs" => batchAt,
            "heartRateBpm" => sensors.fresh(sensors.hrAt, now) ? sensors.hr : null,
            "heartRateAtMs" => sensors.hrAt,
            "spo2Percent" => sensors.fresh(sensors.oxygenAt, now) ? sensors.oxygen : null,
            "spo2AtMs" => sensors.oxygenAt,
            "temperatureC" => sensors.fresh(sensors.temperatureAt, now) ? sensors.temperature : null,
            "temperatureAtMs" => sensors.temperatureAt,
            "accelerometer" => fresh ? acceleration : null, "gyroscope" => fresh ? gyroscope : null,
            "beatIntervalsMs" => fresh ? intervals : null,
            "hrvRmssdMs" => hrv(now), "hrvWindowSeconds" => 60};
    }
}
