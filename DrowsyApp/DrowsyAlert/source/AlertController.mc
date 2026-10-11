import Toybox.Attention;
import Toybox.Lang;
import Toybox.System;
class AlertController {
    var level = 0;
    var warningCount = 0;
    var recoveryCount = 0;
    var acknowledged = false;
    var started = null;
    var lastSignal = null;
    var lastAccepted = null;
    var reminderAt = null;
    var missing = false;
    var signalEnabled = true;
    function initialize() {}
    function begin(now) {
        started = now; lastSignal = null; acknowledged = false; reminderAt = null;
    }
    function invalidate() { warningCount = 0; recoveryCount = 0; missing = true; }
    function evaluate(result as Dictionary, now) {
        var score = result[:riskScore];
        var stamp = result[:timestamp];
        if (result[:status] != :ready || score == null ||
            !(score instanceof Lang.Number || score instanceof Lang.Float || score instanceof Lang.Double) ||
            score != score || score < 0 || score > 1 ||
            !(stamp instanceof Lang.Number) || stamp > now || now - stamp > Config.RESULT_FRESH_MS) {
            invalidate(); return false;
        }
        if (lastAccepted != null && stamp <= lastAccepted) { invalidate(); return false; }
        if (lastAccepted != null && stamp - lastAccepted > Config.RESULT_FRESH_MS) {
            warningCount = 0; recoveryCount = 0;
        }
        lastAccepted = stamp; missing = false;
        if (score >= Config.HIGH) {
            warningCount = 0; recoveryCount = 0;
            if (level != 2) { level = 2; begin(now); }
            else if (acknowledged && reminderAt != null && now >= reminderAt) { begin(now); }
        } else if (score >= Config.WARNING) {
            recoveryCount = 0; warningCount += 1;
            if (warningCount >= Config.CONSECUTIVE && level == 0) { level = 1; begin(now); }
        } else {
            warningCount = 0;
            if (score < Config.RECOVERY) {
                recoveryCount += 1;
                if (recoveryCount >= Config.CONSECUTIVE) {
                    level = 0; started = null; acknowledged = false; reminderAt = null;
                }
            } else { recoveryCount = 0; }
        }
        return true;
    }
    // Explicit phone-model decision, independent of watch sensors/score thresholds.
    function triggerExternal(requestedLevel, now) {
        lastAccepted = now; missing = false;
        if (requestedLevel > level) { level = requestedLevel; begin(now); }
        else if (acknowledged && reminderAt != null && now >= reminderAt) { begin(now); }
    }
    function acknowledge(now) {
        if (level == 0) { return false; }
        acknowledged = true; started = null; lastSignal = null;
        reminderAt = now + Config.REMINDER_MS;
        return true;
    }
    function flashing(now) {
        return started != null && !acknowledged && now - started < Config.FLASH_MS;
    }
    function bright(now) {
        return flashing(now) && ((now - started) / 500).toNumber() % 2 == 0;
    }
    function signaling(now) {
        return level > 0 && started != null && !acknowledged && now - started < Config.SIGNAL_MS;
    }
    function tick(now) {
        if (lastAccepted == null || now - lastAccepted > Config.RESULT_FRESH_MS) { invalidate(); }
        if (!signaling(now)) { return; }
        var signalInterval = level == 2 ? Config.HIGH_SIGNAL_INTERVAL_MS : Config.SIGNAL_INTERVAL_MS;
        if (lastSignal != null && now - lastSignal < signalInterval) { return; }
        lastSignal = now;
        if (!signalEnabled) { return; }
        try { if (Attention has :playTone) { Attention.playTone(level == 2 ? Attention.TONE_LOUD_BEEP : Attention.TONE_ALARM); } }
        catch (ex) { System.println("Alarm tone unavailable"); }
        try {
            if (Attention has :vibrate) {
                if (level == 2) {
                    Attention.vibrate([new Attention.VibeProfile(100, 400), new Attention.VibeProfile(0, 100),
                     new Attention.VibeProfile(100, 400), new Attention.VibeProfile(0, 100),
                     new Attention.VibeProfile(100, 400)]);
                } else {
                    Attention.vibrate([new Attention.VibeProfile(90, 350), new Attention.VibeProfile(0, 150),
                     new Attention.VibeProfile(90, 350)]);
                }
            }
        }
        catch (ex) { System.println("Vibration unavailable"); }
    }
    function stop() { started = null; lastSignal = null; }
}
