import Toybox.Lang;
import Toybox.WatchUi;
class DrowsyAlertMenuDelegate extends WatchUi.MenuInputDelegate {
    function initialize() { MenuInputDelegate.initialize(); }
    function onMenuItem(item as Symbol) as Void {
        if (item == :test_replay) { getApp().replayTestData(); }
        else if (item == :live) { getApp().live(); }
        else if (item == :baseline) { getApp().restartBaseline(); }
        else if (item == :computer_status) { WatchUi.pushView(new ComputerStatusView(),new ComputerStatusDelegate(),WatchUi.SLIDE_UP); }
    }
}
