#!/usr/bin/env bash
# CareFlow 一鍵啟動腳本（Mac / Linux）
# 用途：本地綠色包模式 — 不需要 Docker，直接以 Python + Node 啟動。
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== CareFlow 啟動 ==="
echo "工作目錄：$ROOT"

# 1. 後端
echo
echo "[1/3] 安裝後端 Python 依賴 …"
cd "$ROOT/backend"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -e .

# 2. 種子資料（可選）
echo
echo "[2/3] 產生 mock 種子（20 張照片 + 一個示範批次）…"
python -m app.seed --count 20 || echo "  (種子失敗或已存在，忽略)"

# 3. 啟動 uvicorn（背景）
echo
echo "[3/3] 啟動後端 uvicorn :8000 …"
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > "$ROOT/backend.log" 2>&1 &
BACKEND_PID=$!
echo "  後端 PID = $BACKEND_PID（log: backend.log）"
echo "$BACKEND_PID" > "$ROOT/.backend.pid"

# 4. 前端
echo
cd "$ROOT/frontend"
if [ ! -d "node_modules" ]; then
  echo "[4/4] 安裝前端依賴（首次較慢）…"
  npm install --legacy-peer-deps
fi
echo
echo "啟動前端 Vite dev server :5173 …"
echo "完成後請瀏覽 http://localhost:5173"
npm run dev
