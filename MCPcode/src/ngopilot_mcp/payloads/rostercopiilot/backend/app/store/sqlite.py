"""SQLite/SQLModel persistence for roster state and import review data."""
from __future__ import annotations

import json
import os
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import event, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Field, Session, SQLModel, create_engine, select

from ..domain import (
    ManualOverride,
    MasterDataIssue,
    MasterDataSet,
    MockDataset,
    PublicationRecord,
    ReviewDecisionRecord,
    ScheduleVersion,
    WeeklyRunRecord,
    canonical_json,
    validate_master_data,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _apply_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    """Set durability/concurrency PRAGMAs on every new SQLite connection.

    WAL lets reviewers read while a decision commits; a 30s busy timeout lets a
    racing writer wait for the compare-and-swap instead of erroring; NORMAL
    synchronous is safe under WAL and avoids per-commit fsync stalls.
    """

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def default_db_path() -> Path:
    raw = os.getenv("ROSTER_DB_PATH")
    path = Path(raw) if raw else REPO_ROOT / "data" / "roster.db"
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _json_loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    return json.loads(value)


class StoreMeta(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value_json: str
    updated_at: datetime = Field(default_factory=_now)


class DatasetSnapshot(SQLModel, table=True):
    id: str = Field(primary_key=True)
    seed: int
    payload_json: str
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class StoredScheduleVersion(SQLModel, table=True):
    id: str = Field(primary_key=True)
    kind: str
    parent_version_id: str | None = None
    week_start: str
    created_at: datetime
    payload_json: str
    is_current: bool = False
    updated_at: datetime = Field(default_factory=_now)


class ImportBatchRecord(SQLModel, table=True):
    id: str = Field(primary_key=True)
    created_at: datetime = Field(default_factory=_now)
    source_names_json: str
    summary_json: str
    payload_json: str


class ImportAmbiguityRecord(SQLModel, table=True):
    id: str = Field(primary_key=True)
    batch_id: str
    code: str
    message: str
    severity: str = "warning"
    status: str = "pending"
    source_json: str = "{}"
    payload_json: str = "{}"
    resolution_json: str | None = None
    created_at: datetime = Field(default_factory=_now)
    resolved_at: datetime | None = None


class AliasResolutionRecord(SQLModel, table=True):
    id: str = Field(default_factory=lambda: f"alias_{uuid4().hex[:12]}",
                    primary_key=True)
    entity_type: str
    alias: str
    canonical_id: str
    canonical_name: str | None = None
    confidence: str = "manual"
    payload_json: str = "{}"
    created_at: datetime = Field(default_factory=_now)


class MasterDataVersionRecord(SQLModel, table=True):
    version: int = Field(primary_key=True)
    id: str = Field(default_factory=lambda: f"md_{uuid4().hex[:12]}", index=True)
    created_at: datetime = Field(default_factory=_now)
    origin: str = "api"
    schema_version: str = "phase1a"
    payload_json: str
    issues_json: str = "[]"


class WeeklyRunDocument(SQLModel, table=True):
    """One JSON-backed weekly-run envelope; versions live append-only below."""

    id: str = Field(primary_key=True)
    week_start: str
    created_at: datetime
    current_version_id: str
    master_data_version_json: str = "null"
    snapshot_json: str
    dataset_json: str
    generated_json: str
    scheduler_result_json: str
    run_context_json: str
    latest_export_report_json: str
    latest_export_plan_json: str
    latest_content_hash: str
    updated_at: datetime = Field(default_factory=_now)


class WeeklyRunScheduleVersion(SQLModel, table=True):
    """Immutable schedule-version document owned by a weekly run."""

    id: str = Field(primary_key=True)
    run_id: str = Field(index=True)
    kind: str
    parent_version_id: str | None = None
    created_at: datetime
    payload_json: str
    content_hash: str


class WeeklyRunDecision(SQLModel, table=True):
    decision_id: str = Field(primary_key=True)
    run_id: str = Field(index=True)
    idempotency_key: str = Field(index=True, unique=True)
    payload_json: str
    created_at: datetime


class WeeklyRunManualOverride(SQLModel, table=True):
    id: str = Field(primary_key=True)
    run_id: str = Field(index=True)
    decision_id: str = Field(index=True)
    payload_json: str
    created_at: datetime = Field(default_factory=_now)


class WeeklyRunPublication(SQLModel, table=True):
    publication_id: str = Field(primary_key=True)
    run_id: str = Field(index=True)
    source_version_id: str = Field(index=True)
    payload_json: str
    created_at: datetime


class WeeklyWorkspaceStateDocument(SQLModel, table=True):
    """Single-user pointer to the weekly run currently open in the workspace."""

    id: str = Field(default="current", primary_key=True)
    run_id: str = Field(index=True)
    saved_at: datetime = Field(default_factory=_now)


class WeeklyRunArchiveDocument(SQLModel, table=True):
    """Immutable browser-safe snapshot of one exact weekly-run version."""

    archive_id: str = Field(primary_key=True)
    run_id: str = Field(index=True)
    title: str
    week_start: str
    source_version_id: str
    content_hash: str
    snapshot_json: str
    created_at: datetime = Field(default_factory=_now)


class WeeklyRunStoreError(RuntimeError):
    """Structured fail-closed error raised for incomplete/corrupt run data."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        run_id: str,
        field: str | None = None,
        extra: dict[str, str] | None = None,
    ) -> None:
        self.code = code
        self.run_id = run_id
        self.field = field
        self.extra = dict(extra or {})
        super().__init__(message)

    def as_detail(self) -> dict[str, str]:
        localized_message = {
            "WEEKLY_RUN_DATA_MISSING": "保存的排班資料不完整，無法安全載入。",
            "WEEKLY_RUN_DATA_CORRUPT": "保存的排班資料已損壞或不一致，無法安全載入。",
            "STALE_SCHEDULE_VERSION": "審核請求所指的版本已不是目前保存版本，請重新載入後再操作。",
        }.get(self.code, "排班資料發生錯誤，無法安全處理。")
        detail = {
            "code": self.code,
            "message": localized_message,
            "run_id": self.run_id,
        }
        if self.field:
            detail["field"] = self.field
        detail.update(self.extra)
        return detail


class WeeklyRunVersionConflictError(WeeklyRunStoreError):
    """The durable current version advanced past the request's source version.

    Raised when the atomic compare-and-swap on the current-version pointer
    matches zero rows: a concurrent decision or revalidation already advanced
    the run, so this request was computed against a stale version.
    """

    def __init__(
        self,
        *,
        run_id: str,
        source_version_id: str,
        current_version_id: str,
    ) -> None:
        super().__init__(
            "STALE_SCHEDULE_VERSION",
            "durable current version advanced past the requested source version",
            run_id=run_id,
            extra={
                "source_version_id": source_version_id,
                "current_version_id": current_version_id,
            },
        )


class RosterStore:
    """Thin JSON-backed repository over SQLModel tables.

    The Phase 1 requirement is durability and traceability, not a fully
    normalized relational model. Pydantic/domain objects stay authoritative in
    memory; the DB stores complete JSON snapshots plus queryable headers.
    """

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            # A racing writer waits for the competing transaction instead of
            # failing fast with "database is locked"; the compare-and-swap on
            # the current-version pointer then decides the outcome.
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        event.listen(self.engine, "connect", _apply_sqlite_pragmas)
        SQLModel.metadata.create_all(self.engine)

    # ---------------------------------------------------------------- state
    def save_app_state(
        self,
        *,
        seed: int,
        dataset: MockDataset,
        versions: dict[str, ScheduleVersion],
        baseline_id: str,
        current_id: str,
    ) -> None:
        with Session(self.engine) as session:
            self._upsert_meta(session, "app_state", {
                "seed": seed,
                "baseline_id": baseline_id,
                "current_id": current_id,
                "version_ids": list(versions),
            })
            snapshot = session.get(DatasetSnapshot, "current")
            payload = _json_dumps(dataset.model_dump(mode="json"))
            if snapshot is None:
                snapshot = DatasetSnapshot(id="current", seed=seed,
                                           payload_json=payload)
                session.add(snapshot)
            else:
                snapshot.seed = seed
                snapshot.payload_json = payload
                snapshot.updated_at = _now()
            for version in versions.values():
                self._upsert_version(session, version,
                                     is_current=(version.id == current_id))
            for row in session.exec(select(StoredScheduleVersion)).all():
                if row.id not in versions:
                    session.delete(row)
            session.commit()

    def load_app_state(self) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            meta = session.get(StoreMeta, "app_state")
            snapshot = session.get(DatasetSnapshot, "current")
            if meta is None or snapshot is None:
                return None
            meta_payload = _json_loads(meta.value_json, {})
            versions: dict[str, ScheduleVersion] = {}
            for row in session.exec(select(StoredScheduleVersion)).all():
                versions[row.id] = ScheduleVersion.model_validate(
                    _json_loads(row.payload_json, {}))
            if not versions:
                return None
            current_id = meta_payload.get("current_id")
            baseline_id = meta_payload.get("baseline_id")
            if current_id not in versions or baseline_id not in versions:
                return None
            return {
                "seed": int(meta_payload.get("seed", snapshot.seed)),
                "dataset": MockDataset.model_validate(
                    _json_loads(snapshot.payload_json, {})),
                "versions": versions,
                "baseline_id": baseline_id,
                "current_id": current_id,
            }

    def save_version(self, version: ScheduleVersion, *, current_id: str) -> None:
        with Session(self.engine) as session:
            self._upsert_version(session, version, is_current=True)
            for row in session.exec(select(StoredScheduleVersion)).all():
                row.is_current = (row.id == current_id)
            self._upsert_meta_value(session, "current_id", current_id)
            session.commit()

    # ---------------------------------------------------------- weekly runs
    def create_weekly_run(self, record: WeeklyRunRecord) -> WeeklyRunRecord:
        """Create one durable run and its initial immutable version(s)."""

        with Session(self.engine) as session:
            if record.publications:
                raise ValueError("new weekly run cannot contain publication records")
            if session.get(WeeklyRunDocument, record.run_id) is not None:
                raise ValueError(f"weekly run already exists: {record.run_id}")
            for version in record.versions:
                self._insert_weekly_version(
                    session,
                    run_id=record.run_id,
                    version=version,
                )
            current = next(
                version for version in record.versions
                if version.id == record.current_version_id
            )
            expected_hash = self._version_content_hash(current)
            if record.latest_content_hash != expected_hash:
                raise ValueError("weekly run content hash does not match current version")
            self._validate_export_artifacts(
                version=current,
                content_hash=record.latest_content_hash,
                report=record.latest_export_report,
                plan=record.latest_export_plan,
            )
            session.add(WeeklyRunDocument(
                id=record.run_id,
                week_start=record.week_start.isoformat(),
                created_at=record.created_at,
                current_version_id=record.current_version_id,
                master_data_version_json=_json_dumps(record.master_data_version),
                snapshot_json=_json_dumps(record.snapshot.model_dump(mode="json")),
                dataset_json=_json_dumps(record.dataset.model_dump(mode="json")),
                generated_json=_json_dumps(record.generated_payload),
                scheduler_result_json=_json_dumps(record.scheduler_result_payload),
                run_context_json=_json_dumps(record.run_context),
                latest_export_report_json=_json_dumps(record.latest_export_report),
                latest_export_plan_json=_json_dumps(record.latest_export_plan),
                latest_content_hash=record.latest_content_hash,
            ))
            session.commit()
        loaded = self.get_weekly_run(record.run_id)
        if loaded is None:  # pragma: no cover - a committed row must be readable
            raise WeeklyRunStoreError(
                "WEEKLY_RUN_DATA_MISSING",
                "created weekly run could not be loaded",
                run_id=record.run_id,
            )
        return loaded

    def get_weekly_run(self, run_id: str) -> WeeklyRunRecord | None:
        """Load and validate the complete durable run; never regenerate it."""

        with Session(self.engine) as session:
            row = session.get(WeeklyRunDocument, run_id)
            if row is None:
                return None
            version_rows = session.exec(
                select(WeeklyRunScheduleVersion).where(
                    WeeklyRunScheduleVersion.run_id == run_id
                )
            ).all()
            decision_rows = session.exec(
                select(WeeklyRunDecision).where(WeeklyRunDecision.run_id == run_id)
            ).all()
            override_rows = session.exec(
                select(WeeklyRunManualOverride).where(
                    WeeklyRunManualOverride.run_id == run_id
                )
            ).all()
            publication_rows = session.exec(
                select(WeeklyRunPublication).where(
                    WeeklyRunPublication.run_id == run_id
                )
            ).all()
            try:
                versions = [
                    ScheduleVersion.model_validate(
                        self._load_required_json(item.payload_json, run_id, "versions")
                    )
                    for item in version_rows
                ]
                versions.sort(key=lambda item: (item.created_at, item.id))
                version_rows_by_id = {item.id: item for item in version_rows}
                for version in versions:
                    version_row = version_rows_by_id[version.id]
                    computed = self._version_content_hash(version)
                    if computed != version_row.content_hash:
                        raise WeeklyRunStoreError(
                            "WEEKLY_RUN_DATA_CORRUPT",
                            f"stored schedule version hash is invalid: {version.id}",
                            run_id=run_id,
                            field="versions",
                        )
                current = next(
                    (item for item in versions if item.id == row.current_version_id),
                    None,
                )
                if current is None:
                    raise WeeklyRunStoreError(
                        "WEEKLY_RUN_DATA_MISSING",
                        "weekly run current version is missing",
                        run_id=run_id,
                        field="current_version_id",
                    )
                if self._version_content_hash(current) != row.latest_content_hash:
                    raise WeeklyRunStoreError(
                        "WEEKLY_RUN_DATA_CORRUPT",
                        "weekly run latest content hash is invalid",
                        run_id=run_id,
                        field="latest_content_hash",
                    )
                decisions = [
                    ReviewDecisionRecord.model_validate(
                        self._load_required_json(item.payload_json, run_id, "decisions")
                    )
                    for item in decision_rows
                ]
                decisions.sort(key=lambda item: (item.timestamp, item.decision_id))
                overrides = [
                    ManualOverride.model_validate(
                        self._load_required_json(
                            item.payload_json, run_id, "manual_overrides"
                        )
                    )
                    for item in override_rows
                ]
                overrides.sort(key=lambda item: item.id)
                publications: list[PublicationRecord] = []
                for item in publication_rows:
                    publication = PublicationRecord.model_validate(
                        self._load_required_json(
                            item.payload_json, run_id, "publications"
                        )
                    )
                    if (
                        publication.publication_id != item.publication_id
                        or publication.run_id != item.run_id
                        or publication.source_version_id != item.source_version_id
                    ):
                        raise WeeklyRunStoreError(
                            "WEEKLY_RUN_DATA_CORRUPT",
                            "publication row identity does not match its payload",
                            run_id=run_id,
                            field="publications",
                        )
                    publications.append(publication)
                publications.sort(
                    key=lambda item: (item.published_at, item.publication_id)
                )
                record = WeeklyRunRecord(
                    run_id=row.id,
                    week_start=row.week_start,
                    created_at=row.created_at,
                    current_version_id=row.current_version_id,
                    master_data_version=self._load_required_json(
                        row.master_data_version_json,
                        run_id,
                        "master_data_version",
                        allow_null=True,
                    ),
                    snapshot=self._load_required_json(
                        row.snapshot_json, run_id, "snapshot"
                    ),
                    dataset=self._load_required_json(
                        row.dataset_json, run_id, "dataset"
                    ),
                    generated_payload=self._load_required_json(
                        row.generated_json, run_id, "generated"
                    ),
                    scheduler_result_payload=self._load_required_json(
                        row.scheduler_result_json, run_id, "scheduler_result"
                    ),
                    run_context=self._load_required_json(
                        row.run_context_json, run_id, "run_context"
                    ),
                    versions=versions,
                    decisions=decisions,
                    manual_overrides=overrides,
                    publications=publications,
                    latest_export_report=self._load_required_json(
                        row.latest_export_report_json, run_id, "latest_export_report"
                    ),
                    latest_export_plan=self._load_required_json(
                        row.latest_export_plan_json, run_id, "latest_export_plan"
                    ),
                    latest_content_hash=row.latest_content_hash,
                )
                versions_by_id = {item.id: item for item in versions}
                for version in versions:
                    if (
                        version.parent_version_id is not None
                        and version.parent_version_id not in versions_by_id
                    ):
                        raise WeeklyRunStoreError(
                            "WEEKLY_RUN_DATA_MISSING",
                            f"schedule version parent is missing: {version.id}",
                            run_id=run_id,
                            field="versions",
                        )
                decisions_by_id = {item.decision_id: item for item in decisions}
                for decision in decisions:
                    source = versions_by_id.get(decision.source_version_id)
                    result = versions_by_id.get(decision.resulting_version_id)
                    if source is None or result is None:
                        raise WeeklyRunStoreError(
                            "WEEKLY_RUN_DATA_MISSING",
                            f"review decision version lineage is incomplete: "
                            f"{decision.decision_id}",
                            run_id=run_id,
                            field="decisions",
                        )
                    if (
                        result.parent_version_id != source.id
                        or self._version_content_hash(result) != decision.content_hash
                    ):
                        raise WeeklyRunStoreError(
                            "WEEKLY_RUN_DATA_CORRUPT",
                            f"review decision version lineage is invalid: "
                            f"{decision.decision_id}",
                            run_id=run_id,
                            field="decisions",
                        )
                for override in overrides:
                    decision = decisions_by_id.get(override.decision_id or "")
                    if decision is None:
                        raise WeeklyRunStoreError(
                            "WEEKLY_RUN_DATA_MISSING",
                            f"manual override decision is missing: {override.id}",
                            run_id=run_id,
                            field="manual_overrides",
                        )
                    self._validate_review_override(decision, override)
                for publication in publications:
                    version = versions_by_id.get(publication.source_version_id)
                    if version is None:
                        raise WeeklyRunStoreError(
                            "WEEKLY_RUN_DATA_MISSING",
                            f"publication version is missing: {publication.publication_id}",
                            run_id=run_id,
                            field="publications",
                        )
                    if publication.content_hash != self._version_content_hash(version):
                        raise WeeklyRunStoreError(
                            "WEEKLY_RUN_DATA_CORRUPT",
                            f"publication lineage is invalid: {publication.publication_id}",
                            run_id=run_id,
                            field="publications",
                        )
                    self._validate_publication_artifact(publication)
                self._validate_export_artifacts(
                    version=current,
                    content_hash=row.latest_content_hash,
                    report=record.latest_export_report,
                    plan=record.latest_export_plan,
                )
                return record
            except WeeklyRunStoreError:
                raise
            except (KeyError, TypeError, ValueError) as exc:
                raise WeeklyRunStoreError(
                    "WEEKLY_RUN_DATA_CORRUPT",
                    f"stored weekly run is invalid: {exc}",
                    run_id=run_id,
                ) from exc

    # ------------------------------------------------ weekly workspaces/archive
    def save_weekly_workspace(self, run_id: str) -> dict[str, Any]:
        """Persist the run that should be restored after the browser refreshes."""

        with Session(self.engine) as session:
            if session.get(WeeklyRunDocument, run_id) is None:
                raise KeyError(run_id)
            row = session.get(WeeklyWorkspaceStateDocument, "current")
            if row is None:
                row = WeeklyWorkspaceStateDocument(run_id=run_id)
            else:
                row.run_id = run_id
                row.saved_at = _now()
            session.add(row)
            session.commit()
            session.refresh(row)
            return {
                "current_run_id": row.run_id,
                "saved_at": row.saved_at,
            }

    def get_weekly_workspace(self) -> dict[str, Any] | None:
        """Return the current workspace pointer, if one has been saved."""

        with Session(self.engine) as session:
            row = session.get(WeeklyWorkspaceStateDocument, "current")
            if row is None:
                return None
            return {
                "current_run_id": row.run_id,
                "saved_at": row.saved_at,
            }

    def create_weekly_run_archive(
        self,
        *,
        run_id: str,
        title: str,
        week_start: str,
        source_version_id: str,
        content_hash: str,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """Freeze one exact API payload; later run edits cannot change it."""

        clean_title = title.strip()
        if not clean_title:
            raise ValueError("archive title cannot be empty")
        if len(clean_title) > 120:
            raise ValueError("archive title cannot exceed 120 characters")
        with Session(self.engine) as session:
            if session.get(WeeklyRunDocument, run_id) is None:
                raise KeyError(run_id)
            row = WeeklyRunArchiveDocument(
                archive_id=f"arc_{uuid4().hex[:12]}",
                run_id=run_id,
                title=clean_title,
                week_start=week_start,
                source_version_id=source_version_id,
                content_hash=content_hash,
                snapshot_json=_json_dumps(snapshot),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._archive_metadata(row)

    def list_weekly_run_archives(self) -> list[dict[str, Any]]:
        """List immutable archives without loading their full snapshots."""

        with Session(self.engine) as session:
            rows = session.exec(
                select(WeeklyRunArchiveDocument).order_by(
                    WeeklyRunArchiveDocument.created_at.desc()
                )
            ).all()
            return [self._archive_metadata(row) for row in rows]

    def get_weekly_run_archive(self, archive_id: str) -> dict[str, Any] | None:
        """Load one immutable archive and its frozen browser payload."""

        with Session(self.engine) as session:
            row = session.get(WeeklyRunArchiveDocument, archive_id)
            if row is None:
                return None
            return {
                "archive": self._archive_metadata(row),
                "snapshot": _json_loads(row.snapshot_json, {}),
            }

    @staticmethod
    def _archive_metadata(row: WeeklyRunArchiveDocument) -> dict[str, Any]:
        return {
            "archive_id": row.archive_id,
            "run_id": row.run_id,
            "title": row.title,
            "week_start": row.week_start,
            "source_version_id": row.source_version_id,
            "content_hash": row.content_hash,
            "created_at": row.created_at,
        }

    def append_weekly_run_version(
        self,
        *,
        run_id: str,
        version: ScheduleVersion,
        latest_export_report: dict[str, Any],
        latest_export_plan: dict[str, Any],
    ) -> ScheduleVersion:
        """Append an immutable child and advance the durable current pointer."""

        with Session(self.engine) as session:
            row = session.get(WeeklyRunDocument, run_id)
            if row is None:
                raise KeyError(run_id)
            if version.parent_version_id != row.current_version_id:
                raise WeeklyRunVersionConflictError(
                    run_id=run_id,
                    source_version_id=version.parent_version_id or "",
                    current_version_id=row.current_version_id,
                )
            if version.id == version.parent_version_id:
                raise ValueError("new schedule version must have a distinct ID")
            content_hash = self._version_content_hash(version)
            self._validate_export_artifacts(
                version=version,
                content_hash=content_hash,
                report=latest_export_report,
                plan=latest_export_plan,
            )
            if not self._advance_current_version(
                session,
                run_id=run_id,
                source_version_id=version.parent_version_id or "",
                result_version_id=version.id,
                result_content_hash=content_hash,
                latest_export_report=latest_export_report,
                latest_export_plan=latest_export_plan,
            ):
                session.rollback()
                raise WeeklyRunVersionConflictError(
                    run_id=run_id,
                    source_version_id=version.parent_version_id or "",
                    current_version_id=self._current_version_id(run_id),
                )
            self._insert_weekly_version(session, run_id=run_id, version=version)
            session.commit()
        return version

    def save_weekly_run_decision(
        self,
        decision: ReviewDecisionRecord,
        *,
        result_version: ScheduleVersion,
        latest_export_report: dict[str, Any],
        latest_export_plan: dict[str, Any],
        manual_override: ManualOverride | None = None,
    ) -> ReviewDecisionRecord:
        """Atomically persist a decision, child version and optional override.

        Repeating an idempotency key returns the original decision without
        touching the current pointer or duplicating the override.

        Correctness is enforced by the database transaction, not by any
        in-process lock: the current-version pointer is advanced with a
        conditional UPDATE (compare-and-swap on the expected source version
        and its content hash), so of two racing requests exactly one commits.
        The loser's transaction is rolled back whole — no child version,
        decision, or override row survives — and it surfaces either an
        idempotent replay (same key) or a structured stale-version conflict.
        """

        stored_idempotency_key = f"{decision.run_id}:{decision.idempotency_key}"
        try:
            with Session(self.engine) as session:
                replay = self._decision_for_key(
                    session, stored_idempotency_key, decision
                )
                if replay is not None:
                    return replay
                row = session.get(WeeklyRunDocument, decision.run_id)
                if row is None:
                    raise KeyError(decision.run_id)
                if decision.source_version_id != row.current_version_id:
                    raise WeeklyRunVersionConflictError(
                        run_id=decision.run_id,
                        source_version_id=decision.source_version_id,
                        current_version_id=row.current_version_id,
                    )
                if decision.resulting_version_id != result_version.id:
                    raise ValueError("decision resulting version does not match payload")
                if decision.content_hash != self._version_content_hash(result_version):
                    raise ValueError("decision content hash does not match result version")
                if result_version.parent_version_id != decision.source_version_id:
                    raise ValueError("decision result must parent the source version")
                self._validate_export_artifacts(
                    version=result_version,
                    content_hash=decision.content_hash,
                    report=latest_export_report,
                    plan=latest_export_plan,
                )
                if not self._advance_current_version(
                    session,
                    run_id=decision.run_id,
                    source_version_id=decision.source_version_id,
                    result_version_id=result_version.id,
                    result_content_hash=decision.content_hash,
                    latest_export_report=latest_export_report,
                    latest_export_plan=latest_export_plan,
                ):
                    # Lost the race: a concurrent request advanced the pointer
                    # first. Roll back before any child/decision insert.
                    session.rollback()
                    replay = self._replay_lost_race(
                        stored_idempotency_key, decision
                    )
                    if replay is not None:
                        return replay
                    raise WeeklyRunVersionConflictError(
                        run_id=decision.run_id,
                        source_version_id=decision.source_version_id,
                        current_version_id=self._current_version_id(
                            decision.run_id
                        ),
                    )
                self._insert_weekly_version(
                    session,
                    run_id=decision.run_id,
                    version=result_version,
                )
                session.add(WeeklyRunDecision(
                    decision_id=decision.decision_id,
                    run_id=decision.run_id,
                    idempotency_key=stored_idempotency_key,
                    payload_json=_json_dumps(decision.model_dump(mode="json")),
                    created_at=decision.timestamp,
                ))
                if manual_override is not None:
                    self._validate_review_override(decision, manual_override)
                    if session.get(
                        WeeklyRunManualOverride, manual_override.id
                    ) is not None:
                        raise ValueError(
                            f"manual override already exists: {manual_override.id}"
                        )
                    session.add(WeeklyRunManualOverride(
                        id=manual_override.id,
                        run_id=decision.run_id,
                        decision_id=decision.decision_id,
                        payload_json=_json_dumps(
                            manual_override.model_dump(mode="json")
                        ),
                        created_at=manual_override.created_at or decision.timestamp,
                    ))
                session.commit()
        except IntegrityError as exc:
            # A concurrent request with the same idempotency key (or the same
            # deterministic child version) committed between our checks and
            # our own commit; the transaction was rolled back whole.
            replay = self._replay_lost_race(stored_idempotency_key, decision)
            if replay is not None:
                return replay
            raise WeeklyRunVersionConflictError(
                run_id=decision.run_id,
                source_version_id=decision.source_version_id,
                current_version_id=self._current_version_id(decision.run_id),
            ) from exc
        return decision

    def _advance_current_version(
        self,
        session: Session,
        *,
        run_id: str,
        source_version_id: str,
        result_version_id: str,
        result_content_hash: str,
        latest_export_report: dict[str, Any],
        latest_export_plan: dict[str, Any],
    ) -> bool:
        """Advance the current pointer with a database-level compare-and-swap.

        The UPDATE only matches while the run still points at the expected
        source version with the expected content hash; the affected-row count
        tells the caller whether it won the race.
        """

        expected_hash = session.exec(
            select(WeeklyRunScheduleVersion.content_hash).where(
                WeeklyRunScheduleVersion.id == source_version_id,
                WeeklyRunScheduleVersion.run_id == run_id,
            )
        ).first()
        if expected_hash is None:
            raise ValueError("source version does not belong to the weekly run")
        result = session.execute(
            update(WeeklyRunDocument)
            .where(WeeklyRunDocument.id == run_id)
            .where(WeeklyRunDocument.current_version_id == source_version_id)
            .where(WeeklyRunDocument.latest_content_hash == expected_hash)
            .values(
                current_version_id=result_version_id,
                latest_export_report_json=_json_dumps(latest_export_report),
                latest_export_plan_json=_json_dumps(latest_export_plan),
                latest_content_hash=result_content_hash,
                updated_at=_now(),
            )
        )
        return result.rowcount == 1

    def _current_version_id(self, run_id: str) -> str:
        with Session(self.engine) as session:
            row = session.get(WeeklyRunDocument, run_id)
            return "" if row is None else row.current_version_id

    def _decision_for_key(
        self,
        session: Session,
        stored_idempotency_key: str,
        decision: ReviewDecisionRecord,
    ) -> ReviewDecisionRecord | None:
        """Return the stored decision for this key, or None when unused.

        A key reused for a different logical request fails loudly instead of
        replaying someone else's decision.
        """

        prior = session.exec(
            select(WeeklyRunDecision).where(
                WeeklyRunDecision.idempotency_key == stored_idempotency_key
            )
        ).first()
        if prior is None:
            return None
        prior_decision = ReviewDecisionRecord.model_validate(
            _json_loads(prior.payload_json, {})
        )
        if (
            self._decision_request_identity(prior_decision)
            != self._decision_request_identity(decision)
        ):
            raise ValueError(
                "idempotency key was already used for a different review request"
            )
        return prior_decision

    def _replay_lost_race(
        self,
        stored_idempotency_key: str,
        decision: ReviewDecisionRecord,
    ) -> ReviewDecisionRecord | None:
        """After losing a commit race, resolve a same-key winner as a replay."""

        with Session(self.engine) as session:
            return self._decision_for_key(
                session, stored_idempotency_key, decision
            )

    def get_review_decision(
        self,
        decision_id: str,
    ) -> ReviewDecisionRecord | None:
        with Session(self.engine) as session:
            row = session.get(WeeklyRunDecision, decision_id)
            if row is None:
                return None
            return ReviewDecisionRecord.model_validate(
                _json_loads(row.payload_json, {})
            )

    def list_weekly_run_decisions(self, run_id: str) -> list[ReviewDecisionRecord]:
        run = self.get_weekly_run(run_id)
        return [] if run is None else list(run.decisions)

    def list_weekly_run_overrides(self, run_id: str) -> list[ManualOverride]:
        run = self.get_weekly_run(run_id)
        if run is None:
            return []
        return [ManualOverride.model_validate(item) for item in run.manual_overrides]

    def save_weekly_run_publication(
        self,
        publication: PublicationRecord,
    ) -> PublicationRecord:
        """Persist one successful immutable final artifact, idempotently."""

        with Session(self.engine) as session:
            prior = session.get(WeeklyRunPublication, publication.publication_id)
            if prior is not None:
                stored = PublicationRecord.model_validate(
                    _json_loads(prior.payload_json, {})
                )
                if canonical_json(stored.model_dump(mode="json")) != canonical_json(
                    publication.model_dump(mode="json")
                ):
                    raise ValueError(
                        "immutable publication already exists with different facts"
                    )
                self._validate_publication_artifact(stored)
                return stored
            row = session.get(WeeklyRunDocument, publication.run_id)
            if row is None:
                raise KeyError(publication.run_id)
            if publication.source_version_id != row.current_version_id:
                raise ValueError("publication source version is stale")
            if publication.content_hash != row.latest_content_hash:
                raise ValueError("publication content hash is stale")
            version_row = session.get(
                WeeklyRunScheduleVersion, publication.source_version_id
            )
            if (
                version_row is None
                or version_row.run_id != publication.run_id
                or version_row.content_hash != publication.content_hash
            ):
                raise ValueError("publication version lineage is invalid")
            self._validate_publication_artifact(publication)
            session.add(WeeklyRunPublication(
                publication_id=publication.publication_id,
                run_id=publication.run_id,
                source_version_id=publication.source_version_id,
                payload_json=_json_dumps(publication.model_dump(mode="json")),
                created_at=publication.published_at,
            ))
            session.commit()
        return publication

    # --------------------------------------------------------------- imports
    def create_import_batch(
        self,
        *,
        summary: dict[str, Any],
        payload: dict[str, Any],
        source_names: list[str],
        ambiguities: list[dict[str, Any]],
    ) -> dict[str, Any]:
        batch_id = f"ib_{uuid4().hex[:12]}"
        created_at = _now()
        with Session(self.engine) as session:
            session.add(ImportBatchRecord(
                id=batch_id,
                created_at=created_at,
                source_names_json=_json_dumps(source_names),
                summary_json=_json_dumps(summary),
                payload_json=_json_dumps(payload),
            ))
            ambiguity_rows: list[ImportAmbiguityRecord] = []
            for idx, ambiguity in enumerate(ambiguities, start=1):
                source = ambiguity.get("source") or {}
                row = ImportAmbiguityRecord(
                    id=f"ia_{uuid4().hex[:12]}",
                    batch_id=batch_id,
                    code=str(ambiguity.get("code", "UNKNOWN")),
                    message=str(ambiguity.get("message", "")),
                    severity=str(ambiguity.get("severity", "warning")),
                    source_json=_json_dumps(source),
                    payload_json=_json_dumps({
                        "ordinal": idx,
                        **ambiguity,
                    }),
                )
                ambiguity_rows.append(row)
                session.add(row)
            session.commit()
            counts = self._ambiguity_counts(ambiguity_rows)
            return {
                "id": batch_id,
                "created_at": created_at.isoformat(),
                "source_names": source_names,
                "summary": summary,
                **counts,
            }

    def get_import_batch(self, batch_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            row = session.get(ImportBatchRecord, batch_id)
            if row is None:
                return None
            return self._batch_to_dict(row, session=session)

    def list_import_batches(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = session.exec(
                select(ImportBatchRecord).order_by(ImportBatchRecord.created_at)
            ).all()
            return [
                self._batch_to_dict(row, include_payload=False, session=session)
                for row in rows
            ]

    def list_import_ambiguities(
        self,
        *,
        status: str | None = "pending",
        batch_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            stmt = select(ImportAmbiguityRecord)
            rows = session.exec(stmt).all()
            out = []
            for row in rows:
                if status is not None and row.status != status:
                    continue
                if batch_id is not None and row.batch_id != batch_id:
                    continue
                out.append(self._ambiguity_to_dict(row))
            out.sort(key=lambda r: (r["created_at"], r["id"]))
            return out

    def resolve_import_ambiguity(
        self,
        ambiguity_id: str,
        *,
        status: str,
        resolution: dict[str, Any],
    ) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            row = session.get(ImportAmbiguityRecord, ambiguity_id)
            if row is None:
                return None
            row.status = status
            row.resolution_json = _json_dumps(resolution)
            row.resolved_at = _now()
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._ambiguity_to_dict(row)

    def save_alias_resolution(
        self,
        *,
        entity_type: str,
        alias: str,
        canonical_id: str,
        canonical_name: str | None = None,
        confidence: str = "manual",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = AliasResolutionRecord(
                entity_type=entity_type,
                alias=alias,
                canonical_id=canonical_id,
                canonical_name=canonical_name,
                confidence=confidence,
                payload_json=_json_dumps(payload or {}),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._alias_to_dict(row)

    def list_alias_resolutions(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = session.exec(select(AliasResolutionRecord)).all()
            return [self._alias_to_dict(row) for row in rows]

    # ---------------------------------------------------------- master data
    def save_master_data(
        self,
        payload: MasterDataSet,
        *,
        origin: str = "api",
        issues: list[MasterDataIssue] | None = None,
    ) -> dict[str, Any]:
        """Append a new active master-data document version."""

        computed_issues = issues if issues is not None else validate_master_data(payload)
        with Session(self.engine) as session:
            version = self._next_master_data_version(session)
            row = MasterDataVersionRecord(
                version=version,
                origin=origin,
                schema_version=payload.schema_version,
                payload_json=_json_dumps(payload.model_dump(mode="json")),
                issues_json=_json_dumps([
                    issue.model_dump(mode="json") for issue in computed_issues
                ]),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._master_data_to_dict(row)

    def get_master_data(self) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            row = self._latest_master_data_row(session)
            if row is None:
                return None
            return self._master_data_to_dict(row)

    def get_master_data_payload(self) -> MasterDataSet | None:
        current = self.get_master_data()
        if current is None:
            return None
        return MasterDataSet.model_validate(current["payload"])

    def list_master_data_versions(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = session.exec(select(MasterDataVersionRecord)).all()
            rows.sort(key=lambda row: row.version)
            return [
                {
                    "version": row.version,
                    "id": row.id,
                    "created_at": row.created_at.isoformat(),
                    "origin": row.origin,
                    "schema_version": row.schema_version,
                }
                for row in rows
            ]

    def get_master_data_issues(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            row = self._latest_master_data_row(session)
            if row is None:
                return []
            return _json_loads(row.issues_json, [])

    # ------------------------------------------------------------- internals
    def _insert_weekly_version(
        self,
        session: Session,
        *,
        run_id: str,
        version: ScheduleVersion,
    ) -> None:
        payload = _json_dumps(version.model_dump(mode="json"))
        content_hash = self._version_content_hash(version)
        prior = session.get(WeeklyRunScheduleVersion, version.id)
        if prior is not None:
            if (
                prior.run_id == run_id
                and prior.payload_json == payload
                and prior.content_hash == content_hash
            ):
                return
            raise ValueError(
                f"immutable schedule version already exists with different content: "
                f"{version.id}"
            )
        session.add(WeeklyRunScheduleVersion(
            id=version.id,
            run_id=run_id,
            kind=version.kind.value,
            parent_version_id=version.parent_version_id,
            created_at=version.created_at,
            payload_json=payload,
            content_hash=content_hash,
        ))

    def _load_required_json(
        self,
        raw: str | None,
        run_id: str,
        field: str,
        *,
        allow_null: bool = False,
    ) -> Any:
        if raw is None or raw == "":
            raise WeeklyRunStoreError(
                "WEEKLY_RUN_DATA_MISSING",
                f"stored weekly run is missing {field}",
                run_id=run_id,
                field=field,
            )
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise WeeklyRunStoreError(
                "WEEKLY_RUN_DATA_CORRUPT",
                f"stored weekly run has invalid JSON in {field}",
                run_id=run_id,
                field=field,
            ) from exc
        if value is None and not allow_null:
            raise WeeklyRunStoreError(
                "WEEKLY_RUN_DATA_MISSING",
                f"stored weekly run is missing {field}",
                run_id=run_id,
                field=field,
            )
        return value

    def _version_content_hash(self, version: ScheduleVersion) -> str:
        # Local import keeps the domain/store layer free of a module cycle.
        from ..scheduler import version_content_hash

        return version_content_hash(version)

    def _validate_review_override(
        self,
        decision: ReviewDecisionRecord,
        override: ManualOverride,
    ) -> None:
        expected = {
            "decision_id": decision.decision_id,
            "run_id": decision.run_id,
            "source_version_id": decision.source_version_id,
            "resulting_version_id": decision.resulting_version_id,
            "origin_audit_item_id": decision.audit_id,
        }
        for field, value in expected.items():
            if getattr(override, field) != value:
                raise ValueError(
                    f"manual override {field} does not match its review decision"
                )

    def _validate_publication_artifact(
        self,
        publication: PublicationRecord,
    ) -> None:
        path = Path(publication.artifact_path)
        if not path.is_file():
            raise WeeklyRunStoreError(
                "PUBLICATION_ARTIFACT_MISSING",
                "published final workbook is missing",
                run_id=publication.run_id,
                field="publications",
            )
        digest = hashlib.sha256()
        try:
            with path.open("rb") as artifact:
                for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise WeeklyRunStoreError(
                "PUBLICATION_ARTIFACT_UNREADABLE",
                "published final workbook cannot be read",
                run_id=publication.run_id,
                field="publications",
            ) from exc
        if digest.hexdigest() != publication.artifact_sha256:
            raise WeeklyRunStoreError(
                "PUBLICATION_ARTIFACT_CORRUPT",
                "published final workbook SHA-256 does not match its record",
                run_id=publication.run_id,
                field="publications",
            )

    def _decision_request_identity(
        self,
        decision: ReviewDecisionRecord,
    ) -> str:
        return canonical_json({
            "run_id": decision.run_id,
            "source_version_id": decision.source_version_id,
            "audit_id": decision.audit_id,
            "audit_ids": decision.audit_ids,
            "action": decision.action,
            "actor": decision.actor,
            "note": decision.note,
            "override_note": decision.override_note,
            "hard_bypass": decision.hard_bypass,
            "edited_entry_payload": (
                decision.edited_entry_payload.model_dump(mode="json")
                if decision.edited_entry_payload is not None
                else None
            ),
            "request_hash": decision.request_hash,
        })

    def _validate_export_artifacts(
        self,
        *,
        version: ScheduleVersion,
        content_hash: str,
        report: dict[str, Any],
        plan: dict[str, Any],
    ) -> None:
        reconciliation = report.get("reconciliation")
        if not isinstance(reconciliation, dict):
            raise ValueError("latest export report has no reconciliation")
        if reconciliation.get("version_id") != version.id:
            raise ValueError("latest export report version does not match current version")
        if reconciliation.get("content_hash") != content_hash:
            raise ValueError("latest export report content hash is stale")
        plan_version = plan.get("review_version")
        plan_report = plan.get("report")
        if not isinstance(plan_version, dict) or not isinstance(plan_report, dict):
            raise ValueError("latest export plan is incomplete")
        plan_reconciliation = plan_report.get("reconciliation")
        if not isinstance(plan_reconciliation, dict):
            raise ValueError("latest export plan has no reconciliation")
        if plan_version.get("id") != version.id:
            raise ValueError("latest export plan version does not match current version")
        if plan_reconciliation.get("version_id") != version.id:
            raise ValueError("latest export plan report has a stale version")
        if plan_reconciliation.get("content_hash") != content_hash:
            raise ValueError("latest export plan report content hash is stale")
        if not plan.get("integrity_hash"):
            raise ValueError("latest export plan has no integrity hash")

    def _upsert_meta(self, session: Session, key: str, payload: dict[str, Any]) -> None:
        row = session.get(StoreMeta, key)
        value = _json_dumps(payload)
        if row is None:
            session.add(StoreMeta(key=key, value_json=value))
        else:
            row.value_json = value
            row.updated_at = _now()

    def _upsert_meta_value(self, session: Session, key: str, value: Any) -> None:
        self._upsert_meta(session, key, {"value": value})

    def _upsert_version(
        self,
        session: Session,
        version: ScheduleVersion,
        *,
        is_current: bool,
    ) -> None:
        payload = _json_dumps(version.model_dump(mode="json"))
        row = session.get(StoredScheduleVersion, version.id)
        if row is None:
            row = StoredScheduleVersion(
                id=version.id,
                kind=version.kind.value,
                parent_version_id=version.parent_version_id,
                week_start=version.week_start.isoformat(),
                created_at=version.created_at,
                payload_json=payload,
                is_current=is_current,
            )
            session.add(row)
        else:
            row.kind = version.kind.value
            row.parent_version_id = version.parent_version_id
            row.week_start = version.week_start.isoformat()
            row.created_at = version.created_at
            row.payload_json = payload
            row.is_current = is_current
            row.updated_at = _now()

    def _batch_to_dict(
        self,
        row: ImportBatchRecord,
        *,
        include_payload: bool = True,
        session: Session | None = None,
    ) -> dict[str, Any]:
        out = {
            "id": row.id,
            "created_at": row.created_at.isoformat(),
            "source_names": _json_loads(row.source_names_json, []),
            "summary": _json_loads(row.summary_json, {}),
        }
        if session is not None:
            ambiguity_rows = session.exec(
                select(ImportAmbiguityRecord).where(
                    ImportAmbiguityRecord.batch_id == row.id)
            ).all()
            out.update(self._ambiguity_counts(ambiguity_rows))
        if include_payload:
            out["payload"] = _json_loads(row.payload_json, {})
        return out

    def _ambiguity_counts(
        self,
        rows: list[ImportAmbiguityRecord],
    ) -> dict[str, int]:
        pending = [row for row in rows if row.status == "pending"]
        return {
            "ambiguity_count": len(rows),
            "pending_ambiguity_count": len(pending),
            "blocking_ambiguity_count": sum(
                1 for row in pending if row.severity == "blocking"
            ),
        }

    def _ambiguity_to_dict(self, row: ImportAmbiguityRecord) -> dict[str, Any]:
        return {
            "id": row.id,
            "batch_id": row.batch_id,
            "code": row.code,
            "message": row.message,
            "severity": row.severity,
            "status": row.status,
            "source": _json_loads(row.source_json, {}),
            "payload": _json_loads(row.payload_json, {}),
            "resolution": _json_loads(row.resolution_json, None),
            "created_at": row.created_at.isoformat(),
            "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        }

    def _alias_to_dict(self, row: AliasResolutionRecord) -> dict[str, Any]:
        return {
            "id": row.id,
            "entity_type": row.entity_type,
            "alias": row.alias,
            "canonical_id": row.canonical_id,
            "canonical_name": row.canonical_name,
            "confidence": row.confidence,
            "payload": _json_loads(row.payload_json, {}),
            "created_at": row.created_at.isoformat(),
        }

    def _next_master_data_version(self, session: Session) -> int:
        rows = session.exec(select(MasterDataVersionRecord)).all()
        if not rows:
            return 1
        return max(row.version for row in rows) + 1

    def _latest_master_data_row(
        self,
        session: Session,
    ) -> MasterDataVersionRecord | None:
        rows = session.exec(select(MasterDataVersionRecord)).all()
        if not rows:
            return None
        return max(rows, key=lambda row: row.version)

    def _master_data_to_dict(self, row: MasterDataVersionRecord) -> dict[str, Any]:
        return {
            "version": row.version,
            "id": row.id,
            "created_at": row.created_at.isoformat(),
            "origin": row.origin,
            "schema_version": row.schema_version,
            "payload": _json_loads(row.payload_json, {}),
            "issues": _json_loads(row.issues_json, []),
        }
