import Toybox.Test;
import Toybox.Lang;
import Toybox.Math;
(:test)
function testContinuousRemoteScore(logger) {
    var app = getApp();
    var now = Toybox.System.getTimer();
    app.alerts.signalEnabled = false;
    Test.assert(app.acceptModelResult(testResult(0.42, now-1)));
    Test.assertEqual(app.lastValidRisk, 0.42);
    app.invalidateRemoteModelResult();
    Test.assert(app.result[:riskScore] == null);
    Test.assertEqual(app.lastValidRisk, 0.42);
    Test.assertEqual(app.lastScoreAge(now + 12000), 12);
    Test.assert(!app.acceptModelResult(testResult(99, now)));
    Test.assertEqual(app.lastValidRisk, 0.42);
    Test.assert(app.acceptModelResult(testResult(0, now)));
    Test.assertEqual(app.lastValidRisk, 0);
    app.live();
    Test.assert(app.lastValidRisk == null);
    return true;
}
(:test)
class TestRemoteScoreSink {
    var alerts as AlertController;
    var received as Dictionary? = null;
    var now = 0;
    function initialize() { alerts = new AlertController(); alerts.signalEnabled = false; }
    function accept(result as Dictionary) { received = result; return alerts.evaluate(result, now); }
    function invalidate() { alerts.invalidate(); }
}
(:test)
function testRemoteModelBridge(logger) {
    var bridge = new PhoneAlertBridge("relay-session"); bridge.transportEnabled = false;
    var sink = new TestRemoteScoreSink(); bridge.modelSink = sink.method(:accept);
    bridge.invalidModelSink = sink.method(:invalidate);
    var msg = {"protocol"=>1,"source"=>"phone_relay","type"=>"model_result","session"=>"relay-session",
        "sequence"=>1,"sentAt"=>1000,"status"=>"ready","riskScore"=>0.75,"modelVersion"=>"website-v1"};
    sink.now = 10000;
    Test.assert(bridge.receive(msg,1001,10000,false)["status"].equals("accepted"));
    var received = sink.received as Dictionary;
    Test.assertEqual(received[:timestamp],9000); Test.assertEqual(sink.alerts.level,0);
    msg["sequence"] = 2; msg["sentAt"] = 1001;
    Test.assert(bridge.receive(msg,1001,11000,false)["status"].equals("rate_limited"));
    sink.now = 15000; msg["sentAt"] = 1005;
    Test.assert(bridge.receive(msg,1006,15000,false)["status"].equals("accepted"));
    sink.now = 20000; msg["sequence"] = 3; msg["sentAt"] = 1010;
    Test.assert(bridge.receive(msg,1011,20000,false)["status"].equals("accepted"));
    Test.assertEqual(sink.alerts.level,1);
    msg["sequence"] = 4; msg["riskScore"] = 95;
    Test.assert(bridge.receive(msg,1011,25000,false)["status"].equals("invalid"));
    Test.assert(sink.alerts.missing); Test.assertEqual(sink.alerts.warningCount,0);
    msg["riskScore"] = 0.95; msg["sentAt"] = 1015; sink.now = 25000;
    Test.assert(bridge.receive(msg,1016,25000,true)["status"].equals("test_mode"));
    Test.assert(bridge.receive(msg,1016,25000,false)["status"].equals("accepted"));
    Test.assertEqual(sink.alerts.level,2);
    Test.assert(bridge.receive(msg,1026,35000,false)["status"].equals("stale"));
    msg["sequence"] = 5; msg["sentAt"] = 1020; msg["riskScore"] = null; msg["status"] = "insufficient_data"; sink.now = 30000;
    Test.assert(bridge.receive(msg,1021,30000,false)["status"].equals("insufficient_data"));
    Test.assert(sink.alerts.missing); Test.assertEqual(sink.alerts.level,2);
    return true;
}
(:test)
function testTelemetry(logger) {
    var s = new SensorCollector(); var t = s.telemetry;
    var p = t.packet(s, 1000, 100, 1, "test-session");
    Test.assert(p["heartRateBpm"] == null);
    Test.assert(p["spo2Percent"] == null);
    Test.assert(p["temperatureC"] == null);
    Test.assert(p["accelerometer"] == null);
    Test.assert(p["gyroscope"] == null);
    Test.assert(p["hrvRmssdMs"] == null);
    s.hr = 72; s.hrAt = 1000; s.oxygen = 98; s.oxygenAt = 1000;
    s.temperature = 24.5; s.temperatureAt = 1000;
    var xs = []; var ys = []; var zs = [];
    for (var i=0; i<30; i+=1) { xs.add(i); ys.add(null); zs.add(1000); }
    t.acceleration = t.encodeAxes(xs, ys, zs, null, 25, "mg"); t.batchAt = 1000;
    p = t.packet(s, 1000, 100, 2, "test-session");
    Test.assertEqual(p["heartRateBpm"], 72);
    Test.assertEqual(p["temperatureC"], 24.5);
    var a = p["accelerometer"] as Dictionary;
    var x = a["x"] as Array; var y = a["y"] as Array;
    Test.assertEqual(x.size(), 25); Test.assert(y[0] == null);
    Test.assertEqual(a["truncated"], true);
    Test.assert(p["hrvRmssdMs"] == null); // HR alone never creates HRV.
    p = t.packet(s, 5000, 104, 3, "test-session");
    Test.assert(p["heartRateBpm"] == null); Test.assert(p["accelerometer"] == null);
    Test.assert(p["temperatureC"] == null); Test.assert(p["spo2Percent"] == null);
    for (var second=0; second<=60; second+=1) { t.addIntervals([second%2 == 0 ? 1000 : 1100], second*1000); }
    Test.assert((t.hrv(60000)-100.0).abs() < 0.01);
    Test.assert(t.hrv(65000) == null);
    t.addIntervals([1000], 65000); Test.assert(t.hrv(65000) == null);
    t.addIntervals([null, 1000], 66000); Test.assertEqual(t.beats.size(), 1);
    return true;
}
(:test)
function testAlarmCadence(logger) {
    var a = new AlertController(); a.signalEnabled = false;
    a.triggerExternal(1, 1000); a.tick(1000);
    a.tick(3500); Test.assertEqual(a.lastSignal, 1000);
    a.tick(4000); Test.assertEqual(a.lastSignal, 4000);
    a.triggerExternal(2, 4500); a.tick(4500);
    a.tick(5500); Test.assertEqual(a.lastSignal, 4500);
    a.tick(6000); Test.assertEqual(a.lastSignal, 6000);
    Test.assert(a.signaling(34499)); Test.assert(!a.signaling(34500));
    a.tick(34500); Test.assertEqual(a.lastSignal, 6000);
    a.acknowledge(35000); Test.assert(!a.signaling(35000));
    a.triggerExternal(2, 95000); Test.assert(a.signaling(95000));
    a.stop(); Test.assert(!a.signaling(95000));
    return true;
}
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

