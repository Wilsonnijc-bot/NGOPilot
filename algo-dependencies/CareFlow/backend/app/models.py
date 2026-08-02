"""ORM 模型 — 圍繞「志工探訪批次任務」展開。"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel, Column, JSON


# ── 列舉型別 ────────────────────────────────────────────────────────────────
class BatchStatus(str, Enum):
    UPLOADED = "uploaded"            # 照片已上傳，等待 AI 抽取
    EXTRACTING = "extracting"        # AI 正在處理
    PENDING_REVIEW = "pending_review"  # 待社工審查
    CONFIRMED = "confirmed"          # 社工已確認
    EXPORTED = "exported"            # 已匯出 Excel
    FAILED = "failed"


# ── 任務批次：一次上傳 N 張照片構成一個批次 ──────────────────────────────────
class VolunteerBatch(SQLModel, table=True):
    __tablename__ = "volunteer_batch"

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str                                          # 例：「2026-05-12 深水埗志工探訪 12 份」
    volunteer_team: Optional[str] = None                # 志工隊名稱
    visit_date: Optional[str] = None                    # 探訪日期（任務級）
    note: Optional[str] = None
    status: BatchStatus = Field(default=BatchStatus.UPLOADED)
    total_photos: int = 0
    confirmed_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    confirmed_at: Optional[datetime] = None
    exported_at: Optional[datetime] = None
    exported_file: Optional[str] = None                 # 相對 DATA_DIR


# ── 單張照片 + 抽取結果 ────────────────────────────────────────────────────
class VolunteerRecord(SQLModel, table=True):
    __tablename__ = "volunteer_record"

    id: Optional[int] = Field(default=None, primary_key=True)
    batch_id: int = Field(foreign_key="volunteer_batch.id", index=True)
    photo_path: str                                     # 相對 DATA_DIR
    original_filename: str

    # AI 抽取
    ai_extracted: Optional[dict] = Field(default=None, sa_column=Column(JSON))   # raw fields
    ai_confidence: Optional[dict] = Field(default=None, sa_column=Column(JSON))  # per-field 0..1
    ai_bbox: Optional[dict] = Field(default=None, sa_column=Column(JSON))        # per-field [x,y,w,h] (normalized)
    ai_provider: Optional[str] = None
    ai_model: Optional[str] = None
    ai_raw_response: Optional[str] = None
    ai_latency_ms: Optional[int] = None
    ai_error: Optional[str] = None

    # 人工最終值
    final_fields: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    is_reviewed: bool = False
    reviewer: Optional[str] = None
    reviewed_at: Optional[datetime] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ── 修正記錄：用於 prompt 改進 ───────────────────────────────────────────────
class FieldCorrection(SQLModel, table=True):
    __tablename__ = "field_correction"

    id: Optional[int] = Field(default=None, primary_key=True)
    record_id: int = Field(foreign_key="volunteer_record.id", index=True)
    batch_id: int = Field(foreign_key="volunteer_batch.id", index=True)
    field_name: str
    ai_value: Optional[str] = None
    final_value: Optional[str] = None
    ai_confidence: Optional[float] = None
    reviewer: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── 長者資料（簡版，供其他功能未來引用）─────────────────────────────────────
class Elder(SQLModel, table=True):
    __tablename__ = "elder"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    hkid_masked: Optional[str] = None                   # 只存遮罩後例：A12****(7)
    gender: Optional[str] = None
    birth_year: Optional[int] = None
    district: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    living_alone: Optional[bool] = None
    chronic_conditions: Optional[str] = None
    note: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ── 流水線 β：家訪語音 → 結構化報告 session ─────────────────────────────────
class VisitSessionStatus(str, Enum):
    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    PENDING_REVIEW = "pending_review"
    RENDERING = "rendering"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    BURNED = "burned"  # transcript 已被「閱後即焚」


class VisitSession(SQLModel, table=True):
    __tablename__ = "visit_session"

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    note: Optional[str] = None
    status: VisitSessionStatus = Field(default=VisitSessionStatus.UPLOADED)

    audio_path: Optional[str] = None        # 相對 DATA_DIR
    audio_filename: Optional[str] = None
    template_path: Optional[str] = None     # 相對 DATA_DIR — 上傳的模板原檔
    template_filename: Optional[str] = None
    working_docx_path: Optional[str] = None # 相對 DATA_DIR — normalize 後的 .docx

    # AI 產出（可審查，存得起）
    template_contract: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    slot_content: Optional[dict] = Field(default=None, sa_column=Column(JSON))    # AI 草稿
    slot_content_final: Optional[dict] = Field(default=None, sa_column=Column(JSON))  # 人工確認版

    # 隱私：transcript 不存明文。指向加密 vault 檔。
    transcript_vault_path: Optional[str] = None   # 相對 DATA_DIR
    transcript_burned: bool = False

    # 最終輸出
    generated_file: Optional[str] = None    # 相對 DATA_DIR

    ai_provider: Optional[str] = None
    ai_model: Optional[str] = None
    ai_latency_ms: Optional[int] = None
    ai_error: Optional[str] = None

    reviewer: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ── 功能 θ：自訂 PDF 表單模板分析 ─────────────────────────────────────────────
class ThetaTemplateStatus(str, Enum):
    ANALYZING = "analyzing"
    PENDING_REVIEW = "pending_review"
    CONFIRMED = "confirmed"


class ThetaTemplate(SQLModel, table=True):
    __tablename__ = "theta_template"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    original_pdf_path: str                           # 相對 DATA_DIR
    original_pdf_filename: Optional[str] = None
    page_count: int = 0
    status: ThetaTemplateStatus = Field(default=ThetaTemplateStatus.ANALYZING)
    note: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ThetaField(SQLModel, table=True):
    __tablename__ = "theta_field"

    id: Optional[int] = Field(default=None, primary_key=True)
    template_id: int = Field(foreign_key="theta_template.id", index=True)
    page_number: int = 0                              # 0-indexed
    field_key: str                                    # e.g. "name_zh"
    field_label: str                                  # e.g. "姓名（中文）"
    field_type: str = "text"                          # text / number / date / checkbox / select / signature
    bbox: Optional[dict] = Field(default=None, sa_column=Column(JSON))  # [x, y, w, h] normalized 0..1 — refined (vector-snap) or LLM raw
    bbox_llm: Optional[dict] = Field(default=None, sa_column=Column(JSON))  # rc6.8: LLM 原始預測 bbox（向量微調前），audit 雙框比對用
    confidence: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)

