import Toybox.Math;
import Toybox.Lang;
class FeatureCollector {
    var points as Array<Dictionary> = [];
    var lastHrAt = null;
    var baseline = null;
    var baselineStart = null;
    var baselineCount = 0;
    var baselineSum = 0.0;
    function initialize() {}
    function restartBaseline(now) {
        baseline = null; baselineStart = now; baselineCount = 0; baselineSum = 0.0;
        points = []; lastHrAt = null;
    }
    function add(sensors as SensorCollector, now) {
        var point = sensors.take(now, lastHrAt);
        lastHrAt = sensors.hrAt;
        points.add(point);
        while (points.size() > Config.WINDOW_SECONDS ||
               (points.size() > 0 && now - points[0][:t] >= Config.WINDOW_SECONDS * 1000)) {
            points = points.slice(1, points.size());
        }
        if (baselineStart == null) { baselineStart = now; }
        if (baseline == null) {
            if (point[:hr] != null && point[:n] >= sensors.sampleRate * 0.8) {
                baselineCount += 1; baselineSum += point[:hr];
            }
            if (now - baselineStart >= Config.BASELINE_SECONDS * 1000) {
                if (baselineCount >= Config.BASELINE_SECONDS * Config.COVERAGE) {
                    baseline = baselineSum / baselineCount;
                } else { baselineStart = now; baselineCount = 0; baselineSum = 0.0; }
            }
        }
    }
    function evaluate(sensors as SensorCollector, now) as Dictionary {
        var n = 0; var sum = 0.0; var sq = 0.0;
        var tx = 0.0; var txx = 0.0; var txy = 0.0;
        var an = 0; var asum = 0.0; var asq = 0.0; var still = 0;
        var accelBuckets = 0; var rrSq = 0.0; var rrPairs = 0;
        for (var i = 0; i < points.size(); i += 1) {
            var p = points[i];
            if (p[:hr] != null) {
                var h = p[:hr]; var t = (p[:t] - points[0][:t]) / 1000.0;
                n += 1; sum += h; sq += h*h; tx += t; txx += t*t; txy += t*h;
            }
            if (p[:n] >= sensors.sampleRate * 0.8) {
                accelBuckets += 1; an += p[:n]; asum += p[:sum]; asq += p[:sq]; still += p[:still];
            }
            rrSq += p[:rrSq]; rrPairs += p[:rrPairs];
        }
        var hrMean = n > 0 ? sum/n : null;
        var accelMean = an > 0 ? asum/an : null;
        var denom = n*txx - tx*tx;
        var full = points.size() >= Config.WINDOW_SECONDS * Config.COVERAGE &&
            now - points[0][:t] >= (Config.WINDOW_SECONDS - 1) * 1000 &&
            n >= Config.WINDOW_SECONDS * Config.COVERAGE &&
            accelBuckets >= Config.WINDOW_SECONDS * Config.COVERAGE &&
            sensors.coreFresh(now) && baseline != null;
        return { :complete => full, :timestamp => now, :schema => "candidate-v1",
            :hrMean => hrMean,
            :hrStd => n > 1 ? Math.sqrt(Config.max(0.0, sq/n - hrMean*hrMean)) : null,
            :hrSlope => n > 1 && denom > 0 ? (n*txy - tx*sum)/denom : null,
            :hrBaselineDelta => hrMean != null && baseline != null ? hrMean-baseline : null,
            :accelMean => accelMean,
            :accelStd => an > 1 ? Math.sqrt(Config.max(0.0, asq/an - accelMean*accelMean)) : null,
            :stillFraction => an > 0 ? still.toFloat()/an : null,
            :rmssd => rrPairs >= 20 && sensors.fresh(sensors.rrAt, now) ? Math.sqrt(rrSq/rrPairs) : null,
            :hrCoverage => n.toFloat()/Config.WINDOW_SECONDS,
            :accelCoverage => accelBuckets.toFloat()/Config.WINDOW_SECONDS };
    }
}
