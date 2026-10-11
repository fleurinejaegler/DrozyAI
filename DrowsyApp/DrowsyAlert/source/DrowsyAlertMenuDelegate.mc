import Toybox.Lang;
import Toybox.WatchUi;
class DrowsyAlertMenuDelegate extends WatchUi.MenuInputDelegate {
    function initialize() { MenuInputDelegate.initialize(); }
    function onMenuItem(item as Symbol) as Void {
        if (item == :test_warning) { getApp().setDemo(0.75); }
        else if (item == :test_high) { getApp().setDemo(0.95); }
        else if (item == :live) { getApp().live(); }
        else if (item == :baseline) { getApp().restartBaseline(); }
    }
}
