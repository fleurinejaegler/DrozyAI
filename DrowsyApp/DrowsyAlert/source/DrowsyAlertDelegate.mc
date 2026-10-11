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
        getApp().alerts.acknowledge(System.getTimer()); WatchUi.requestUpdate(); return true;
    }
    function onBack() as Boolean { return false; }
}
