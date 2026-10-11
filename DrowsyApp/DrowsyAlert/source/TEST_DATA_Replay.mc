import Toybox.Lang;

// TEST DATA ONLY: synthetic values, NOT measurements collected from a Garmin.
// Columns: heartRateBpm, accelerationMagnitudeMg (gravity included), spo2Percent,
// assumed model riskScore (0..1). Each row lasts five seconds; sequence loops.
// These scores are independent fixtures, NOT inferred from the health metrics.
class TestDataReplay {
    var started = 0;
    var rows as Array = [
        [72, 1008.0, 98, 0.28], [74, 1035.0, 98, 0.32],
        [73, 1012.0, 97, 0.38], [71, 1004.0, null, 0.48],
        [70, 1003.0, 98, 0.72], [69, 1002.0, 98, 0.76],
        [71, 1010.0, 98, 0.79], [72, 1007.0, 97, 0.83],
        [73, 1015.0, 98, 0.95], [74, 1030.0, 98, 0.96],
        [72, 1009.0, 98, 0.93], [71, 1004.0, 98, 0.91],
        [null, null, null, null], [null, null, null, null],
        [75, 1080.0, 98, 0.45], [76, 1120.0, 98, 0.40],
        [74, 1050.0, 98, 0.35], [73, 1020.0, 98, 0.28]
    ];
    function initialize(now) { started = now; }
    function row(now) as Array { return rows[((now - started) / Config.EVALUATION_MS).toNumber() % rows.size()]; }
    function applyVitals(sensors as SensorCollector, now) {
        var r = row(now);
        // Held fixture values published on every app tick; no raw accelerometer/HRV is invented.
        sensors.hr = r[0]; sensors.hrAt = r[0] == null ? null : now;
        sensors.movement = r[1]; sensors.accelAt = r[1] == null ? null : now;
        sensors.oxygen = r[2]; sensors.oxygenAt = r[2] == null ? null : now;
    }
    function result(adapter as ModelAdapter, now) as Dictionary {
        var r = row(now);
        return adapter.resultFromScore(r[3], now, "TEST-DATA-v1");
    }
}
