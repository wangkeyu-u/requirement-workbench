#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import fastapi, uvicorn, httpx' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r backend/requirements.txt
fi
if [[ ! -d frontend/node_modules ]]; then
  (cd frontend && npm ci)
fi
if [[ -f backend/.env ]]; then
  set -a
  source backend/.env
  set +a
fi
workbench_frontend_port=${FRONTEND_PORT:-3000}
workbench_backend_port=${BACKEND_PORT:-8000}
for workbench_port in "$workbench_frontend_port" "$workbench_backend_port"; do
  if lsof -nP -iTCP:"$workbench_port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port $workbench_port is occupied. Use FRONTEND_PORT=3001 BACKEND_PORT=8001 bash scripts/dev.sh"
    exit 1
  fi
done
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port "$workbench_backend_port" &
backend_pid=$!
cleanup() { kill "$backend_pid" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
cd frontend
NEXT_PUBLIC_API_URL="http://localhost:$workbench_backend_port" npm run dev -- --hostname localhost --port "$workbench_frontend_port"
