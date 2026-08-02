#!/usr/bin/env bash
# 關閉 start.sh 啟動的後端進程
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$ROOT/.backend.pid" ]; then
  PID=$(cat "$ROOT/.backend.pid")
  echo "Stopping backend PID $PID …"
  kill "$PID" 2>/dev/null || echo "  (already stopped)"
  rm "$ROOT/.backend.pid"
fi
