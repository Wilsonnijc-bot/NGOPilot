"""Phase 1B weekly-run review transitions.

The API layer supplies a durable run and the current division layout.  This
module owns immutable child construction, atomic audit-group transitions,
independent validation/preflight, and the linked manual-override value object.
It deliberately does not persist anything; ``RosterStore`` remains the one
atomic write boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..domain import (
    AuditItem,
    AuditStatus,
    EntrySource,
    EntryStatus,
    ManualOverride,
    ManualOverridePin,
    Period,
    ReviewDecisionRecord,
    ScheduleEntry,
    ScheduleVersion,
    VersionKind,
    WeeklyRunRecord,
    canonical_json,
    content_fingerprint,
    stable_id,
)
from ..exporter import GeneratedDivisionExportReport, prepare_generated_division_roster_export
from ..exporter.division_writer import GeneratedDivisionExportPlan
from ..importer import DivisionImportResult
from ..scheduler import GeneratedDemands, version_content_hash


class WeeklyReviewCommand(BaseModel):
    """One fail-closed approve/reject/edit request."""

    model_config = ConfigDict(extra="forbid")

    source_version_id: str
    content_hash: str
    idempotency_key: str
    actor: str
    action: Literal["approve", "reject", "edit"]
    audit_id: str
    audit_ids: list[str] = Field(default_factory=list)
    note: str | None = None
    override_note: str | None = None
    edited_entry: dict[str, Any] | None = None

    @field_validator(
        "source_version_id",
        "content_hash",
        "idempotency_key",
        "actor",
        "audit_id",
        mode="before",
    )
    @classmethod
    def _required_string(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
        if not value:
            raise ValueError("審核請求的識別欄位不可留空")
        return value

    @field_validator("note", "override_note", mode="before")
    @classmethod
    def _optional_note(cls, value: Any) -> Any:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("audit_ids", mode="after")
    @classmethod
    def _canonical_audit_ids(cls, value: list[str]) -> list[str]:
        return sorted({item.strip() for item in value if item.strip()})

    @model_validator(mode="after")
    def _action_requirements(self) -> "WeeklyReviewCommand":
        if self.action in {"reject", "edit"} and not self.note:
            action_label = "強制略過" if self.action == "reject" else "修改"
            raise ValueError(f"{action_label}操作必須填寫備註")
        if self.action == "edit" and not self.edited_entry:
            raise ValueError("修改操作必須提供修改後的排班項目")
        if self.action != "edit" and self.edited_entry is not None:
            raise ValueError("只有修改操作可以提供修改後的排班項目")
        if self.action != "edit" and self.override_note is not None:
            raise ValueError("只有修改操作可以提供硬規則覆核說明")
        return self


class WeeklyRevalidateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_version_id: str
    content_hash: str

    @field_validator("source_version_id", "content_hash", mode="before")
    @classmethod
    def _required_string(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
        if not value:
            raise ValueError("重新驗證所需的識別欄位不可留空")
        return value


class WeeklyReviewError(ValueError):
    """Service error with an API-safe status/code/payload."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        **context: Any,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.context = context
        super().__init__(message)

    def as_detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), **self.context}


@dataclass
class WeeklyReviewOutcome:
    version: ScheduleVersion
    report: GeneratedDivisionExportReport
    plan: GeneratedDivisionExportPlan
    decision: ReviewDecisionRecord
    manual_override: ManualOverride | None = None


def validate_current_version(
    record: WeeklyRunRecord,
    *,
    source_version_id: str,
    content_hash: str,
) -> ScheduleVersion:
    """Resolve the exact durable current version or reject stale input."""

    if source_version_id != record.current_version_id:
        raise WeeklyReviewError(
            409,
            "STALE_SCHEDULE_VERSION",
            "審核請求所指的版本已不是目前保存版本，請重新載入後再操作",
            current_version_id=record.current_version_id,
            source_version_id=source_version_id,
        )
    current = next(
        (item for item in record.versions if item.id == record.current_version_id),
        None,
    )
    if current is None:
        raise WeeklyReviewError(
            409,
            "WEEKLY_RUN_DATA_MISSING",
            "找不到目前保存的排班版本",
            run_id=record.run_id,
        )
    expected_hash = version_content_hash(current)
    if content_hash != expected_hash or content_hash != record.latest_content_hash:
        raise WeeklyReviewError(
            409,
            "STALE_CONTENT_HASH",
            "審核內容已過期，請重新載入最新排班後再操作",
            current_content_hash=record.latest_content_hash,
            supplied_content_hash=content_hash,
        )
    return current


