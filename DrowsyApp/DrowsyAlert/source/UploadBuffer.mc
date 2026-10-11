import Toybox.Lang;
// Separate bounded raw buffers: the existing phone/model telemetry is unchanged.
class UploadBuffer {
    var recording = false;
    var heart as Array<Dictionary> = []; var acceleration as Array<Dictionary> = [];
    var ibi as Array<Dictionary> = []; var temperatures as Array<Dictionary> = [];
    var dropped as Dictionary = {"heart_rate"=>0, "accelerometer"=>0, "ibi"=>0, "temperature"=>0, "expired_batches"=>0};
    function initialize() {}
    function countRows(rows as Dictionary, kind) {
        if (kind.equals("accelerometer")) { return rows["x"].size(); }
        if (kind.equals("ibi")) { return rows["values_ms"].size(); }
        return 1;
    }
    function appendBounded(items as Array<Dictionary>, item as Dictionary, limit, kind) {
        if (!recording) { return items; }
        if (items.size() >= limit) {
            dropped[kind] += countRows(items[0], kind);
            items = items.slice(1, items.size());
        }
        items.add(item); return items;
    }
    function addHeart(now, value) {
        heart = appendBounded(heart, {"t"=>now, "v"=>value}, 32, "heart_rate");
    }
    function addTemperature(now, value, source, epoch) {
        temperatures = appendBounded(temperatures, {"t"=>now, "v"=>value,
            "source"=>source, "type"=>"unknown", "epoch_s"=>epoch}, 32, "temperature");
    }
    function addIntervals(values as Array?, now) {
        if (!recording) { return; }
        var rr = values == null ? [] : values.slice(0,values.size());
        if (rr.size() > 8) { dropped["ibi"] += rr.size() - 8; rr = rr.slice(0,8); }
        ibi = appendBounded(ibi, {"t"=>now, "values_ms"=>rr}, 32, "ibi");
    }
    function addAxes(xs as Array, ys as Array, zs as Array, stamps as Array?, now, rate) {
        if (!recording) { return; }
        var count = Config.min(xs.size(), Config.min(ys.size(), zs.size())).toNumber();
        var n = Config.min(count,25).toNumber();
        if (count > n) { dropped["accelerometer"] += count-n; }
        if (n == 0) { return; }
        var times = [];
        for (var i=0; i<n; i+=1) { times.add(stamps != null && i<stamps.size() ? stamps[i] : null); }
        acceleration = appendBounded(acceleration, {"t"=>now, "rate_hz"=>rate,
            "x"=>xs.slice(0,n), "y"=>ys.slice(0,n), "z"=>zs.slice(0,n), "sensor_ms"=>times}, 10, "accelerometer");
    }
    function reset() { heart=[]; acceleration=[]; ibi=[]; temperatures=[]; }
    function clearWithDrops() {
        dropped["heart_rate"] += heart.size(); dropped["temperature"] += temperatures.size();
        for (var i=0; i<acceleration.size(); i+=1) { dropped["accelerometer"] += countRows(acceleration[i],"accelerometer"); }
        for (var j=0; j<ibi.size(); j+=1) { dropped["ibi"] += countRows(ibi[j],"ibi"); }
        reset();
    }
    function packet(session, id, epoch, anchor, now, availability, limit) as Dictionary {
        var blocks = Config.min(limit,acceleration.size()).toNumber();
        var nh=Config.min(limit,heart.size()).toNumber();
        var nr=Config.min(limit,ibi.size()).toNumber();
        var nt=Config.min(limit,temperatures.size()).toNumber();
        var result = {"schema_version"=>1, "device"=>"garmin_forerunner_970", "session"=>session,
            "batch_id"=>id, "anchor_epoch_s"=>epoch, "anchor_watch_ms"=>anchor, "created_watch_ms"=>now,
            "heart_rate"=>heart.slice(0,nh), "accelerometer"=>acceleration.slice(0,blocks), "ibi"=>ibi.slice(0,nr),
            "temperature"=>temperatures.slice(0,nt), "availability"=>availability,
            "dropped"=>{"heart_rate"=>dropped["heart_rate"], "accelerometer"=>dropped["accelerometer"],
                "ibi"=>dropped["ibi"], "temperature"=>dropped["temperature"], "expired_batches"=>dropped["expired_batches"]}};
        heart=heart.slice(nh,heart.size()); ibi=ibi.slice(nr,ibi.size());
        temperatures=temperatures.slice(nt,temperatures.size()); acceleration=acceleration.slice(blocks,acceleration.size());
        return result;
    }
    function expire(packet as Dictionary) {
        dropped["expired_batches"] += 1;
        dropped["heart_rate"] += packet["heart_rate"].size();
        dropped["temperature"] += packet["temperature"].size();
        var axes = packet["accelerometer"] as Array<Dictionary>; var intervals = packet["ibi"] as Array<Dictionary>;
        for (var i=0; i<axes.size(); i+=1) { dropped["accelerometer"] += axes[i]["x"].size(); }
        for (var j=0; j<intervals.size(); j+=1) { dropped["ibi"] += intervals[j]["values_ms"].size(); }
    }
}
