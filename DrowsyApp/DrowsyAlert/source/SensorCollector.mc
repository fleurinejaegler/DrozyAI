import Toybox.Sensor;
import Toybox.System;
import Toybox.Math;
class SensorCollector {
    var hr = null;
    var hrAt = null;
    var oxygen = null;
    var oxygenAt = null;
    var accelAt = null;
    var movement = null;
    var sampleRate = Config.ACCEL_RATE;
    var accelSum = 0.0;
    var accelSq = 0.0;
    var accelN = 0;
    var stillN = 0;
    var rrSq = 0.0;
    var rrPairs = 0;
    var previousRR = null;
    var rrAt = null;
    var lastAccelTimestamp = null;
    var running = false;
    function initialize() {}
    function start() {
        if (running) { return; }
        running = true;
        try {
            Sensor.setEnabledSensors([Sensor.SENSOR_HEARTRATE]);
            Sensor.enableSensorEvents(method(:onInfo));
        } catch (ex) { System.println("Heart rate listener unavailable"); }
        try {
            if (Sensor has :SENSOR_PULSE_OXIMETRY) {
                Sensor.setEnabledSensors([Sensor.SENSOR_HEARTRATE, Sensor.SENSOR_PULSE_OXIMETRY]);
            }
        } catch (ex) {
            System.println("Optional SpO2 unavailable");
            try { Sensor.setEnabledSensors([Sensor.SENSOR_HEARTRATE]); } catch (fallback) {}
        }
        try {
            sampleRate = Config.min(Config.ACCEL_RATE, Sensor.getMaxSampleRateForSensorType(:accelerometer)).toNumber();
            if (sampleRate > 0) {
                try { register(true); } catch (ex) { register(false); }
            }
        } catch (ex) { System.println("Accelerometer listener unavailable"); }
    }
    function register(withIntervals) {
        Sensor.registerSensorDataListener(method(:onData), {
            :period => 1,
            :accelerometer => { :enabled => true, :sampleRate => sampleRate, :includeTimestamps => true },
            :heartBeatIntervals => { :enabled => withIntervals }
        });
    }
    function onInfo(info as Sensor.Info) as Void {
        if (!running) { return; }
        var now = System.getTimer();
        hr = info.heartRate;
        hrAt = (hr != null && hr > 0) ? now : null;
        if (hrAt == null) { hr = null; }
        if (info has :oxygenSaturation) {
            oxygen = info.oxygenSaturation;
            oxygenAt = (oxygen != null && oxygen > 0 && oxygen <= 100) ? now : null;
            if (oxygenAt == null) { oxygen = null; }
        }
    }
    function onData(data as Sensor.SensorData) as Void {
        if (!running) { return; }
        var now = System.getTimer();
        var accel = data.accelerometerData;
        if (accel != null) {
            var count = Config.min(accel.x.size(), Config.min(accel.y.size(), accel.z.size())).toNumber();
            var batchSum = 0.0; var batchN = 0;
            for (var i = 0; i < count; i += 1) {
                if (accel.x[i] == null || accel.y[i] == null || accel.z[i] == null) { continue; }
                if (accel.timestamp != null && i < accel.timestamp.size()) {
                    var stamp = accel.timestamp[i];
                    if (lastAccelTimestamp != null && stamp <= lastAccelTimestamp) { continue; }
                    lastAccelTimestamp = stamp;
                }
                var x = accel.x[i].toFloat(); var y = accel.y[i].toFloat(); var z = accel.z[i].toFloat();
                var mag = Math.sqrt(x*x + y*y + z*z);
                accelSum += mag; accelSq += mag*mag; accelN += 1;
                batchSum += mag; batchN += 1;
                if ((mag - 1000.0).abs() < Config.STILL_MG) { stillN += 1; }
            }
            if (batchN > 0) { accelAt = now; movement = batchSum / batchN; }
        }
        var rate = data.heartRateData;
        if (rate != null) {
            if (rrAt == null || now - rrAt > Config.SENSOR_FRESH_MS) { previousRR = null; }
            var intervals = rate.heartBeatIntervals;
            for (var j = 0; j < intervals.size(); j += 1) {
                var rr = intervals[j];
                if (rr == null || rr < 300 || rr > 2000) { previousRR = null; continue; }
                if (previousRR != null) {
                    var diff = rr - previousRR; rrSq += diff * diff; rrPairs += 1;
                }
                previousRR = rr; rrAt = now;
            }
        } else { previousRR = null; }
    }
    function fresh(at, now) { return at != null && now >= at && now - at <= Config.SENSOR_FRESH_MS; }
    function coreFresh(now) { return fresh(hrAt, now) && fresh(accelAt, now); }
    function take(now, lastHrAt) as Toybox.Lang.Dictionary {
        var point = { :t => now, :hr => (fresh(hrAt, now) && hrAt != lastHrAt) ? hr : null,
            :n => accelN, :sum => accelSum, :sq => accelSq, :still => stillN,
            :rrSq => rrSq, :rrPairs => rrPairs };
        accelN = 0; accelSum = 0.0; accelSq = 0.0; stillN = 0; rrSq = 0.0; rrPairs = 0;
        return point;
    }
    function stop() {
        running = false;
        try { Sensor.enableSensorEvents(null); } catch (ex) {}
        try { Sensor.unregisterSensorDataListener(); } catch (ex) {}
        try { Sensor.setEnabledSensors([]); } catch (ex) {}
        previousRR = null;
    }
}
