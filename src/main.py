"""DrozyAI entry point -- minimal end-to-end placeholder."""


def capture():
    print("[1] Capture: watch + webcam (placeholder)")
    return {"hr": 72, "temp": 36.5, "motion": 0.1}


def extract_features(raw):
    print("[2] Feature extraction (placeholder)")
    return {"mean_hr": raw["hr"]}


def predict(features):
    print("[3] Prediction (placeholder)")
    return 0.3


def advise(risk):
    print("[4] Nemotron advice (placeholder)")
    return "continue" if risk < 0.4 else "take a break"


if __name__ == "__main__":
    raw = capture()
    feats = extract_features(raw)
    risk = predict(feats)
    action = advise(risk)
    print(f"\nRisk: {risk:.2f} -> Advice: {action}")
