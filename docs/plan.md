# DrozyAI — Wearable Drowsiness Detection

## Goal
Detect driver drowsiness using a smartwatch + webcam, and give safety advice
via local AI (ASUS GX10 + Nemotron).

## Six stages
1. Capture: watch at 1 Hz + webcam at 10-15 fps
2. Features: 60s sliding window, 5s step, per-driver baseline normalization
3. Predict: gradient boosting baseline -> GRU -> isotonic calibration
4. Advise: Nemotron outputs stop / break / continue
5. Dashboard: threshold slider + missed-drowsy vs false-alarm curve
6. Driver app: traffic light + spoken alert + "I'm alert" button

## Deliverables
- [ ] Dataset and license confirmed
- [ ] Baseline + fused models with leave-one-driver-out splits
- [ ] Nemotron advisor running offline on the GX10
- [ ] Jury dashboard with threshold slider
- [ ] Driver app with traffic light and spoken alert
- [ ] Offline latency benchmark
- [ ] Demo video and write-up
- [ ] Feedback survey submitted
- [ ] GX10 returned in good condition
