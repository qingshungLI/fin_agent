#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$PWD/.venv/bin:$PATH"
mkdir -p artifacts/services
for port in 8000 5173; do
  if ss -ltn | awk '{print $4}' | grep -qE ":$port$"; then
    echo "Port $port is occupied; existing process is left unchanged."
    exit 1
  fi
done
nohup python -m uvicorn engine.api:app --host 127.0.0.1 --port 8000 > artifacts/services/api.log 2>&1 < /dev/null &
echo "$!" > artifacts/services/api.pid
nohup npm run dev -- --strictPort > artifacts/services/web.log 2>&1 < /dev/null &
echo "$!" > artifacts/services/web.pid
echo "Server loopback endpoints: API 127.0.0.1:8000, workbench 127.0.0.1:5173."
