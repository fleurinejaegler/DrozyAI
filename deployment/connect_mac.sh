#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ne 1 ]; then
  echo "Usage: $0 USER@GX10_IP" >&2
  exit 1
fi
exec ssh -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -N \
  -L 127.0.0.1:8779:127.0.0.1:8778 \
  -L 0.0.0.0:8767:127.0.0.1:8766 "$1"