def apply_weekly_review(
    record: WeeklyRunRecord,
    division_layout: DivisionImportResult,
    command: WeeklyReviewCommand,
) -> WeeklyReviewOutcome:
    """Build and fully preflight one immutable review child."""

    current = validate_current_version(
        record,
        source_version_id=command.source_version_id,
        content_hash=command.content_hash,
    )
    audit_by_id = {item.id: item for item in current.audit_items}
    if command.audit_id not in audit_by_id:
        raise WeeklyReviewError(
            404,
            "AUDIT_ITEM_NOT_FOUND",
            "在原排班版本中找不到此審核項目",
            audit_id=command.audit_id,
        )
    supplied_ids = {command.audit_id, *command.audit_ids}
    unknown = sorted(supplied_ids - set(audit_by_id))
    if unknown:
        raise WeeklyReviewError(
            404,
            "AUDIT_ITEM_NOT_FOUND",
            "找不到一個或多個需要一併處理的審核項目",
            audit_ids=unknown,
        )
    required_ids = _atomic_audit_group(current.audit_items, command.audit_id)
    if command.action == "reject":
        # A supervisor may hard-bypass several independent review groups in
        # one immutable decision, but every selected dependency group must
        # still be complete.
        required_ids = set().union(*(
            _atomic_audit_group(current.audit_items, audit_id)
            for audit_id in supplied_ids
        ))
    if supplied_ids != required_ids:
        raise WeeklyReviewError(
            409,
            "ATOMIC_REVIEW_GROUP_REQUIRED",
            "互相依賴或連鎖調動的審核項目必須一次過一併處理",
            supplied_audit_ids=sorted(supplied_ids),
            required_audit_ids=sorted(required_ids),
        )
    already_decided = sorted(
        audit_id for audit_id in required_ids
        if audit_by_id[audit_id].status != AuditStatus.PENDING
    )
    if already_decided:
        raise WeeklyReviewError(
            409,
            "AUDIT_ITEM_ALREADY_DECIDED",
            "一個或多個審核項目已處理，不再是待審核狀態",
            audit_ids=already_decided,
        )

    now = datetime.now(timezone.utc)
    child_id = stable_id("ver_", "weekly_review_version", {
        "run_id": record.run_id,
        "source_version_id": current.id,
        "action": command.action,
        "audit_ids": sorted(required_ids),
        "idempotency_key": command.idempotency_key,
    })
    decision_id = stable_id("dec_", "review_decision", {
        "run_id": record.run_id,
        "audit_id": command.audit_id,
        "resulting_version_id": child_id,
    })
    child = current.model_copy(deep=True, update={
        "id": child_id,
        "kind": VersionKind.MANUAL_EDIT,
        "parent_version_id": current.id,
        "created_at": now,
        "reconciliation": None,
    })
    child_audits = {item.id: item for item in child.audit_items}

    status = {
        "approve": AuditStatus.APPROVED,
        "reject": AuditStatus.REJECTED,
        "edit": AuditStatus.EDITED,
    }[command.action]
    for audit_id in required_ids:
        audit = child_audits[audit_id]
        audit.status = status
        audit.decision_id = decision_id
        audit.human_note = command.note
        audit.decided_at = now

    generated = GeneratedDemands.model_validate(record.generated_payload)
    override_id: str | None = None
    edited_demand_id: str | None = None
    if command.action == "approve":
        _approve_suggestions(child, required_ids, record)
    elif command.action == "reject":
        _hard_bypass_audits(child, required_ids, generated, command.note or "")
    else:
        override_id = stable_id("ovr_", "weekly_review_override", {
            "run_id": record.run_id,
            "source_version_id": current.id,
            "audit_ids": sorted(required_ids),
            "idempotency_key": command.idempotency_key,
        })
        edited_demand_id = _apply_edit(
            child,
            required_ids,
            record,
            command.edited_entry or {},
            override_id,
        )

    plan = prepare_generated_division_roster_export(
        division_layout=division_layout,
        dataset=record.dataset,
        version=child,
        generated=generated,
    )
    violations = plan.report.validator_violations
    if violations and command.action in {"approve", "edit"} and not command.override_note:
        raise WeeklyReviewError(
            422,
            "HARD_CONSTRAINT_OVERRIDE_REQUIRED",
            "此排班安排違反硬性排班規則；如確需保留，請填寫硬規則覆核說明",
            violations=[item.model_dump(mode="json") for item in violations],
        )
    if command.action == "approve" and command.override_note:
        # Defensive only; the request model already forbids this combination.
        raise WeeklyReviewError(
            422,
            "APPROVE_CANNOT_OVERRIDE_HARD_RULES",
            "批准操作不能略過硬性排班規則，請改用修改並填寫覆核說明",
        )
    if command.action == "edit" and command.override_note and not violations:
        raise WeeklyReviewError(
            422,
            "OVERRIDE_NOTE_NOT_REQUIRED",
            "目前沒有硬規則衝突，不需要填寫硬規則覆核說明",
        )

    result_version = plan.review_version
    edited_entry: ScheduleEntry | None = None
    manual_override: ManualOverride | None = None
    if command.action == "edit":
        edited_entry = next(
            (
                item for item in result_version.entries
                if item.demand_id == edited_demand_id and override_id in item.override_ids
            ),
            None,
        )
        if edited_entry is None:
            raise WeeklyReviewError(
                409,
                "EDITED_ENTRY_PROVENANCE_MISSING",
                "匯出前檢查未能保留修改項目或覆核記錄，已停止保存",
            )
        manual_override = ManualOverride(
            id=override_id or "",
            scope="entry",
            pin=ManualOverridePin(
                worker_id=edited_entry.worker_id,
                elder_id=edited_entry.elder_id,
                date=edited_entry.schedule_date,
                weekday=edited_entry.weekday,
                period=edited_entry.period,
                service_code=edited_entry.service_code,
            ),
            action="pin_assignment",
            reason=command.override_note or command.note or "人工審核修改",
            effective_from=edited_entry.schedule_date,
            effective_to=edited_entry.schedule_date,
            origin_audit_item_id=command.audit_id,
            decision_id=decision_id,
            run_id=record.run_id,
            source_version_id=current.id,
            resulting_version_id=result_version.id,
            actor=command.actor,
            created_at=now,
        )

    decision = ReviewDecisionRecord(
        decision_id=decision_id,
        run_id=record.run_id,
        source_version_id=current.id,
        resulting_version_id=result_version.id,
        audit_id=command.audit_id,
        audit_ids=sorted(required_ids),
        action=command.action,
        actor=command.actor,
        timestamp=now,
        note=command.note,
        override_note=command.override_note,
        hard_bypass=command.action == "reject",
        edited_entry_payload=edited_entry,
        validator_result=violations,
        content_hash=version_content_hash(result_version),
        idempotency_key=command.idempotency_key,
        request_hash=_command_request_hash(command),
    )
    return WeeklyReviewOutcome(
        version=result_version,
        report=plan.report,
        plan=plan,
        decision=decision,
        manual_override=manual_override,
    )


