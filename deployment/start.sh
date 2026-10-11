#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${DROWSY_PHONE_URL:?Set DROWSY_PHONE_URL to http://YOUR_MAC_LAN_IP:8767}"
export LLM_BASE_URL="${LLM_BASE_URL:-http://127.0.0.1:11434/v1}"
export LLM_MODEL="${LLM_MODEL:-llama3.2:3b}"
export DROWSY_RELAY_BIND=127.0.0.1
export DROWSY_COMPUTE_LABEL=GX10
export LOKY_MAX_CPU_COUNT=4
exec .venv-gx10/bin/python -B run_demo.py --port 8778 --relay-port 8766
