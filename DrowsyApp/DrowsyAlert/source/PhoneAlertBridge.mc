import Toybox.Lang;
import Toybox.Communications;
import Toybox.System;
import Toybox.Time;
import Toybox.WatchUi;

// Foreground-only iPhone companion messages, separate from watch-model results.
class PhoneAlertBridge {
    var alerts as AlertController;
    var session as String;
    var lastSequence = -1;
    var lastAt = null;
    var lastAlertSequence = null;
    var lastModelSequence = null;
    var transportEnabled = true;
    var sendBusy = false;
    var sendAt = 0;
    var sendFailed = false;
    var pendingReply = null;
    var lastTelemetryAt = 0;
    var telemetrySequence = 0;
    var lastModelAt = null;
    var modelSink = null;
    var invalidModelSink = null;
    function initialize(token as String) { session = token; alerts = new AlertController(); }
    function start() {
        try { Communications.registerForPhoneAppMessages(method(:onMessage)); }
        catch (ex) { sendFailed = true; System.println("Phone message listener unavailable"); }
    }
    function stop() {
        alerts.stop();
        pendingReply = null;
        try { Communications.registerForPhoneAppMessages(null); } catch (ex) {}
    }
    function onMessage(msg as Communications.PhoneAppMessage) as Void {
        var reply = receive(msg.data, Time.now().value(), System.getTimer(), getApp().isTestMode());
        send(reply); WatchUi.requestUpdate();
    }
    function stringIs(value, expected as String) { return value instanceof String && value.equals(expected); }
    function rejectModel(data as Dictionary) {
        if (!stringIs(data["source"], "phone_relay") || !stringIs(data["type"], "model_result") || !stringIs(data["session"], session)) { return; }
        if (invalidModelSink != null) { invalidModelSink.invoke(); }
        else if (modelSink == null && !getApp().isTestMode()) { getApp().invalidateRemoteModelResult(); }
    }
    function receive(data, utc, now, testMode) as Dictionary {
        var reply = {"type" => "receipt", "protocol" => 1, "session" => session, "status" => "invalid"};
        if (!(data instanceof Dictionary)) { return reply; }
        if (data["protocol"] != 1 || (!stringIs(data["source"], "phone_video") && !stringIs(data["source"], "phone_relay"))) { return reply; }
        var stamp = data["sentAt"];
        if (!(stamp instanceof Number) || stamp > utc + 2 || utc - stamp > 10) {
            if (!testMode) { rejectModel(data); }
            reply["status"] = "stale"; return reply;
        }
        if (stringIs(data["type"], "hello")) {
            reply["type"] = "hello_reply"; reply["status"] = "ready";
            return reply;
        }
        if (!stringIs(data["session"], session)) { reply["status"] = "wrong_session"; return reply; }
        var seq = data["sequence"];
        if (!(seq instanceof Number) || seq < 0) { return reply; }
        reply["sequence"] = seq;
        if (seq <= lastSequence) { reply["status"] = "duplicate"; return reply; }
        var kind = data["type"];
        if (!stringIs(kind, "alert") && !stringIs(kind, "heartbeat") && !stringIs(kind, "clear") && !stringIs(kind, "model_result")) { return reply; }
        if (stringIs(kind, "model_result")) {
            if (!stringIs(data["source"], "phone_relay")) { return reply; }
            var state = data["status"];
            if (!stringIs(state, "ready") && !stringIs(state, "insufficient_data") && !stringIs(state, "model_not_connected")) { if (!testMode) { rejectModel(data); } return reply; }
            var score = data["riskScore"];
            if (stringIs(state, "ready") && (!(score instanceof Number || score instanceof Float || score instanceof Double) || score != score || score < 0 || score > 1)) { if (!testMode) { rejectModel(data); } return reply; }
            if (!stringIs(state, "ready") && score != null) { if (!testMode) { rejectModel(data); } return reply; }
            if (!(data["modelVersion"] instanceof String)) { return reply; }
            if (testMode) { reply["status"] = "test_mode"; return reply; }
            if (lastModelAt != null && now - lastModelAt < Config.EVALUATION_MS) { reply["status"] = "rate_limited"; return reply; }
            // Convert the original capture age, never renew an old inference timestamp.
            var translated = now - Config.max(0, utc - stamp) * 1000;
            var result = { :riskScore => score, :timestamp => translated, :modelVersion => data["modelVersion"],
                :status => stringIs(state, "ready") ? :ready : (stringIs(state, "insufficient_data") ? :insufficient_data : :model_not_connected) };
            lastSequence = seq; lastAt = now; lastModelAt = now;
            var accepted = modelSink != null ? modelSink.invoke(result) : getApp().acceptModelResult(result);
            if (accepted) { lastModelSequence = seq; }
            reply["status"] = accepted ? "accepted" : "insufficient_data";
            return reply;
        }
        var severity = data["severity"];
        if (stringIs(kind, "alert") && !stringIs(severity, "warning") && !stringIs(severity, "high")) { return reply; }
        // Never mix phone alarms with synthetic replay.
        if (testMode) { reply["status"] = "test_mode"; return reply; }
        lastSequence = seq; lastAt = now;
        if (stringIs(kind, "alert")) {
            lastAlertSequence = seq;
            alerts.triggerExternal(stringIs(severity, "high") ? 2 : 1, now);
            alerts.tick(now);
        } else if (stringIs(kind, "clear")) {
            alerts.stop(); alerts.level = 0; alerts.acknowledged = false;
        }
        reply["status"] = "accepted";
        return reply;
    }
    function fresh(now) { return lastAt != null && now - lastAt <= 15000; }
    function tick(now) {
        alerts.tick(now);
        if (sendBusy && now - sendAt >= 5000) { sendFailed = true; }
        if (pendingReply != null && !sendBusy) {
            var reply = pendingReply; pendingReply = null; send(reply);
        }
    }
    function acknowledge(now) {
        acknowledgeAll(now, false);
    }
    function acknowledgeAll(now, modelAcknowledged) {
        var cameraAcknowledged = alerts.acknowledge(now);
        if (!cameraAcknowledged && !modelAcknowledged) { return; }
        send({"protocol" => 1, "type" => "user_acknowledged", "session" => session,
            "sequence" => cameraAcknowledged ? lastAlertSequence : lastModelSequence,
            "modelSequence" => modelAcknowledged ? lastModelSequence : null,
            "cameraSequence" => cameraAcknowledged ? lastAlertSequence : null,
            "source" => cameraAcknowledged ? (modelAcknowledged ? "both" : "phone_video") : "watch_model"});
    }
    function sendTelemetry(sensors as SensorCollector, now, testMode) {
        // Receipts/acknowledgments have priority. Drop rather than queue telemetry.
        if (testMode || !transportEnabled || !fresh(now) || pendingReply != null || sendBusy ||
            now - lastTelemetryAt < Config.TELEMETRY_MS) { return; }
        lastTelemetryAt = now; telemetrySequence += 1;
        send(sensors.telemetry.packet(sensors, now, Time.now().value(), telemetrySequence, session));
    }
    function send(reply as Dictionary) {
        if (!transportEnabled) { return; }
        var now = System.getTimer();
        if (sendBusy) {
            // One bounded slot; preserve the user's acknowledgment over receipts.
            if (pendingReply == null || stringIs(reply["type"], "user_acknowledged")) { pendingReply = reply; }
            return;
        }
        sendBusy = true; sendAt = now;
        try { Communications.transmit(reply, null, new PhoneSendListener(self)); }
        catch (ex) { sendBusy = false; sendFailed = true; }
    }
    function label(now) {
        if (sendFailed) { return "PHONE: LINK ERROR"; }
        return fresh(now) ? "PHONE: CONNECTED" : "PHONE: NO RECENT SIGNAL";
    }
}
class PhoneSendListener extends Communications.ConnectionListener {
    var bridge as PhoneAlertBridge;
    function initialize(owner as PhoneAlertBridge) { ConnectionListener.initialize(); bridge = owner; }
    function onComplete() as Void { bridge.sendBusy = false; bridge.sendFailed = false; }
    function onError() as Void { bridge.sendBusy = false; bridge.sendFailed = true; }
}
