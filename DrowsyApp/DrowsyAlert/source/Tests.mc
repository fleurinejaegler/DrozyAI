import Toybox.Test;
import Toybox.Lang;
import Toybox.Math;
(:test)
function testAlertThresholds(logger) {
    var a = new AlertController(); a.signalEnabled = false;
    a.evaluate(testResult(0.70, 1000), 1000);
    a.evaluate(testResult(0.70, 6000), 6000);
    Test.assertEqual(a.level, 0);
    a.evaluate(testResult(0.70, 11000), 11000);
    Test.assertEqual(a.level, 1);
    Test.assert(a.flashing(11000));
    Test.assert(a.bright(11000));
    Test.assert(!a.bright(11500));
    Test.assert(a.bright(12000));
    Test.assert(!a.flashing(21000));
    a.evaluate(testResult(0.90, 16000), 16000);
    Test.assertEqual(a.level, 2);
    a.acknowledge(17000);
    Test.assertEqual(a.level, 2);
    Test.assert(!a.flashing(17000));
    a.evaluate(testResult(0.95, 22000), 22000);
    Test.assert(a.acknowledged);
    a.evaluate(testResult(0.95, 77000), 77000);
    Test.assert(!a.acknowledged);
    Test.assert(a.flashing(77000));
    a.evaluate(testResult(0.54, 82000), 82000);
    a.evaluate(testResult(0.54, 87000), 87000);
    Test.assertEqual(a.level, 2);
    a.evaluate(testResult(0.54, 92000), 92000);
    Test.assertEqual(a.level, 0);
    a.stop();
    return true;
}
(:test)
function testInvalidAndStale(logger) {
    var a = new AlertController(); a.signalEnabled = false;
    a.evaluate(testResult(0.75, 1000), 1000);
    a.evaluate(testResult(0.75, 6000), 6000);
    Test.assert(!a.evaluate(testResult(null, 11000), 11000));
    Test.assertEqual(a.warningCount, 0);
    a.evaluate(testResult(0.75, 16000), 16000);
    Test.assertEqual(a.level, 0);
    Test.assert(!a.evaluate(testResult(0.95, 1000), 17000));
    Test.assert(!a.evaluate(testResult(1.1, 18000), 18000));
    Test.assert(!a.evaluate(testResult(-0.1, 19000), 19000));
    Test.assert(!a.evaluate(testResult(0.95, 21000), 19000));
    Test.assert(!a.evaluate(testResult("bad", 19000), 19000));
    a.evaluate(testResult(0.95, 20000), 20000);
    Test.assertEqual(a.level, 2);
    a.invalidate();
    Test.assertEqual(a.level, 2);
    Test.assert(a.missing);
    a.evaluate(testResult(0.4, 25000), 25000);
    Test.assert(!a.evaluate(testResult(0.4, 25000), 26000));
    Test.assertEqual(a.recoveryCount, 0);
    a.tick(40000);
    Test.assert(a.missing);
    a.stop();
    return true;
}
(:test)
function testFeatureContract(logger) {
    var s = new SensorCollector();
    var f = new FeatureCollector();
    var empty = f.evaluate(s, 0);
    Test.assert(!empty[:complete]);
    Test.assert(empty[:hrMean] == null);
    Test.assert(empty[:rmssd] == null);
    Test.assert(new ModelAdapter().evaluate(empty)[:riskScore] == null);
    f.restartBaseline(0);
    for (var i = 1; i <= 300; i += 1) {
        s.hr = 60; s.hrAt = i*1000; s.accelAt = i*1000;
        s.accelN = 25; s.accelSum = 25000.0; s.accelSq = 25000000.0; s.stillN = 25;
        f.add(s, i*1000);
    }
    Test.assertEqual(f.baseline, 60.0);
    Test.assertEqual(f.points.size(), 60);
    var good = f.evaluate(s, 300000);
    Test.assert(good[:complete]);
    Test.assertEqual(good[:hrMean], 60.0);
    Test.assertEqual(good[:hrStd], 0.0);
    Test.assertEqual(good[:hrSlope], 0.0);
    Test.assertEqual(good[:hrBaselineDelta], 0.0);
    Test.assertEqual(good[:accelMean], 1000.0);
    Test.assertEqual(good[:accelStd], 0.0);
    Test.assertEqual(good[:stillFraction], 1.0);
    Test.assert(good[:rmssd] == null);
    Test.assertEqual(new ModelAdapter().evaluate(good)[:status], :model_not_connected);
    Test.assert(!f.evaluate(s, 304000)[:complete]);
    f.restartBaseline(305000);
    Test.assert(f.baseline == null);
    return true;
}
(:test)
function testSlopeAndMissingCoverage(logger) {
    var s = new SensorCollector(); var f = new FeatureCollector(); f.baseline = 60.0;
    for (var i = 0; i < 60; i += 1) {
        s.hr = 60+i; s.hrAt = i*1000; s.accelAt = i*1000;
        s.accelN = 25; s.accelSum = 25000.0; s.accelSq = 25000000.0; s.stillN = 25;
        if (i < 7) { s.hr = null; s.hrAt = null; s.accelN = 0; }
        f.add(s, i*1000);
    }
    var result = f.evaluate(s, 59000);
    Test.assert(!result[:complete]);
    Test.assert((result[:hrSlope] - 1.0).abs() < 0.001);
    return true;
}
function testResult(score, now) as Dictionary {
    return { :riskScore => score, :status => :ready, :timestamp => now, :modelVersion => "unit-test" };
}

(:test)
function testReplayEndToEnd(logger) {
    var replay = new TestDataReplay(1000);
    var s = new SensorCollector(); var model = new ModelAdapter();
    var a = new AlertController(); a.signalEnabled = false;
    for (var i = 0; i < 18; i += 1) {
        var now = 1000 + i * Config.EVALUATION_MS;
        replay.applyVitals(s, now);
        var result = replay.result(model, now);
        a.evaluate(result, now);
        if (i == 0) { Test.assertEqual(s.hr, 72); Test.assertEqual(result[:riskScore], 0.28); Test.assertEqual(a.level, 0); }
        if (i == 3) { Test.assert(s.oxygen == null); Test.assert(s.coreFresh(now)); }
        if (i == 5) { Test.assertEqual(a.level, 0); }
        if (i == 6) { Test.assertEqual(a.level, 1); }
        if (i == 8) { Test.assertEqual(a.level, 2); a.acknowledge(now); }
        if (i == 9) { Test.assert(a.acknowledged); Test.assertEqual(a.level, 2); }
        if (i == 12) { Test.assert(!s.coreFresh(now)); Test.assert(s.hr == null); Test.assert(result[:riskScore] == null); Test.assertEqual(a.level, 2); }
        if (i == 15) { Test.assertEqual(a.level, 2); }
        if (i == 16) { Test.assertEqual(a.level, 0); }
    }
    replay.applyVitals(s, 91000);
    Test.assertEqual(s.hr, 72);
    Test.assertEqual(replay.result(model, 91000)[:riskScore], 0.28);
    return true;
}
