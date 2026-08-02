"""Fail-closed final publication for one exact durable weekly version."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, field_validator

from ..domain import PublicationRecord, WeeklyRunRecord, stable_id
from ..exporter import (
    build_generated_division_roster_workbook,
    prepare_generated_division_roster_export,
)
from ..importer import DivisionImportResult
from .weekly_review import WeeklyReviewError, validate_current_version


FINAL_WORKBOOK_FILENAME = "照顧員工作分工表_正式版.xlsx"
_LOCKS_GUARD = Lock()
_PUBLICATION_LOCKS: dict[str, Lock] = {}


class WeeklyPublicationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str
    source_version_id: str
    content_hash: str

    @field_validator("actor", "source_version_id", "content_hash", mode="before")
    @classmethod
    def _required_string(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
        if not value:
            raise ValueError("發佈正式版所需欄位不可留空")
        return value


@dataclass
class WeeklyPublicationOutcome:
    publication: PublicationRecord
    artifact_written: bool


@contextmanager
def weekly_publication_lock(
    *,
    output_dir: Path,
    run_id: str,
    source_version_id: str,
    content_hash: str,
):
    """Serialize one version's load/preflight/write/commit across workers."""

    publication_id = stable_id("pub_", "weekly_publication", {
        "run_id": run_id,
        "source_version_id": source_version_id,
        "content_hash": content_hash,
    })
    with _LOCKS_GUARD:
        thread_lock = _PUBLICATION_LOCKS.setdefault(publication_id, Lock())
    lock_dir = output_dir.resolve() / "published" / ".locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{publication_id}.lock"
    with thread_lock, lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def publish_weekly_run(
    record: WeeklyRunRecord,
    *,
    division_layout: DivisionImportResult,
    command: WeeklyPublicationCommand,
    output_dir: Path,
    template_path: Path,
    source_summary: dict[str, object] | None = None,
) -> WeeklyPublicationOutcome:
    """Freshly preflight and write the staff final only when exactly ready."""

    current = validate_current_version(
        record,
        source_version_id=command.source_version_id,
        content_hash=command.content_hash,
    )
    generated = _restore_generated(record)
    plan = prepare_generated_division_roster_export(
        division_layout=division_layout,
        dataset=record.dataset,
        version=current,
        generated=generated,
    )
    if (
        plan.review_version.id != current.id
        or plan.report.reconciliation.content_hash != command.content_hash
    ):
        raise WeeklyReviewError(
            409,
            "PUBLICATION_PREFLIGHT_DRIFT",
            "正式版匯出前檢查與目前保存版本不一致，已停止發佈",
            source_version_id=current.id,
        )
    if plan.report.publication_state != "ready":
        reasons = list(plan.report.export_block_reasons)
        if not reasons:
            reconciliation = plan.report.reconciliation
            if reconciliation.pending_audit_counts.get("total", 0):
                reasons.append(
                    f"仍有 {reconciliation.pending_audit_counts['total']} 項審核未處理"
                )
            if reconciliation.needs_review:
                reasons.append(f"仍有 {reconciliation.needs_review} 項需要審核")
            if reconciliation.unassigned:
                reasons.append(f"仍有 {reconciliation.unassigned} 項未分配")
        raise WeeklyReviewError(
            409,
            "PUBLICATION_NOT_READY",
            "目前排班版本不可發佈正式版",
            publication_state=plan.report.publication_state,
            reasons=reasons or ["服務器重新驗證結果尚未達到可發放狀態"],
        )

    # An exact-version retry returns the immutable fact already validated by
    # the store loader. It still passed the fresh safety boundary above.
    existing = next(
        (
            item for item in record.publications
            if item.source_version_id == current.id
            and item.content_hash == command.content_hash
        ),
        None,
    )
    if existing is not None:
        return WeeklyPublicationOutcome(existing, artifact_written=False)

    publication_id = stable_id("pub_", "weekly_publication", {
        "run_id": record.run_id,
        "source_version_id": current.id,
        "content_hash": command.content_hash,
    })
    artifact_dir = output_dir.resolve() / "published" / publication_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / FINAL_WORKBOOK_FILENAME
    temporary_path = artifact_dir / f".{uuid4().hex}.xlsx"
    try:
        workbook = build_generated_division_roster_workbook(
            template_path=template_path,
            division_layout=division_layout,
            dataset=record.dataset,
            version=current,
            generated=generated,
            prepared_plan=plan,
            source_summary=source_summary,
        )
        workbook.save(temporary_path)
        artifact_sha256 = _sha256(temporary_path)
        os.replace(temporary_path, artifact_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    publication = PublicationRecord(
        publication_id=publication_id,
        run_id=record.run_id,
        source_version_id=current.id,
        content_hash=command.content_hash,
        actor=command.actor,
        published_at=datetime.now(timezone.utc),
        artifact_path=str(artifact_path),
        artifact_sha256=artifact_sha256,
        filename=FINAL_WORKBOOK_FILENAME,
    )
    return WeeklyPublicationOutcome(publication, artifact_written=True)


def remove_uncommitted_publication(outcome: WeeklyPublicationOutcome) -> None:
    """Best-effort compensation when the durable record was not committed."""

    if not outcome.artifact_written:
        return
    Path(outcome.publication.artifact_path).unlink(missing_ok=True)


def _restore_generated(record: WeeklyRunRecord):
    # Local import keeps the domain service free of a scheduler import cycle.
    from ..scheduler import GeneratedDemands

    return GeneratedDemands.model_validate(record.generated_payload)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
