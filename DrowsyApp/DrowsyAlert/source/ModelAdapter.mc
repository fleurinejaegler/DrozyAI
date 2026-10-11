import Toybox.System;
import Toybox.Lang;
class ModelAdapter {
    function initialize() {}
    function evaluate(features as Dictionary) as Dictionary {
        return { :riskScore => null,
            :status => :model_not_connected,
            :timestamp => System.getTimer(), :modelVersion => "not-connected" };
    }
}
