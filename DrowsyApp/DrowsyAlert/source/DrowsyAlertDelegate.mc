import Toybox.Lang;
import Toybox.WatchUi;

class DrowsyAlertDelegate extends WatchUi.BehaviorDelegate {

    function initialize() {
        BehaviorDelegate.initialize();
    }

    function onMenu() as Boolean {
        WatchUi.pushView(new Rez.Menus.MainMenu(), new DrowsyAlertMenuDelegate(), WatchUi.SLIDE_UP);
        return true;
    }

}