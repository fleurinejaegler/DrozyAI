import Toybox.Lang;
import Toybox.System;
import Toybox.WatchUi;
class DrowsyAlertDelegate extends WatchUi.BehaviorDelegate {
    function initialize() { BehaviorDelegate.initialize(); }
    function onMenu() as Boolean {
        WatchUi.pushView(new Rez.Menus.MainMenu(), new DrowsyAlertMenuDelegate(), WatchUi.SLIDE_UP);
        return true;
    }
    function onSelect() as Boolean {
        getApp().acknowledgeAlerts(System.getTimer()); return true;
    }
    function onBack() as Boolean { return false; }
}