(:test)
function testPhoneAlerts(logger) {
    var b = new PhoneAlertBridge("watch-session");
    b.transportEnabled = false; b.alerts.signalEnabled = false;
    var message = {"protocol"=>1, "source"=>"phone_video", "type"=>"hello", "sentAt"=>1000};
    Test.assert(b.receive(message, 1000, 100, false)["status"].equals("ready"));
    message["type"] = "alert"; message["session"] = "watch-session";
    message["sequence"] = 1; message["severity"] = "warning";
    // No SensorCollector or watch-model score involved.
    Test.assert(b.receive(message, 1000, 100, false)["status"].equals("accepted"));
    Test.assertEqual(b.alerts.level, 1); Test.assert(b.alerts.flashing(100));
    Test.assert(b.receive(message, 1000, 200, false)["status"].equals("duplicate"));
    message["sequence"] = 2; message["severity"] = "high";
    b.receive(message, 1000, 500, false); Test.assertEqual(b.alerts.level, 2);
    b.acknowledge(600); Test.assert(b.alerts.acknowledged); Test.assert(!b.alerts.flashing(600));
    message["sequence"] = 3;
    b.receive(message, 1000, 1000, false); Test.assert(b.alerts.acknowledged);
    message["sentAt"] = 1061; message["sequence"] = 4;
    b.receive(message, 1061, 61600, false); Test.assert(!b.alerts.acknowledged);
    message["sequence"] = 5; message["type"] = "clear";
    Test.assert(b.receive(message, 1080, 80000, false)["status"].equals("stale"));
    Test.assertEqual(b.alerts.level, 2);
    message["sentAt"] = 1080; message["session"] = "old-session";
    Test.assert(b.receive(message, 1080, 80000, false)["status"].equals("wrong_session"));
    message["session"] = "watch-session";
    Test.assert(b.receive(message, 1080, 80000, true)["status"].equals("test_mode"));
    Test.assert(b.receive(message, 1080, 80000, false)["status"].equals("accepted"));
    Test.assertEqual(b.alerts.level, 0);
    Test.assert(b.fresh(80000)); Test.assert(!b.fresh(96000));
    Test.assert(b.receive("bad", 1080, 80000, false)["status"].equals("invalid"));
    message["type"] = "alert"; message["sequence"] = 6; message["severity"] = "bad";
    Test.assert(b.receive(message, 1080, 80000, false)["status"].equals("invalid"));
    return true;
}