def idempotent_decision_matches(
    decision: ReviewDecisionRecord,
    command: WeeklyReviewCommand,
) -> bool:
    """Check whether an API retry matches the persisted logical request."""

    if decision.request_hash is not None:
        return decision.request_hash == _command_request_hash(command)
    if (
        decision.source_version_id != command.source_version_id
        or decision.audit_id != command.audit_id
        or set(decision.audit_ids) != {command.audit_id, *command.audit_ids}
        or decision.action != command.action
        or decision.actor != command.actor
        or decision.note != command.note
        or decision.override_note != command.override_note
    ):
        return False
    if command.action != "edit":
        return True
    edited = decision.edited_entry_payload
    if edited is None:
        return False
    for key, value in (command.edited_entry or {}).items():
        if key == "entry_id":
            continue
        actual = getattr(edited, key, None)
        actual_json = getattr(actual, "value", actual)
        if isinstance(actual_json, (date, datetime)):
            actual_json = actual_json.isoformat()
        if canonical_json(actual_json) != canonical_json(value):
            return False
    return True


def _command_request_hash(command: WeeklyReviewCommand) -> str:
    edited = dict(command.edited_entry or {})
    if "schedule_date" in edited and edited["schedule_date"] is not None:
        edited["schedule_date"] = date.fromisoformat(
            str(edited["schedule_date"])
        ).isoformat()
    if "period" in edited and edited["period"] is not None:
        edited["period"] = Period(str(edited["period"])).value
    for field in ("start_time", "end_time"):
        if field in edited and edited[field] is not None:
            edited[field] = time.fromisoformat(str(edited[field])).isoformat()
    if "session_index" in edited and edited["session_index"] is not None:
        edited["session_index"] = int(edited["session_index"])
    if "entry_id" in edited:
        edited["entry_id"] = str(edited["entry_id"]).strip()
    if "worker_id" in edited and edited["worker_id"] is not None:
        edited["worker_id"] = str(edited["worker_id"]).strip()
    return content_fingerprint({
        "source_version_id": command.source_version_id,
        "content_hash": command.content_hash,
        "idempotency_key": command.idempotency_key,
        "actor": command.actor,
        "action": command.action,
        "audit_id": command.audit_id,
        "audit_ids": sorted({command.audit_id, *command.audit_ids}),
        "note": command.note,
        "override_note": command.override_note,
        "edited_entry": edited or None,
    })


