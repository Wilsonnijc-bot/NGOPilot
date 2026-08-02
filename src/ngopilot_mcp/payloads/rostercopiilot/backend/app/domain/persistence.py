"""Durable Phase 1B weekly-run and human-review value objects."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .dataset import MockDataset
from .master_data import ManualOverride
from .provenance import stable_id
from .schedule import HardViolation, ScheduleEntry, ScheduleVersion
from .snapshot import SchedulerSnapshot


class ReviewDecisionRecord(BaseModel):
    """One idempotent review action and the immutable version it produced."""

    decision_id: str = ""
    run_id: str
    source_version_id: str
    resulting_version_id: str
    audit_id: str
    audit_ids: list[str] = Field(default_factory=list)
    action: Literal["approve", "reject", "edit", "revalidate"]
    actor: str
    timestamp: datetime
    note: str | None = None
    override_note: str | None = None
    hard_bypass: bool = False
    edited_entry_payload: ScheduleEntry | None = None
    validator_result: list[HardViolation] = Field(default_factory=list)
    content_hash: str
    idempotency_key: str
    request_hash: str | None = None

    @field_validator(
        "run_id",
        "source_version_id",
        "resulting_version_id",
        "audit_id",
        "actor",
        "content_hash",
        "idempotency_key",
        mode="before",
    )
    @classmethod
    def _non_empty_string(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("review-decision identity fields must not be empty")
        return value

    @model_validator(mode="after")
    def _stable_default_id(self) -> "ReviewDecisionRecord":
        expected = stable_id("dec_", "review_decision", {
            "run_id": self.run_id,
            "audit_id": self.audit_id,
            "resulting_version_id": self.resulting_version_id,
        })
        if self.decision_id and self.decision_id != expected:
            raise ValueError("decision ID does not match its canonical identity")
        self.decision_id = expected
        self.audit_ids = sorted({
            self.audit_id,
            *(item.strip() for item in self.audit_ids if item.strip()),
        })
        if self.action in {"reject", "edit"} and not self.note:
            raise ValueError(f"{self.action} decision requires a note")
        if self.action == "edit" and self.edited_entry_payload is None:
            raise ValueError("edit decision requires edited_entry_payload")
        return self


class PublicationRecord(BaseModel):
    """Immutable proof that one exact ready schedule was written to disk."""

    publication_id: str = ""
    run_id: str
    source_version_id: str
    content_hash: str
    actor: str
    published_at: datetime
    artifact_path: str
    artifact_sha256: str
    filename: Literal["照顧員工作分工表_正式版.xlsx"] = "照顧員工作分工表_正式版.xlsx"

    @field_validator(
        "run_id",
        "source_version_id",
        "content_hash",
        "actor",
        "artifact_path",
        "artifact_sha256",
        mode="before",
    )
    @classmethod
    def _required_publication_string(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
        if not value:
            raise ValueError("publication identity fields must not be empty")
        return value

    @model_validator(mode="after")
    def _canonical_publication_identity(self) -> "PublicationRecord":
        expected = stable_id("pub_", "weekly_publication", {
            "run_id": self.run_id,
            "source_version_id": self.source_version_id,
            "content_hash": self.content_hash,
        })
        if self.publication_id and self.publication_id != expected:
            raise ValueError("publication ID does not match its canonical identity")
        self.publication_id = expected
        if len(self.artifact_sha256) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.artifact_sha256.lower()
        ):
            raise ValueError("publication artifact SHA-256 is invalid")
        self.artifact_sha256 = self.artifact_sha256.lower()
        if not Path(self.artifact_path).is_absolute():
            raise ValueError("publication artifact path must be absolute")
        return self


class WeeklyRunRecord(BaseModel):
    """Complete durable document needed to review/export one weekly run."""

    run_id: str
    week_start: date
    created_at: datetime
    current_version_id: str
    master_data_version: int | str | None = None
    snapshot: SchedulerSnapshot
    dataset: MockDataset
    generated_payload: dict[str, Any]
    scheduler_result_payload: dict[str, Any]
    run_context: dict[str, Any]
    versions: list[ScheduleVersion]
    decisions: list[ReviewDecisionRecord] = Field(default_factory=list)
    manual_overrides: list[ManualOverride] = Field(default_factory=list)
    publications: list[PublicationRecord] = Field(default_factory=list)
    latest_export_report: dict[str, Any]
    latest_export_plan: dict[str, Any]
    latest_content_hash: str

    @field_validator("run_id", "current_version_id", "latest_content_hash", mode="before")
    @classmethod
    def _required_identity(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("weekly-run identity fields must not be empty")
        return value

    @model_validator(mode="after")
    def _current_version_must_exist(self) -> "WeeklyRunRecord":
        ids = [version.id for version in self.versions]
        if len(ids) != len(set(ids)):
            raise ValueError("weekly run contains duplicate schedule version IDs")
        if self.current_version_id not in ids:
            raise ValueError("weekly run current version is missing")
        upload_names = self.run_context.get("upload_names")
        if not isinstance(upload_names, dict):
            raise ValueError("weekly run upload display names are missing")
        for role in ("hc_workbook", "escort_workbook"):
            name = upload_names.get(role)
            if (
                not isinstance(name, str)
                or not name.strip()
                or len(name) > 255
                or "/" in name
                or "\\" in name
                or any(character < " " or character == "\x7f" for character in name)
            ):
                raise ValueError(f"weekly run has unsafe upload display name: {role}")
        return self
