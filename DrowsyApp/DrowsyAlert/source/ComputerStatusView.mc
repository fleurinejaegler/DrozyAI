import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;
import Toybox.WatchUi;
class ComputerStatusView extends WatchUi.View {
    var alarmView as DrowsyAlertView;
    function initialize() { View.initialize(); alarmView=new DrowsyAlertView(); }
    function onLayout(dc as Graphics.Dc) as Void { alarmView.onLayout(dc); }
    function onShow() as Void { getApp().foreground=true; }
    function onHide() as Void { getApp().foreground=false; }
    function onUpdate(dc as Graphics.Dc) as Void {
        var app=getApp(); var s=app.sensors; var u=app.computer; var now=System.getTimer();
        if (app.alerts.signaling(now) || app.phone.alerts.signaling(now)) { alarmView.onUpdate(dc); return; }
        var available=s.uploadAvailability(now);
        dc.setColor(Graphics.COLOR_WHITE,Graphics.COLOR_BLACK); dc.clear();
        var lines=["DROWSINESS MONITOR", "HR: "+(available["heart_rate"].equals("receiving") ? s.hr.toString()+" bpm" : available["heart_rate"]),
            "Accel: "+available["accelerometer"]+" "+s.sampleRate.toString()+" Hz",
            "IBI: "+available["ibi"], "Temp: "+(!available["temperature"].equals("receiving") ? "--" : s.uploadTemperature.format("%.1f")+" C"),
            u.label(now), "Last upload: "+(u.lastUpload==null ? "never" : ((now-u.lastUpload)/1000).toNumber().toString()+"s ago"),
            app.isTestMode() ? "TEST: UPLOADS BLOCKED" : u.error,
            "Drops: "+s.uploadBuffer.dropped["accelerometer"].toString()+" accel | "+(u.batchMs/1000).toNumber().toString()+"s", "BACK: RETURN"];
        var step=dc.getHeight()/13; var top=step*2;
        for (var i=0; i<lines.size(); i+=1) {
            dc.drawText(dc.getWidth()/2,top+i*step,Graphics.FONT_XTINY,lines[i],Graphics.TEXT_JUSTIFY_CENTER);
        }
    }
}
class ComputerStatusDelegate extends WatchUi.BehaviorDelegate {
    function initialize() { BehaviorDelegate.initialize(); }
    function onSelect() as Boolean { getApp().acknowledgeAlerts(System.getTimer()); return true; }
    function onBack() as Boolean { WatchUi.popView(WatchUi.SLIDE_DOWN); return true; }
}