def _atomic_audit_group(audits: list[AuditItem], seed_id: str) -> set[str]:
    ids = {item.id for item in audits}
    adjacency: dict[str, set[str]] = {item: set() for item in ids}
    for audit in audits:
        for dependency in audit.depends_on:
            if dependency not in ids:
                raise WeeklyReviewError(
                    409,
                    "AUDIT_DEPENDENCY_MISSING",
                    "原排班版本缺少此審核項目的相依項目",
                    audit_id=audit.id,
                    dependency_id=dependency,
                )
            adjacency[audit.id].add(dependency)
            adjacency[dependency].add(audit.id)
    pending = [seed_id]
    group: set[str] = set()
    while pending:
        audit_id = pending.pop()
        if audit_id in group:
            continue
        group.add(audit_id)
        pending.extend(sorted(adjacency[audit_id] - group))
    return group


def _approve_suggestions(
    child: ScheduleVersion,
    audit_ids: set[str],
    record: WeeklyRunRecord,
) -> None:
    suggestions: dict[str, ScheduleEntry] = {}
    for audit in child.audit_items:
        if audit.id not in audit_ids:
            continue
        candidates = [audit.suggested_entry]
        candidates.extend(step.entry_after for step in audit.chain)
        for candidate in candidates:
            if candidate is None or not candidate.demand_id:
                continue
            prior = suggestions.get(candidate.demand_id)
            if prior is not None and canonical_json(prior) != canonical_json(candidate):
                raise WeeklyReviewError(
                    409,
                    "CONFLICTING_ATOMIC_SUGGESTIONS",
                    "需要一併處理的審核項目包含互相衝突的建議",
                    demand_id=candidate.demand_id,
                )
            suggestions[candidate.demand_id] = candidate
    if not suggestions:
        raise WeeklyReviewError(
            422,
            "AUDIT_HAS_NO_APPROVABLE_SUGGESTION",
            "此項沒有可直接批准的替補建議；請補充資料或使用修改功能",
            audit_ids=sorted(audit_ids),
        )
    for demand_id, suggestion in suggestions.items():
        revision = _next_revision(child, demand_id)
        target = suggestion.model_copy(deep=True)
        target.entry_role = "current"
        target.revision = revision
        target.source = EntrySource.SYSTEM_REASSIGNED
        target.status = (
            EntryStatus.NEEDS_REVIEW
            if _uses_uncertainty(target)
            else EntryStatus.SCHEDULED
        )
        if target.status == EntryStatus.SCHEDULED:
            # The decided audit item keeps these reasons for traceability; a
            # supervisor-approved entry with no remaining uncertainty must
            # export as a normal scheduled cell instead of re-blocking the run.
            target.review_reasons = []
        target.audit_ids = sorted({*target.audit_ids, *audit_ids})
        _normalize_worker_name(target, record)
        _replace_demand_entries(child, demand_id, target)


HARD_BYPASS_FLAG = "supervisor_hard_bypass"


