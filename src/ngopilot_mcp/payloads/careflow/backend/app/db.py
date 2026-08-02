"""SQLModel 資料層 — SQLite 單機。"""
from __future__ import annotations

from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine

from .config import settings

# 確保 data 資料夾存在（也會建立 uploads/exports/samples/templates 子目錄）
_ = settings.data_path

# 若是 SQLite 相對路徑，將 db 檔放進 data_path
_db_url = settings.database_url
if _db_url.startswith("sqlite:///") and not _db_url.startswith("sqlite:////"):
    # 例如 sqlite:///./data/careflow.db → 改用 data_path 絕對路徑
    rel = _db_url.replace("sqlite:///", "", 1)
    abs_path = (Path(rel).resolve() if Path(rel).is_absolute() else settings.data_path / Path(rel).name)
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    _db_url = f"sqlite:///{abs_path}"

# SQLite + 多執行緒
engine = create_engine(
    _db_url,
    echo=False,
    connect_args={"check_same_thread": False} if _db_url.startswith("sqlite") else {},
)


def init_db() -> None:
    # 確保所有 model 已 import
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _apply_lightweight_migrations()


def _apply_lightweight_migrations() -> None:
    """SQLite-safe ad-hoc ALTER TABLE，用於沒有 alembic 的小欄位新增。

    每條 ALTER 包在 try/except 內，已存在的欄位會被靜默忽略。
    """
    from sqlalchemy import text  # type: ignore
    migrations = [
        # rc6.8：ThetaField 加 bbox_llm（向量微調前的 LLM 原始 bbox）
        "ALTER TABLE theta_field ADD COLUMN bbox_llm JSON",
    ]
    with engine.begin() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
            except Exception:  # noqa: BLE001
                pass


def get_session() -> Session:  # FastAPI dependency
    with Session(engine) as session:
        yield session
