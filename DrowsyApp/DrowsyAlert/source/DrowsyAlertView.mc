import Toybox.Graphics;
import Toybox.System;
import Toybox.WatchUi;
class DrowsyAlertView extends WatchUi.View {
    function initialize() { View.initialize(); }
    function onShow() as Void { getApp().foreground = true; }
    function onHide() as Void { getApp().foreground = false; }
    function line(dc, y, font, text, color) {
        dc.setColor(color, Graphics.COLOR_TRANSPARENT);
        dc.drawText(dc.getWidth()/2, y, font, text, Graphics.TEXT_JUSTIFY_CENTER);
    }
    function onUpdate(dc as Graphics.Dc) as Void {
        var app = getApp(); var now = System.getTimer(); var sensor = app.sensors; var alert = app.alerts;
        var h = dc.getHeight(); var color = Graphics.COLOR_LT_GRAY;
        if (alert.level == 2) { color = Graphics.COLOR_RED; }
        else if (alert.level == 1) { color = 0xFFB000; }
        else if (app.result[:status] == :ready && app.result[:riskScore] != null &&
                 app.result[:riskScore] < Config.WARNING) { color = Graphics.COLOR_GREEN; }
        else if (app.result[:status] == :ready && app.result[:riskScore] != null) { color = 0xFFB000; }
        var bg = alert.bright(now) ? Graphics.COLOR_RED : Graphics.COLOR_BLACK;
        dc.setColor(Graphics.COLOR_WHITE, bg); dc.clear();
        if (bg == Graphics.COLOR_RED) { color = Graphics.COLOR_WHITE; }
        line(dc, h*0.08, Graphics.FONT_SMALL, "DrowsyAlert", Graphics.COLOR_WHITE);
        line(dc, h*0.17, Graphics.FONT_XTINY, app.demo != null ? "DEMO - simulated risk" : "Foreground monitoring",
            bg == Graphics.COLOR_RED ? Graphics.COLOR_WHITE : (app.demo != null ? 0xFFCC00 : Graphics.COLOR_LT_GRAY));
        var heart = sensor.fresh(sensor.hrAt, now) ? sensor.hr.format("%d") : "--";
        line(dc, h*0.25, Graphics.FONT_LARGE, "HR: " + heart + " bpm", Graphics.COLOR_WHITE);
        var move = sensor.fresh(sensor.accelAt, now) ? sensor.movement.format("%.0f") : "--";
        line(dc, h*0.38, Graphics.FONT_XTINY, "Accel: " + move + " mg (incl. gravity)", Graphics.COLOR_WHITE);
        var oxygen = sensor.fresh(sensor.oxygenAt, now) ? sensor.oxygen.format("%d") + "%" : "--";
        var risk = app.result[:status] == :ready && app.result[:riskScore] != null ?
            (app.result[:riskScore]*100).format("%.0f") : "--";
        line(dc, h*0.46, Graphics.FONT_SMALL, "SpO2: " + oxygen + "   Risk: " + risk, color);
        if (alert.level > 0) {
            line(dc, h*0.57, alert.level == 2 ? Graphics.FONT_SMALL : Graphics.FONT_XTINY,
                alert.level == 2 ? "HIGH RISK" : "DROWSINESS ALERT", color);
            line(dc, h*0.66, Graphics.FONT_XTINY, "Stop safely and take a break.", Graphics.COLOR_WHITE);
            var state = alert.acknowledged ? "Acknowledged; elevated" : "START to acknowledge";
            if (app.demo == null && (alert.missing || !sensor.coreFresh(now))) { state = "Warning / data missing"; }
            line(dc, h*0.74, Graphics.FONT_XTINY, state, Graphics.COLOR_WHITE);
        } else {
            line(dc, h*0.60, Graphics.FONT_XTINY, app.status(now), color);
            if (app.demo == null && app.features.baseline == null) {
                line(dc, h*0.69, Graphics.FONT_XTINY,
                    "Baseline: " + app.features.baselineCount + "/" + Config.BASELINE_SECONDS + " valid s", Graphics.COLOR_LT_GRAY);
            }
        }
        line(dc, h*0.83, Graphics.FONT_XTINY, "MENU / BACK: exit", Graphics.COLOR_LT_GRAY);
    }
}