def _hard_bypass_audits(
    child: ScheduleVersion,
    audit_ids: set[str],
    generated: GeneratedDemands,
    note: str,
) -> None:
    """Keep the supervisor-selected terminal state and waive its blocker."""

    selected = [item for item in child.audit_items if item.id in audit_ids]
    demand_ids = {
        demand_id for audit in selected for demand_id in audit.demand_ids
    }
    generated_by_id = {
        item.demand_id: item
        for item in [
            *generated.weekly_demands,
            *generated.suppressed_weekly_demands,
        ]
        if item.demand_id
    }
    for demand_id in sorted(demand_ids):
        existing = [item for item in child.entries if item.demand_id == demand_id]
        current = next(
            (
                item for item in existing
                if item.entry_role != "alternative" and item.superseded_by is None
            ),
            None,
        )
        source = current or next(
            (
                entry for audit in selected
                for entry in (audit.original_entry,)
                if entry is not None and entry.demand_id == demand_id
            ),
            None,
        )
        if source is None:
            demand = generated_by_id.get(demand_id)
            if (
                demand is None
                or demand.task_date is None
                or demand.period is None
                or demand.service_code is None
            ):
                raise WeeklyReviewError(
                    422,
                    "HARD_BYPASS_DISPOSITION_UNAVAILABLE",
                    "強制略過後無法建立可追溯的任務終止狀態",
                    demand_id=demand_id,
                )
            source = ScheduleEntry(
                id=f"pending-hard-bypass-{demand_id}",
                demand_id=demand_id,
                schedule_date=demand.task_date,
                weekday=demand.weekday or demand.task_date.isoweekday(),
                period=demand.period,
                session_index=demand.session_index,
                service_code=demand.service_code,
                elder_id=demand.elder_id,
                center=demand.centre,
                district=demand.district,
                route=demand.route,
                destination=demand.destination,
                start_time=demand.start_time,
                end_time=demand.end_time,
                source_refs=list(demand.source_refs),
                source_evidence=list(demand.source_evidence),
                data_gap_ids=list(demand.data_gap_ids),
                assumptions=list(demand.assumptions),
                override_ids=list(demand.override_ids),
                depends_on=list(demand.depends_on),
            )
        bypassed = source.model_copy(deep=True)
        bypassed.entry_role = "manual"
        bypassed.revision = _next_revision(child, demand_id)
        bypassed.source = EntrySource.MANUAL
        bypassed.audit_ids = sorted({*bypassed.audit_ids, *audit_ids})
        bypassed.constraint_flags = sorted({
            *bypassed.constraint_flags,
            HARD_BYPASS_FLAG,
        })
        if current is None or current.status in {
            EntryStatus.UNASSIGNED,
            EntryStatus.CANCELLED,
        }:
            bypassed.worker_id = None
            bypassed.worker_name = None
            bypassed.status = EntryStatus.CANCELLED
            bypassed.explanation = f"主管強制略過，停止本週執行：{note}"
        else:
            bypassed.status = EntryStatus.SCHEDULED
            bypassed.explanation = f"主管強制略過並保留目前安排：{note}"
        _replace_demand_entries(child, demand_id, bypassed)


_EDITABLE_ENTRY_FIELDS = {
    "worker_id",
    "schedule_date",
    "period",
    "session_index",
    "start_time",
    "end_time",
    "notes",
}


