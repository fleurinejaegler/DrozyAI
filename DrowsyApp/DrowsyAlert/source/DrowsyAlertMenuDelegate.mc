import Toybox.Lang;
import Toybox.WatchUi;
class DrowsyAlertMenuDelegate extends WatchUi.MenuInputDelegate {
    function initialize() { MenuInputDelegate.initialize(); }
    function onMenuItem(item as Symbol) as Void {
        if (item == :test_replay) { getApp().replayTestData(); }
        else if (item == :live) { getApp().live(); }
        else if (item == :baseline) { getApp().restartBaseline(); }
        else if (item == :computer_status) { WatchUi.pushView(new ComputerStatusView(),new ComputerStatusDelegate(),WatchUi.SLIDE_UP); }
        else if (item == :computer_toggle) { getApp().computer.toggle(); }
        else if (item == :computer_cadence) { getApp().computer.toggleCadence(); }
        else if (item == :computer_endpoint || item == :computer_token) {
            var field = item == :computer_endpoint ? :endpoint : :token;
            var initial = field == :endpoint ? getApp().computer.endpoint : "";
            WatchUi.pushView(new WatchUi.TextPicker(initial),new ComputerSetupDelegate(field),WatchUi.SLIDE_UP);
        }
    }
}
