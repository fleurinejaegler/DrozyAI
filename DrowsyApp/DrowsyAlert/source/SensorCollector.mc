import Toybox.Sensor;
import Toybox.System;
import Toybox.Math;
import Toybox.SensorHistory;
import Toybox.Time;
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
    var temperature = null;
    var temperatureAt = null;
    var gyroRate = 0;
    var telemetry as TelemetryCollector;
    var uploadBuffer as UploadBuffer;
    var externalHeart = true; var externalTemperature = true;
    var ibiReceivedAt = null; var uploadTemperature = null; var uploadTemperatureEpoch = null;
    var uploadTemperatureAt = null; var lastHistoryEpoch = null; var lastHistoryPoll = null;
    function initialize() { telemetry = new TelemetryCollector(); uploadBuffer = new UploadBuffer(); }
    function checkSources() {
        // Conservative: any registered external sensor blocks that source, even if inactive.
        externalHeart = true; externalTemperature = true;
        try {
            externalHeart = Sensor.getRegisteredSensors(Sensor.SENSOR_HEARTRATE).next()!=null;
            externalTemperature = Sensor.getRegisteredSensors(Sensor.SENSOR_TEMPERATURE).next()!=null;
        } catch (ex) { System.println("Onboard source check unavailable; HR/IBI/temperature uploads blocked"); }
    }
    function pollUploadTemperature(now) {
        if (!uploadBuffer.recording || (lastHistoryPoll!=null && now-lastHistoryPoll<5000)) { return; }
        lastHistoryPoll=now; checkSources();
        if (externalTemperature) { uploadTemperature=null; return; }
        var sample=null;
        try {
            if (SensorHistory has :getTemperatureHistory) {
                sample=SensorHistory.getTemperatureHistory({:period=>1,:order=>SensorHistory.ORDER_NEWEST_FIRST}).next();
            }
        } catch (ex) {}
        if (sample!=null && sample.data!=null && sample.when!=null) {
            var epoch=sample.when.value();
            if (epoch!=lastHistoryEpoch) {
                uploadTemperature=sample.data; uploadTemperatureEpoch=epoch; uploadTemperatureAt=now; lastHistoryEpoch=epoch;
                uploadBuffer.addTemperature(now,sample.data,"watch_onboard_history",epoch);
            }
        } else {
            uploadTemperature=fresh(temperatureAt,now) ? temperature : null;
            uploadTemperatureEpoch=null; uploadTemperatureAt=now;
            uploadBuffer.addTemperature(now,uploadTemperature,"watch_sensor_info_no_external",null);
        }
    }
    function uploadAvailability(now) as Toybox.Lang.Dictionary {
        var tempFresh=uploadTemperature!=null && uploadTemperatureAt!=null && now-uploadTemperatureAt<=300000;
        if (uploadTemperatureEpoch!=null) { var age=Time.now().value()-uploadTemperatureEpoch; tempFresh=tempFresh && age>=0 && age<=300; }
        return {"heart_rate"=>externalHeart ? "external_blocked" : (fresh(hrAt,now) ? "receiving" : "unavailable"),
            "accelerometer"=>fresh(accelAt,now) ? "receiving" : "unavailable",
            "ibi"=>externalHeart ? "external_blocked" : (fresh(ibiReceivedAt,now) ? "receiving" : "unavailable"),
            "temperature"=>externalTemperature ? "external_blocked" : (tempFresh ? "receiving" : "unavailable")};
    }
    function start() {
        if (running) { return; }
        running = true;
        checkSources();
        try {
            Sensor.setEnabledSensors([Sensor.SENSOR_HEARTRATE]);
            Sensor.enableSensorEvents(method(:onInfo));
        } catch (ex) { System.println("Heart rate listener unavailable"); }
        // Enable optional sensors independently: one failure cannot disable HR.
        var enabled = [Sensor.SENSOR_HEARTRATE];
        if (Sensor has :SENSOR_PULSE_OXIMETRY) {
            try { Sensor.setEnabledSensors([Sensor.SENSOR_HEARTRATE, Sensor.SENSOR_PULSE_OXIMETRY]); enabled.add(Sensor.SENSOR_PULSE_OXIMETRY); }
            catch (ex) { try { Sensor.setEnabledSensors(enabled); } catch (fallback) {} }
        }
        try {
            var withTemperature = enabled.slice(0, enabled.size()); withTemperature.add(Sensor.SENSOR_TEMPERATURE);
            Sensor.setEnabledSensors(withTemperature);
        } catch (ex) { try { Sensor.setEnabledSensors(enabled); } catch (fallback) {} }
        try { gyroRate = Config.min(Config.GYRO_RATE, Sensor.getMaxSampleRateForSensorType(:gyroscope)).toNumber(); }
        catch (ex) { gyroRate = 0; }
        try {
            sampleRate = Config.min(Config.ACCEL_RATE, Sensor.getMaxSampleRateForSensorType(:accelerometer)).toNumber();
            if (sampleRate > 0) {
                try { register(true, gyroRate > 0); }
                catch (ex) {
                    try { register(false, gyroRate > 0); }
                    catch (fallback) { gyroRate = 0; try { register(true, false); } catch (rrFallback) { register(false, false); } }
                }
            }
        } catch (ex) { System.println("Accelerometer listener unavailable"); }
    }
    function register(withIntervals, withGyro) {
        Sensor.registerSensorDataListener(method(:onData), {
            :period => 1,
            :accelerometer => { :enabled => true, :sampleRate => sampleRate, :includeTimestamps => true },
            :gyroscope => { :enabled => withGyro, :sampleRate => withGyro ? gyroRate : Config.GYRO_RATE, :includeTimestamps => true },
            :heartBeatIntervals => { :enabled => withIntervals }
        });
    }
    function onInfo(info as Sensor.Info) as Void {
        if (!running) { return; }
        var now = System.getTimer();
        temperature = info.temperature;
        temperatureAt = temperature != null ? now : null;
        hr = info.heartRate;
        hrAt = (hr != null && hr > 0) ? now : null;
        if (hrAt == null) { hr = null; }
        if (uploadBuffer.recording) { checkSources(); uploadBuffer.addHeart(now,externalHeart ? null : hr); }
        if (info has :oxygenSaturation) {
            oxygen = info.oxygenSaturation;
            oxygenAt = (oxygen != null && oxygen > 0 && oxygen <= 100) ? now : null;
            if (oxygenAt == null) { oxygen = null; }
        }
    }
    function onData(data as Sensor.SensorData) as Void {
        if (!running) { return; }
        var now = System.getTimer();
        telemetry.collect(data, now, sampleRate, gyroRate);
        var accel = data.accelerometerData;
        if (accel != null) {
            uploadBuffer.addAxes(accel.x,accel.y,accel.z,accel.timestamp,now,sampleRate);
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
        if (uploadBuffer.recording) {
            var raw = !externalHeart && rate!=null ? rate.heartBeatIntervals : null;
            uploadBuffer.addIntervals(raw,now);
            ibiReceivedAt=raw!=null && raw.size()>0 ? now : null;
        }
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
