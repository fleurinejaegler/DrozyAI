import Toybox.Graphics;
import Toybox.Math;
import Toybox.Lang;
import Toybox.System;
import Toybox.WatchUi;

class DrowsyAlertView extends WatchUi.View {
    var fonts as Lang.Dictionary = {};
    var scale = 1.0;
    function initialize() { View.initialize(); }
    function onShow() as Void { getApp().foreground = true; }
    function onHide() as Void { getApp().foreground = false; }
    function onLayout(dc as Graphics.Dc) as Void {
        scale = dc.getWidth() / 454.0;
        // Explicit pixel heights avoid device-dependent oversized built-in fonts.
        var sizes = [13, 15, 17, 22, 26, 29, 32, 88, 100];
        for (var i = 0; i < sizes.size(); i += 1) {
            var base = sizes[i] >= 88 ? Graphics.FONT_NUMBER_HOT : Graphics.FONT_MEDIUM;
            var f = Graphics.getVectorFont({:font => base,
                :scale => sizes[i] * scale / dc.getFontHeight(base).toFloat()});
            fonts[sizes[i]] = f == null ? Graphics.FONT_SMALL : f;
        }
    }
    function text(dc, x, y, size, value, color) {
        dc.setColor(color, Graphics.COLOR_TRANSPARENT);
        dc.drawText(x * scale, y * scale - dc.getFontHeight(fonts[size]) / 2,
            fonts[size], value, Graphics.TEXT_JUSTIFY_CENTER);
    }
    function gauge(dc, risk, accent, muted) {
        // Twelve annular segments, with a gap at the bottom for the vitals.
        for (var i = 0; i < 12; i += 1) {
            var points = [];
            var start = (155 + i * 230.0 / 12 + 1.5) * Math.PI / 180;
            var end = (155 + (i + 1) * 230.0 / 12 - 1.5) * Math.PI / 180;
            for (var j = 0; j <= 4; j += 1) {
                var a = start + (end - start) * j / 4;
                points.add([(227 + 210 * Math.cos(a)) * scale, (227 + 210 * Math.sin(a)) * scale]);
            }
            for (var k = 4; k >= 0; k -= 1) {
                var b = start + (end - start) * k / 4;
                points.add([(227 + 184 * Math.cos(b)) * scale, (227 + 184 * Math.sin(b)) * scale]);
            }
            dc.setColor(risk != null && i < (risk * 12).toNumber() ? accent : muted, Graphics.COLOR_TRANSPARENT);
            dc.fillPolygon(points);
        }
    }
    function heart(dc, x, y, color) {
        dc.setColor(color, Graphics.COLOR_TRANSPARENT);
        dc.fillCircle((x - 7) * scale, (y - 4) * scale, 9 * scale);
        dc.fillCircle((x + 7) * scale, (y - 4) * scale, 9 * scale);
        dc.fillPolygon([[(x - 15) * scale, (y - 1) * scale],
            [(x + 15) * scale, (y - 1) * scale], [x * scale, (y + 17) * scale]]);
    }
    function triangle(dc, y, color, background) {
        dc.setColor(color, Graphics.COLOR_TRANSPARENT);
        dc.fillPolygon([[227 * scale, (y - 33) * scale],
            [180 * scale, (y + 33) * scale], [274 * scale, (y + 33) * scale]]);
        dc.setColor(background, Graphics.COLOR_TRANSPARENT);
        dc.fillRectangle(223 * scale, (y - 15) * scale, 8 * scale, 29 * scale);
        dc.fillCircle(227 * scale, (y + 25) * scale, 5 * scale);
    }
    function alertWaves(dc, color) {
        dc.setColor(color, Graphics.COLOR_TRANSPARENT);
        dc.setPenWidth(3 * scale);
        for (var side = -1; side <= 1; side += 2) {
            for (var ring = 0; ring < 3; ring += 1) {
                var radius = 58 + ring * 12;
                for (var step = -3; step < 3; step += 1) {
                    var a = step * 0.18;
                    var b = (step + 1) * 0.18;
                    dc.drawLine((227 + side * radius * Math.cos(a)) * scale, (139 + radius * Math.sin(a)) * scale,
                        (227 + side * radius * Math.cos(b)) * scale, (139 + radius * Math.sin(b)) * scale);
                }
            }
        }
        dc.setPenWidth(1);
    }
    function score(dc, value, y, color) {
        var large = fonts[88];
        var small = fonts[26];
        var leftWidth = dc.getTextWidthInPixels(value, large);
        var rightWidth = dc.getTextWidthInPixels("/100", small);
        var left = (dc.getWidth() - leftWidth - rightWidth - 5 * scale) / 2;
        dc.setColor(color, Graphics.COLOR_TRANSPARENT);
        dc.drawText(left, y * scale - dc.getFontHeight(large) / 2, large, value, Graphics.TEXT_JUSTIFY_LEFT);
        dc.drawText(left + leftWidth + 5 * scale, (y + 22) * scale - dc.getFontHeight(small) / 2,
            small, "/100", Graphics.TEXT_JUSTIFY_LEFT);
    }
    function onUpdate(dc as Graphics.Dc) as Void {
        var app = getApp();
        var now = System.getTimer();
        var sensor = app.sensors;
        var alert = app.displayAlerts();
        var phoneAlert = app.phoneAlertVisible();
        var risk = app.result[:status] == :ready && now - app.result[:timestamp] <= Config.RESULT_FRESH_MS ? app.result[:riskScore] : null;
        var value = risk == null ? "--" : (risk * 100).format("%.0f");
        var high = alert.level == 2;
        var warning = alert.level == 1 || (risk != null && risk >= Config.WARNING);
        var flashing = alert.flashing(now);
        var bg = high ? 0xFF0808 : (warning ? 0xFFDD00 : Graphics.COLOR_BLACK);
        if (flashing) { bg = alert.bright(now) ? 0xFF0808 : Graphics.COLOR_BLACK; }
        var fg = warning && !high && !flashing ? Graphics.COLOR_BLACK : Graphics.COLOR_WHITE;
        var accent = warning || high ? fg : 0x00D9E8;
        var muted = warning && !flashing ? 0x948100 : 0x354047;
        dc.setColor(fg, bg);
        dc.clear();
        var hr = sensor.hr != null && sensor.fresh(sensor.hrAt, now) ? sensor.hr.format("%d") : "--";
        var o2 = sensor.oxygen != null && sensor.fresh(sensor.oxygenAt, now) ? sensor.oxygen.format("%d") + "%" : "--";
        var move = sensor.movement != null && sensor.fresh(sensor.accelAt, now) ? sensor.movement.format("%.0f") : "--";
        if (high || warning) {
            if (!high) { gauge(dc, risk, accent, muted); }
            triangle(dc, 139, fg, bg);
            if (high) { alertWaves(dc, fg); }
            score(dc, value, 222, fg);
            if (phoneAlert) { text(dc, 227, 266, 13, "WATCH RISK SCORE", fg); }
            text(dc, 227, 294, 26, phoneAlert ? "PHONE CAMERA ALERT" : (high ? "HIGH DROWSINESS" : "DROWSINESS RISING"), fg);
            text(dc, 227, 329, 29, high ? "STOP SAFELY" : "TAKE A BREAK", fg);
            heart(dc, 155, 364, fg);
            text(dc, 240, 367, 29, hr + " bpm", fg);
            text(dc, 227, 393, 13, (app.isTestMode() ? "TEST | " : "") + (phoneAlert && !app.phone.fresh(now) ? "PHONE SIGNAL STALE" : (!sensor.coreFresh(now) ? "SENSOR DATA MISSING" : "SpO2 " + o2 + "   Move " + move + " mg")), fg);
            text(dc, 227, 414, 13, alert.acknowledged ? "ACKNOWLEDGED - ELEVATED" : "START: ACKNOWLEDGE", fg);
        } else {
            gauge(dc, risk, accent, muted);
            text(dc, 227, 191, 100, value, fg);
            text(dc, 227, 254, 26, "/100", 0xAAB7BC);
            text(dc, 227, 290, risk == null ? 17 : 29, risk == null ? app.status(now) : (risk >= Config.WARNING ? "CONFIRMING" : "LOW"), risk == null ? 0xAAB7BC : accent);
            heart(dc, 148, 333, 0xFF3150);
            text(dc, 240, 336, 32, hr + " bpm", fg);
            text(dc, 227, 368, 15, app.isTestMode() ? "TEST - SIMULATED DATA" : "HEART RATE", 0xAAB7BC);
            text(dc, 227, 392, 15, "SpO2 " + o2 + "   Move " + move + " mg", 0xAAB7BC);
            text(dc, 227, 414, 13, app.isTestMode() ? "MENU: OPTIONS" : app.connectionLabel(now), 0xAAB7BC);
        }
    }
}
