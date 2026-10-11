import Toybox.Application;
import Toybox.Communications;
import Toybox.Lang;
import Toybox.Math;
import Toybox.System;
import Toybox.Time;
class ComputerUplink {
    var endpoint as String = ""; var token as String = ""; var enabled = false;
    var session; var anchorEpoch; var anchorWatch;
    var sequence = 0; var pending as Dictionary? = null; var busy = false;
    var requestAt = 0; var nextAttempt = 0; var retryMs = 5000;
    var lastUpload = null; var lastUploadEpoch = null; var error = "";
    var generation = 0; var transportEnabled = true;
    var batchMs = 5000;
    function initialize() {
        anchorWatch = System.getTimer(); anchorEpoch = Time.now().value();
        session = anchorEpoch.toString()+"-"+Math.rand().toString();
    }
    function load() {
        try {
            var url = Application.Storage.getValue("computerEndpoint");
            var key = Application.Storage.getValue("computerToken");
            var active = Application.Storage.getValue("computerEnabled");
            var cadence = Application.Storage.getValue("computerBatchMs");
            if (url instanceof String) { endpoint=url; }
            if (key instanceof String) { token=key; }
            enabled = active == true;
            if (cadence instanceof Number && cadence >= 1000 && cadence <= 5000) { batchMs=cadence; }
        } catch (ex) { error="Settings unavailable"; }
    }
    function configure(which, value) {
        if (which == :endpoint) {
            if (value.length() < 9 || !value.substring(0,8).equals("https://")) { error="HTTPS URL required"; return false; }
            endpoint=value; Application.Storage.setValue("computerEndpoint",value);
        } else {
            if (value.length()<12) { error="Token needs 12+ characters"; return false; }
            token=value; Application.Storage.setValue("computerToken",value);
        }
        cancel(); lastUpload=null; error=""; nextAttempt=0; retryMs=5000;
        return true;
    }
    function toggle() {
        enabled=!enabled; Application.Storage.setValue("computerEnabled",enabled);
        if (!enabled) { cancel(); }
        nextAttempt=0;
    }
    function toggleCadence() {
        batchMs=batchMs==5000 ? 1000 : 5000;
        Application.Storage.setValue("computerBatchMs",batchMs);
    }
    function cancel() {
        generation+=1;
        if (busy && transportEnabled) { try { Communications.cancelAllRequests(); } catch (ex) {} }
        busy=false;
    }
    function tick(sensors as SensorCollector, now, testMode, foreground) {
        var collecting = enabled && endpoint.length()>0 && token.length()>=12 && !testMode;
        sensors.uploadBuffer.recording=collecting;
        if (!collecting) {
            if (busy) { cancel(); }
            if (pending!=null) { sensors.uploadBuffer.expire(pending); pending=null; }
            sensors.uploadBuffer.clearWithDrops(); return;
        }
        if (busy) {
            if (now-requestAt >= 30000) { cancel(); failure(now,"Request timed out"); }
            return;
        }
        if (!foreground || now<nextAttempt) { return; }
        if (pending!=null && now-pending["created_watch_ms"] >= 120000) {
            sensors.uploadBuffer.expire(pending); pending=null;
            System.println("Computer upload batch expired; dropped counts retained");
        }
        if (pending==null) {
            sequence+=1;
            pending=sensors.uploadBuffer.packet(session,sequence,anchorEpoch,anchorWatch,now,sensors.uploadAvailability(now),(batchMs/1000).toNumber());
        }
        busy=true; requestAt=now; generation+=1;
        if (!transportEnabled) { return; }
        try {
            Communications.makeWebRequest(endpoint,pending,{
                :method=>Communications.HTTP_REQUEST_METHOD_POST,
                :headers=>{"Content-Type"=>Communications.REQUEST_CONTENT_TYPE_JSON,"Authorization"=>"Bearer "+token},
                :responseType=>Communications.HTTP_RESPONSE_CONTENT_TYPE_JSON,
                :context=>generation},method(:onResponse));
        } catch (ex) { busy=false; failure(now,"Request unavailable"); }
    }
    function failure(now,message) {
        error=message; nextAttempt=now+retryMs; retryMs=Config.min(retryMs*2,60000).toNumber();
        System.println("Computer upload failed: "+message);
    }
    function onResponse(code as Number, data as Dictionary or String or Toybox.PersistedContent.Iterator or Null, context as Object) as Void {
        if (context != generation || !busy || pending==null) { return; }
        busy=false; var now=System.getTimer();
        if (code==200 && data instanceof Dictionary && data["status"] instanceof String &&
            (data["status"].equals("accepted") || data["status"].equals("duplicate")) &&
            data["session"] instanceof String && data["session"].equals(session) && data["batch_id"]==pending["batch_id"]) {
            lastUpload=now; lastUploadEpoch=Time.now().value(); pending=null;
            error=""; retryMs=5000; nextAttempt=Config.max(now,requestAt+batchMs).toNumber();
        } else { failure(now,"HTTP "+code.toString()); }
    }
    function connected(now) { return enabled && error.length()==0 && lastUpload!=null && now-lastUpload<=15000; }
    function label(now) {
        if (!enabled) { return "COMPUTER: OFF"; }
        if (endpoint.length()==0 || token.length()<12) { return "COMPUTER: SETUP NEEDED"; }
        if (connected(now)) { return "COMPUTER: CONNECTED"; }
        return busy ? "COMPUTER: UPLOADING" : "COMPUTER: RETRYING";
    }
}
