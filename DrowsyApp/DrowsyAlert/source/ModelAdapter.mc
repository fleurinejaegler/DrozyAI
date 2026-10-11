import Toybox.System;
import Toybox.Lang;
class ModelAdapter {
    function initialize() {}
    // Shared result envelope for a local model or a future external receiver.
    // Call with the real inference timestamp; do not renew old results on receipt.
    function resultFromScore(score, timestamp, version) as Dictionary {
        return { :riskScore => score, :status => score == null ? :insufficient_data : :ready,
            :timestamp => timestamp, :modelVersion => version };
    }
    function evaluate(features as Dictionary) as Dictionary {
        return { :riskScore => null,
            :status => :model_not_connected,
            :timestamp => System.getTimer(), :modelVersion => "not-connected" };
    }
}
