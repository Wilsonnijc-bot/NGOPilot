@echo off
REM CareFlow 一鍵啟動腳本（Windows）
setlocal

set ROOT=%~dp0..
cd /d "%ROOT%"

echo === CareFlow 啟動 ===
echo 工作目錄: %ROOT%

REM 1. 後端
cd backend
if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q --upgrade pip
pip install -q -e .

REM 2. 種子資料
python -m app.seed --count 20

REM 3. 啟動後端（新窗口）
start "CareFlow Backend" cmd /k "call .venv\Scripts\activate.bat && uvicorn app.main:app --host 0.0.0.0 --port 8000"

REM 4. 前端
cd ..\frontend
if not exist node_modules (
  npm install --legacy-peer-deps
)
echo 啟動前端 :5173 — 瀏覽 http://localhost:5173
npm run dev

endlocal
