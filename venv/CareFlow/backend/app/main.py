"""FastAPI 入口。"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .api import diagnose, elders, history, home_visit, placeholder, templates, theta, volunteer
from .config import settings
from .db import init_db
from .version import APP_VERSION


class UTF8JSONResponse(JSONResponse):
    """v0.4.0-beta：強制在 Content-Type 帶上 charset=utf-8，
    避免某些瀏覽器（Safari raw view）誤判 Latin-1 把中文顯示成亂碼。"""
    media_type = "application/json; charset=utf-8"


app = FastAPI(
    title="CareFlow Backend",
    description="香港 NGO 長者照護 AI 生產力工具",
    version=APP_VERSION,
    default_response_class=UTF8JSONResponse,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    init_db()
    # 確保 data 目錄存在
    _ = settings.data_path


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "version": APP_VERSION,
        # rc6: 三路獨立呈現
        "llm_provider": settings.llm_provider,  # legacy 欄位
        "is_mock_mode": settings.is_mock_mode,
        "channels": {
            "text": {
                "provider": "deepseek_official",
                "model": settings.deepseek_text_model,
                "mock": settings.is_text_mock,
            },
            "vision": {
                "provider": "azure_openai",
                "model": settings.azure_openai_model,
                "deployment": settings.azure_openai_deployment,
                "mock": settings.is_vision_mock,
            },
            "asr": {
                "provider": "bailian",
                "model": settings.bailian_asr_model,
                "mock": settings.is_asr_mock,
            },
        },
        # legacy alias，保留舊前端相容
        "models": {
            "text": settings.deepseek_text_model,
            "vision": settings.azure_openai_model,
            "asr": settings.bailian_asr_model,
        },
    }


_ALLOWED_FILE_SUBDIRS = {
    "uploads",
    "exports",
    "welfare_outputs",
    "theta_pdfs",
    "samples",
    "welfare_templates",
}
_FORBIDDEN_FILE_TOKENS = (".transcript_key", "careflow.db")


@app.get("/api/files/{path:path}")
def serve_file(path: str):
    """提供 data/ 下的檔案（照片、Excel 等）。

    Allow-list 限制：只允許以下子目錄；任何 hidden file（以 `.` 開頭的路徑段）
    或敏感檔（Fernet key / SQLite DB）一律 404。
    """
    # 防呆：禁止明確的敏感檔名出現在任何 path segment
    if any(tok in path for tok in _FORBIDDEN_FILE_TOKENS):
        raise HTTPException(404, "file not found")

    base = settings.data_path.resolve()
    full = (base / path).resolve()
    try:
        rel = full.relative_to(base)
    except ValueError:
        raise HTTPException(403, "forbidden")

    parts = rel.parts
    if not parts:
        raise HTTPException(404, "file not found")
    # 第一段必須在 allow-list 內
    if parts[0] not in _ALLOWED_FILE_SUBDIRS:
        raise HTTPException(404, "file not found")
    # 任何 path segment 以 `.` 開頭 → 拒絕（hidden / dotfile）
    if any(seg.startswith(".") for seg in parts):
        raise HTTPException(404, "file not found")

    if not full.exists() or not full.is_file():
        raise HTTPException(404, "file not found")
    return FileResponse(full)


# 註冊路由
app.include_router(volunteer.router)
app.include_router(history.router)
app.include_router(templates.router)
app.include_router(elders.router)
app.include_router(home_visit.router)
app.include_router(placeholder.router)
app.include_router(diagnose.router)
app.include_router(theta.router)
