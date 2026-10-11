import Toybox.Communications;
import Toybox.Lang;
import Toybox.Math;
import Toybox.System;
import Toybox.Time;
class ComputerUplink {
    var endpoint as String = WebsiteConfig.UPLOAD_URL;
    var token as String = WebsiteConfig.API_TOKEN;
    var enabled = true;
    var websiteReady = WebsiteConfig.READY && !WebsiteConfig.USE_PHONE_RELAY;
    var session; var anchorEpoch; var anchorWatch;
    var sequence = 0; var pending as Dictionary? = null; var busy = false;
    var requestAt = 0; var nextAttempt = 0; var retryMs = 5000;
    var lastUpload = null; var lastUploadEpoch = null; var error = "";
    var generation = 0; var transportEnabled = true;
    var batchMs = WebsiteConfig.UPLOAD_INTERVAL_MS;
    function initialize() {
        anchorWatch = System.getTimer(); anchorEpoch = Time.now().value();
        session = anchorEpoch.toString()+"-"+Math.rand().toString();
    }
    function load() {
        // Build configuration is authoritative, including on previously installed watches.
        // Old manually entered URLs, tokens and OFF settings must not override it.
        endpoint=WebsiteConfig.UPLOAD_URL; token=WebsiteConfig.API_TOKEN;
        enabled=true; websiteReady=WebsiteConfig.READY && !WebsiteConfig.USE_PHONE_RELAY;
        batchMs=WebsiteConfig.UPLOAD_INTERVAL_MS;
    }
    function cancel() {
        generation+=1;
        if (busy && transportEnabled) { try { Communications.cancelAllRequests(); } catch (ex) {} }
        busy=false;
    }
    function tick(sensors as SensorCollector, now, testMode, foreground) {
        var collecting = enabled && websiteReady && endpoint.length()>0 && token.length()>=12 && !testMode;
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
        if (!websiteReady) { return "WEBSITE: COMING SOON"; }
        if (!enabled) { return "COMPUTER: OFF"; }
        if (endpoint.length()==0 || token.length()<12) { return "COMPUTER: SETUP NEEDED"; }
        if (connected(now)) { return "COMPUTER: CONNECTED"; }
        return busy ? "COMPUTER: UPLOADING" : "COMPUTER: RETRYING";
    }
}
