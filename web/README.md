# Connected local drowsiness dashboard

See [CONNECTION_GUIDE.md](../CONNECTION_GUIDE.md) for the complete watch/iPhone setup. From the repository root, install `web/requirements.txt` in Python 3.12, run `python run_demo.py --check`, then `python run_demo.py`. Open http://127.0.0.1:8777/. Use another `--port` or `--relay-port` when occupied.

The existing page now calls the actual watch gradient boosting model and video TCN, then the original fusion and LLM/fallback advisor. Both models load once at startup. A 22-feature video logistic regression benchmark remains available through the API and feature-file test. Model training and saved artifacts are unchanged.

The browser extracts geometric eye/mouth event features into the original 15 × 60 sequence. It calibrates geometry for 15 seconds, collects a 60-second window and updates on five-second UTC boundaries. Frames stay in browser memory; only numeric features reach Python. The old expression-score eye cues remain separate descriptive tiles. Live RGB transfer is experimental.

The full watch path is **DrowsyAlert → DrowsyRelay iPhone → authenticated Node relay → Python**. It aggregates genuine HR, motion, IBI and temperature into four required features. Null temperature uses the last real value within the session, with the original age shown; no first temperature or IBI is invented. Direct Bluetooth heart-rate scan remains an optional display source and cannot supply this model alone.

Fresh, aligned same-session model scores are averaged; the local advisor explains results without changing scores or alert actions. The gauge is an uncalibrated 0–100 model score, not a percentage chance or an accuracy metric. Missing data remains unavailable. Real watch/fused results and independent video alarms return through the original iPhone transport; delivery is unconfirmed until a watch receipt arrives.

The camera starts only through **Start camera** and browser permission. Model files selected for testing are processed in memory and do not enter live watch return. The existing pinned MediaPipe assets are bundled with source/license information. Inference does not download camera model assets.

The model server is loopback-only; only the authenticated transport relay binds to the LAN for the phone. Pairing details require an explicit local-page action. Logs contain numeric predictions, never frames or tokens. `--prepare-only` retains the separate mode with models intentionally unloaded.

See [API contracts](../docs/web_api.md) and [model transfer details](../phone-companion/MODEL_COMPATIBILITY.md). Physical watch pairing, genuine interval availability, camera permissions and alarm playback must be checked on the actual devices.
