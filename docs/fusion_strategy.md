# Experimental score fusion

The default `max` rule takes the larger available component score. It can
raise a warning when either model has a high score. This is a prototype
choice; it has not been shown to improve safety, sensitivity or false alarms.

`weighted_average` uses `watch_weight * watch_score +
(1 - watch_weight) * facial_score`, with a default watch weight of 0.5.
Weights must lie in [0, 1]. The weighted result is not a calibrated probability,
and the components were not jointly calibrated or evaluated on matching held-out
people. A learned meta-classifier is intentionally not provided without an
appropriate labeled fusion dataset and participant-separated evaluation.

| Score | Display | `alert` |
|---|---|---|
| `< 0.4` | green | false |
| `>= 0.4` and `< 0.7` | orange / warning | false |
| `>= 0.7` | red | true |
| Both sources missing | unavailable | false |

The original pasted plan left exactly 0.7 ambiguous. This implementation
includes 0.7 in red and tests both boundaries. Here `alert` means **issue a
warning**, rather than the awake/alert class name. These threshold choices
have not been tuned or validated.

Missing sources are never replaced with zero. If one component is available,
its score is returned unchanged with the appropriate single-source mode; no
weighted dilution is applied. Non-finite, boolean, string and out-of-range
values are rejected. No sources means unavailable, never green.

The live eye-closure rule in the dashboard remains a separate experimental
indicator. Its 0.55 blendshape threshold and 0.8/1.5-second rules are not TCN
inputs or outputs. Garmin HR is displayed separately and does not affect that
live indicator. The saved watch model needs five measured features, four of
which this HR-only bridge cannot currently supply.

The small TCN's observed five-fold participant-separated mean balanced accuracy
was 56.93%, and mean drowsy recall was 40.76%, on 19 participants and 35 sessions.
It missed most drowsy windows at the tested 0.5 threshold. This was exploratory
cross-validation after earlier participants had been inspected, not a fresh
independent test. Overlapping windows are correlated. The shipped final model
was then fitted to all participants; its training scores are not validation.
The checkpoint uses class weighting, so its sigmoid is an uncalibrated score.
No live RGB-webcam transfer or real Garmin detection performance is established.

The integration preserves the teammate's watch predictor as a black box. It
does not endorse the predictor module's probability wording or its historical
cross-validation claims as evidence of live calibration. No watch training or
teammate-owned model changes occur here.

Before making detection claims: verify capture geometry and clocks, collect
independent labeled webcam/Garmin recordings, split by participant before
preprocessing, compare single-source and fused modes on the same held-out
people, evaluate missed drowsy events and false alarms over time, then choose
thresholds on development data only. A low score cannot establish driving safety.