def _apply_edit(
    child: ScheduleVersion,
    audit_ids: set[str],
    record: WeeklyRunRecord,
    patch: dict[str, Any],
    override_id: str,
) -> str:
    entry_id = str(patch.get("entry_id") or "").strip()
    if not entry_id:
        raise WeeklyReviewError(
            422,
            "EDIT_ENTRY_ID_REQUIRED",
            "修改排班時必須指定原排班項目編號",
        )
    forbidden = sorted(set(patch) - {"entry_id", *_EDITABLE_ENTRY_FIELDS})
    if forbidden:
        raise WeeklyReviewError(
            422,
            "EDIT_PROVENANCE_FIELDS_FORBIDDEN",
            "修改操作不可更換任務、來源、資料缺口、審核或原始追溯資料",
            forbidden_fields=forbidden,
        )
    selected = [item for item in child.audit_items if item.id in audit_ids]
    candidates = [item for item in child.entries if item.id == entry_id]
    for audit in selected:
        candidates.extend(
            item for item in [audit.suggested_entry, audit.original_entry]
            if item is not None and item.id == entry_id
        )
        candidates.extend(
            item for step in audit.chain
            for item in (step.entry_before, step.entry_after)
            if item is not None and item.id == entry_id
        )
    if not candidates:
        raise WeeklyReviewError(
            404,
            "SCHEDULE_ENTRY_NOT_FOUND",
            "要修改的排班項目不屬於此審核組別",
            entry_id=entry_id,
        )
    base = candidates[0]
    if not base.demand_id or not any(
        base.demand_id in audit.demand_ids or base.id in audit.entry_ids
        for audit in selected
    ):
        raise WeeklyReviewError(
            422,
            "EDIT_ENTRY_NOT_LINKED_TO_AUDIT",
            "修改後的排班項目未連結至指定審核組別",
            entry_id=entry_id,
        )
    payload = base.model_dump(mode="python")
    payload.update({key: value for key, value in patch.items() if key != "entry_id"})
    payload.update({
        "id": base.id,
        "entry_role": "manual",
        "revision": _next_revision(child, base.demand_id),
        "source": EntrySource.MANUAL,
        "status": EntryStatus.SCHEDULED,
        "audit_ids": sorted({*base.audit_ids, *audit_ids}),
        "override_ids": sorted({*base.override_ids, override_id}),
    })
    try:
        edited = ScheduleEntry.model_validate(payload)
    except (TypeError, ValueError) as exc:
        raise WeeklyReviewError(
            422,
            "EDITED_ENTRY_INVALID",
            "修改後的排班項目格式無效，請檢查同工、日期及時段",
        ) from exc
    week_end = child.week_start + timedelta(days=6)
    if not child.week_start <= edited.schedule_date <= week_end:
        raise WeeklyReviewError(
            422,
            "EDIT_OUTSIDE_RUN_WEEK",
            "修改後的日期必須位於本次排班週內",
        )
    edited.weekday = edited.schedule_date.isoweekday()  # type: ignore[assignment]
    if not edited.worker_id:
        raise WeeklyReviewError(
            422,
            "EDIT_WORKER_REQUIRED",
            "修改排班時必須指定同工編號",
        )
    _normalize_worker_name(edited, record)
    edited.status = (
        EntryStatus.NEEDS_REVIEW
        if _uses_uncertainty(edited)
        else EntryStatus.SCHEDULED
    )
    if edited.status == EntryStatus.SCHEDULED:
        # The reviewer just decided this entry; hard rules are re-checked
        # independently below, so stale review markers must not keep the
        # edited entry out of the exported grid.
        edited.review_reasons = []
    _replace_demand_entries(child, base.demand_id, edited)
    anchor = selected[0]
    anchor.suggested_entry = edited.model_copy(deep=True)
    anchor.entry_ids = sorted({*anchor.entry_ids, edited.id})
    anchor.override_ids = sorted({*anchor.override_ids, override_id})
    return base.demand_id


def _replace_demand_entries(
    version: ScheduleVersion,
    demand_id: str,
    replacement: ScheduleEntry,
) -> None:
    version.entries = [item for item in version.entries if item.demand_id != demand_id]
    version.entries.append(replacement)


def _next_revision(version: ScheduleVersion, demand_id: str) -> int:
    revisions = [
        item.revision for item in version.entries if item.demand_id == demand_id
    ]
    for audit in version.audit_items:
        embedded = [audit.original_entry, audit.suggested_entry, *audit.alternatives]
        embedded.extend(step.entry_before for step in audit.chain)
        embedded.extend(step.entry_after for step in audit.chain)
        revisions.extend(
            item.revision for item in embedded
            if item is not None and item.demand_id == demand_id
        )
    return max(revisions, default=0) + 1


def _uses_uncertainty(entry: ScheduleEntry) -> bool:
    return bool(
        entry.data_gap_ids
        or any(item.confidence in {"low", "seed"} for item in entry.source_evidence)
        or "gender_ok_unverified" in entry.constraint_flags
        or "seed_skill_unverified" in entry.constraint_flags
        or "route_qualification_unverified" in entry.constraint_flags
    )


def _normalize_worker_name(entry: ScheduleEntry, record: WeeklyRunRecord) -> None:
    worker = record.dataset.employee_map().get(entry.worker_id or "")
    entry.worker_name = worker.display_name if worker is not None else None
