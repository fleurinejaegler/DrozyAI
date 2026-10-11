import Toybox.Application;
import Toybox.Attention;
import Toybox.Lang;
import Toybox.System;
import Toybox.Time;
import Toybox.Timer;
import Toybox.WatchUi;
class DrowsyAlertApp extends Application.AppBase {
    var sensors as SensorCollector; var features as FeatureCollector; var model as ModelAdapter; var alerts as AlertController; var ticker as Timer.Timer;
    var phone as PhoneAlertBridge;
    var computer as ComputerUplink;
    var externalModel = false; var testData as TestDataReplay? = null; var demo = null; var result as Dictionary;
    var lastFeatureTick = 0; var lastEvaluation = 0; var foreground = true;
    var displayWakeBlocked = false;
    function initialize() {
        AppBase.initialize();
        sensors = new SensorCollector(); features = new FeatureCollector();
        model = new ModelAdapter(); alerts = new AlertController(); ticker = new Timer.Timer();
        computer = new ComputerUplink();
        phone = new PhoneAlertBridge(Time.now().value().toString() + "-" + System.getTimer().toString());
        phone.modelSink = method(:acceptModelResult);
        phone.invalidModelSink = method(:invalidateRemoteModelResult);
        result = { :riskScore => null, :status => :model_not_connected, :timestamp => 0, :modelVersion => "not-connected" };
    }
    function onStart(state as Dictionary?) as Void {
        var now = System.getTimer();
        features.restartBaseline(now); lastFeatureTick = now; lastEvaluation = now;
        computer.load();
        sensors.start(); phone.start(); ticker.start(method(:tick), 500, true);
    }
    function tick() as Void {
        var now = System.getTimer();
        if (testData != null) { testData.applyVitals(sensors, now); }
        if (testData == null && now - lastFeatureTick >= 1000) { features.add(sensors, now); lastFeatureTick = now; }
        if (now - lastEvaluation >= Config.EVALUATION_MS) { evaluateNow(now); }
        if ((demo == null && !sensors.coreFresh(now)) || now - result[:timestamp] > Config.RESULT_FRESH_MS) {
            alerts.invalidate(); result[:riskScore] = null; result[:status] = :insufficient_data;
        }
        alerts.tick(now); phone.tick(now);
        refreshAlarmDisplay(now);
        phone.sendTelemetry(sensors, now, isTestMode());
        sensors.pollUploadTemperature(now);
        computer.tick(sensors,now,isTestMode(),foreground);
        if (foreground) { WatchUi.requestUpdate(); }
    }
    function refreshAlarmDisplay(now) {
        // One display owner covers both alert sources without competing calls.
        var active = foreground && (alerts.signaling(now) || phone.alerts.signaling(now));
        if (!active) { displayWakeBlocked = false; return; }
        if (displayWakeBlocked || !(Attention has :backlight)) { return; }
        try { Attention.backlight(1.0); }
        catch (ex) {
            // Respect AMOLED protection; do not retry every half second after rejection.
            displayWakeBlocked = true;
            System.println("Alarm display brightness limited by device");
        }
    }
    function evaluateNow(now) {
        lastEvaluation = now;
        if (externalModel && !isTestMode()) { return; }
        if (testData != null) {
            result = testData.result(model, now);
        } else if (demo != null) {
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
    // Future receiver integration hook. Payload uses ModelAdapter's result envelope.
    // The receiver must translate capture time to this watch's monotonic milliseconds.
    function acceptModelResult(payload as Dictionary) {
        if (isTestMode()) { return false; }
        var now = System.getTimer();
        if (!payload.hasKey(:riskScore) || !payload.hasKey(:status) ||
            !payload.hasKey(:timestamp) || !payload.hasKey(:modelVersion)) { return false; }
        externalModel = true;
        if (!sensors.coreFresh(now)) {
            alerts.invalidate();
            result = model.resultFromScore(null, now, payload[:modelVersion]);
            WatchUi.requestUpdate(); return false;
        }
        var accepted = alerts.evaluate(payload, now);
        result = accepted ? payload : { :riskScore => null, :timestamp => payload[:timestamp],
            :status => payload[:status] == :ready ? :insufficient_data : payload[:status], :modelVersion => payload[:modelVersion] };
        alerts.tick(now); WatchUi.requestUpdate(); return accepted;
    }
    function invalidateRemoteModelResult() {
        externalModel = true; alerts.invalidate();
        result[:riskScore] = null; result[:status] = :insufficient_data;
    }
    function displayAlerts() as AlertController {
        return phone.alerts.level >= alerts.level && phone.alerts.level > 0 ? phone.alerts : alerts;
    }
    function phoneAlertVisible() { return phone.alerts.level > 0 && phone.alerts.level >= alerts.level; }
    function acknowledgeAlerts(now) {
        var modelAcknowledged = alerts.acknowledge(now);
        phone.acknowledgeAll(now, modelAcknowledged && externalModel && !isTestMode()); WatchUi.requestUpdate();
    }
    function isTestMode() { return demo != null || testData != null; }
    function connectionLabel(now) {
        return WebsiteConfig.USE_PHONE_RELAY ? phone.label(now) : computer.label(now);
    }
    function replayTestData() {
        phone.alerts.stop(); phone.alerts.level = 0;
        externalModel = false; sensors.stop(); sensors = new SensorCollector();
        alerts.stop(); alerts = new AlertController(); demo = null;
        var now = System.getTimer();
        testData = new TestDataReplay(now);
        testData.applyVitals(sensors, now); evaluateNow(now);
        alerts.tick(now); WatchUi.requestUpdate();
    }
    function setDemo(score) {
        if (testData != null) { live(); }
        alerts.stop(); alerts = new AlertController(); demo = score;
        evaluateNow(System.getTimer()); alerts.tick(System.getTimer()); WatchUi.requestUpdate();
    }
    function live() {
        if (isTestMode()) { alerts.stop(); alerts = new AlertController(); }
        if (testData != null) {
            testData = null; sensors = new SensorCollector(); sensors.start();
            features.restartBaseline(System.getTimer()); lastFeatureTick = System.getTimer();
        }
        demo = null; externalModel = false;
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
        if (testData != null) { return "TEST DATA REPLAY"; }
        if (externalModel) {
            if (result[:status] == :ready) { return result[:riskScore] >= Config.WARNING ? "Warning - confirming" : "Low estimated risk"; }
            return result[:status] == :model_not_connected ? "Model not connected" : "Sensor data missing";
        }
        if (features.baseline == null) { return "Collecting baseline"; }
        if (result[:status] == :model_not_connected) { return "Model not connected"; }
        if (result[:status] != :ready || result[:riskScore] == null) { return "Sensor data missing"; }
        if (result[:riskScore] >= Config.WARNING) { return "Warning - confirming"; }
        return "Low estimated risk";
    }
    function onStop(state as Dictionary?) as Void { ticker.stop(); computer.cancel(); alerts.stop(); phone.stop(); sensors.stop(); }
    function getInitialView() as [Views] or [Views, InputDelegates] {
        return [new DrowsyAlertView(), new DrowsyAlertDelegate()];
    }
}
function getApp() as DrowsyAlertApp { return Application.getApp() as DrowsyAlertApp; }
