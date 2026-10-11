# DrozyAI

The existing watch gradient boosting model, video TCN/logistic benchmark, fusion, local LLM advisor and Garmin/iPhone relay are connected. See [CONNECTION_GUIDE.md](CONNECTION_GUIDE.md) for the runnable setup and device checks.

```sh
python3.12 -m venv .venv-demo
.venv-demo/bin/python -m pip install -r web/requirements.txt
.venv-demo/bin/python run_demo.py --check
.venv-demo/bin/python run_demo.py
```

Open http://127.0.0.1:8777/. If an older page is running there, use `--port 8778`; if relay port 8765 is occupied, also choose `--relay-port 8766`. Existing processes are not replaced.

Temperature carries the last real reading forward when a packet returns null, within the same watch session. Genuine IBI is required for watch inference; BPM is never converted into IBI. The 0–100 model score is uncalibrated and live Garmin/RGB transfer is experimental.

The optional `python web/app.py --prepare-only` mode remains available with models disabled. Its separate [preparation interfaces](realtime_backend/README.md) are retained for compatibility. Do not run its CLI sender alongside the connected demo.
