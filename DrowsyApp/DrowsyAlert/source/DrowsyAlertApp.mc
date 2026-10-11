import Toybox.Application;
import Toybox.Lang;
import Toybox.System;
import Toybox.Timer;
import Toybox.WatchUi;
class DrowsyAlertApp extends Application.AppBase {
    var sensors as SensorCollector; var features as FeatureCollector; var model as ModelAdapter; var alerts as AlertController; var ticker as Timer.Timer;
    var demo = null; var result as Dictionary;
    var lastFeatureTick = 0; var lastEvaluation = 0; var foreground = true;
    function initialize() {
        AppBase.initialize();
        sensors = new SensorCollector(); features = new FeatureCollector();
        model = new ModelAdapter(); alerts = new AlertController(); ticker = new Timer.Timer();
        result = { :riskScore => null, :status => :model_not_connected, :timestamp => 0, :modelVersion => "not-connected" };
    }
    function onStart(state as Dictionary?) as Void {
        var now = System.getTimer();
        features.restartBaseline(now); lastFeatureTick = now; lastEvaluation = now;
        sensors.start(); ticker.start(method(:tick), 500, true);
    }
    function tick() as Void {
        var now = System.getTimer();
        if (now - lastFeatureTick >= 1000) { features.add(sensors, now); lastFeatureTick = now; }
        if (now - lastEvaluation >= Config.EVALUATION_MS) { evaluateNow(now); }
        if ((demo == null && !sensors.coreFresh(now)) || now - result[:timestamp] > Config.RESULT_FRESH_MS) {
            alerts.invalidate(); result[:riskScore] = null; result[:status] = :insufficient_data;
        }
        alerts.tick(now);
        if (foreground) { WatchUi.requestUpdate(); }
    }
    function evaluateNow(now) {
        lastEvaluation = now;
        if (demo != null) {
            result = { :riskScore => demo, :status => :ready, :timestamp => now, :modelVersion => "DEMO" };
        } else {
            var f = features.evaluate(sensors, now);
            result = model.evaluate(f);
            if (!f[:complete]) { result[:riskScore] = null; result[:status] = :insufficient_data; }
        }
        if (!alerts.evaluate(result, now)) {
            result[:riskScore] = null;
            result[:timestamp] = now;
            if (result[:status] == :ready) { result[:status] = :insufficient_data; }
        }
    }
    function setDemo(score) {
        alerts.stop(); alerts = new AlertController(); demo = score;
        evaluateNow(System.getTimer()); alerts.tick(System.getTimer()); WatchUi.requestUpdate();
    }
    function live() {
        if (demo != null) { alerts.stop(); alerts = new AlertController(); }
        demo = null;
        evaluateNow(System.getTimer()); WatchUi.requestUpdate();
    }
    function restartBaseline() {
        features.restartBaseline(System.getTimer());
        if (demo == null) { evaluateNow(System.getTimer()); }
        WatchUi.requestUpdate();
    }
    function status(now) {
        if (alerts.level > 0) {
            if (demo == null && !sensors.coreFresh(now)) { return "Warning / data missing"; }
            return alerts.level == 2 ? "High risk - stop safely" : "Drowsiness warning";
        }
        if (demo != null) { return "DEMO - awaiting threshold"; }
        if (!sensors.coreFresh(now)) { return "Sensor data missing"; }
        if (features.baseline == null) { return "Collecting baseline"; }
        if (result[:status] == :model_not_connected) { return "Model not connected"; }
        if (result[:status] != :ready || result[:riskScore] == null) { return "Sensor data missing"; }
        if (result[:riskScore] >= Config.WARNING) { return "Warning - confirming"; }
        return "Low estimated risk";
    }
    function onStop(state as Dictionary?) as Void { ticker.stop(); alerts.stop(); sensors.stop(); }
    function getInitialView() as [Views] or [Views, InputDelegates] {
        return [new DrowsyAlertView(), new DrowsyAlertDelegate()];
    }
}
function getApp() as DrowsyAlertApp { return Application.getApp() as DrowsyAlertApp; }
