#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -x .venv/bin/python ]]; then
  echo "未找到 .venv，请先运行 bash scripts/dev.sh 安装后端依赖。" >&2
  exit 1
fi

smoke_dir="$(mktemp -d "${TMPDIR:-/tmp}/requirement-workbench-smoke.XXXXXX")"
smoke_db="$smoke_dir/smoke.sqlite3"
smoke_port="${SMOKE_BACKEND_PORT:-8761}"
backend_pid=""

cleanup() {
  if [[ -n "$backend_pid" ]]; then
    kill "$backend_pid" 2>/dev/null || true
    wait "$backend_pid" 2>/dev/null || true
  fi
  rm -rf "$smoke_dir"
}
trap cleanup EXIT INT TERM

DATABASE_PATH="$smoke_db" .venv/bin/python -m uvicorn backend.main:app \
  --host 127.0.0.1 --port "$smoke_port" >"$smoke_dir/backend.log" 2>&1 &
backend_pid=$!

ready="false"
for _ in {1..40}; do
  if curl -fsS "http://127.0.0.1:$smoke_port/api/health" >/dev/null 2>&1; then
    ready="true"
    break
  fi
  sleep 0.1
done
if [[ "$ready" != "true" ]]; then
  cat "$smoke_dir/backend.log" >&2
  echo "后端烟测服务未能启动。" >&2
  exit 1
fi

SMOKE_PORT="$smoke_port" .venv/bin/python - <<'PY'
import json
import os
from urllib.request import Request, urlopen

base = f"http://127.0.0.1:{os.environ['SMOKE_PORT']}"

def request(path: str, method: str = "GET"):
    with urlopen(Request(base + path, method=method), timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))

assert request("/api/health") == {"ok": True}
threads = request("/api/threads")
assert len(threads) >= 10
detail = request(f"/api/threads/{threads[0]['id']}")
assert detail["thread"]["id"] == threads[0]["id"]
markdown = request(f"/api/requirements/{detail['thread']['requirement_id']}/markdown")
assert markdown["markdown"].startswith("# ")
sync = request("/api/mail/sync", method="POST")
assert sync["provider"] == "mock"
assert sync["imported"] == 0
print(f"后端烟测通过：{len(threads)} 条线程，详情、Markdown、邮箱同步均正常。")
PY

if curl -fsS "${SMOKE_FRONTEND_URL:-http://localhost:3001/}" >"$smoke_dir/frontend.html" 2>/dev/null; then
  SMOKE_FRONTEND_FILE="$smoke_dir/frontend.html" .venv/bin/python - <<'PY'
from pathlib import Path
import os

html = Path(os.environ["SMOKE_FRONTEND_FILE"]).read_text()
for phrase in ("需求工作台", "自动回复", "同步邮件"):
    assert phrase in html, phrase
assert "A little space." not in html
print("前端烟测通过：首页中文文案和同步入口已输出。")
PY
else
  echo "未检测到前端开发服务，已跳过首页烟测；后端烟测仍已通过。"
fi
