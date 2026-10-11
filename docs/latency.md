# DrozyAI Latency Benchmark

Measured with the network off, on a Mac (Apple Silicon).

| Stage | Time (ms) |
|---|---|
| Watch model inference | 25.27 |
| Vision model inference | 8.14 |
| Fusion | 0.01 |
| Advisor (LLM + rules) | 479.93 |
| **Total time-to-alert** | **513.36** |

Notes:
- Watch model: HistGradientBoostingClassifier (4 features)
- Vision model: HistGradientBoostingClassifier (11 features)
- Advisor: rule-based action + local LLM reason (Ollama, llama3.2:3b)
- All stages run locally on-device with no network access
