"""Schedule output entities: entries, audit items, versions, change events."""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .entities import EscortRequest, Weekday
from .enums import (
    AuditKind,
    AuditStatus,
    ChangeType,
    EntrySource,
    EntryStatus,
    Period,
    ReviewReasonCode,
    ServiceCode,
    Severity,
    VersionKind,
)
from .provenance import (
    DemandDisposition,
    DemandReconciliationReport,
    GapPolicy,
    SourceEvidence,
    merge_source_evidence,
    normalize_identity_string,
    stable_id,
)


class ManualReviewReason(BaseModel):
    """Structured review reason: machine-readable code + params + rendered text."""

    code: ReviewReasonCode
    message: str
    params: dict[str, str] = Field(default_factory=dict)
    rule_ref: str | None = None  # rulebook.md rule id, e.g. "RB-EXCL-02"


class ChangeEvent(BaseModel):
    id: str | None = None
    type: ChangeType
    change_date: date
    period: Period | None = None          # None = full day (for leave)
    worker_id: str | None = None          # leave
    elder_id: str | None = None           # elder_cancellation
    escort_request_id: str | None = None  # escort_cancelled
    new_escort: EscortRequest | None = None  # escort_new
    reason: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    source_evidence: list[SourceEvidence] = Field(default_factory=list)
    data_gap_ids: list[str] = Field(default_factory=list)
    data_gap_policies: dict[str, GapPolicy] = Field(default_factory=dict)
    override_ids: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)

    @field_validator(
        "id", "worker_id", "elder_id", "escort_request_id", mode="before"
    )
    @classmethod
    def _normalize_optional_identities(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = normalize_identity_string(value)
        return normalized or None

    @field_validator(
        "source_refs", "data_gap_ids", "override_ids", "depends_on",
        mode="before",
    )
    @classmethod
    def _normalize_identity_lists(cls, value: object) -> object:
        if not isinstance(value, (list, tuple)):
            return value
        normalized = [
            normalize_identity_string(item) for item in value
            if isinstance(item, str) and normalize_identity_string(item)
        ]
        return sorted(set(normalized))

    @model_validator(mode="after")
    def _stable_default_id(self) -> "ChangeEvent":
        self.source_refs = sorted(set(self.source_refs))
        self.source_evidence = merge_source_evidence(self.source_evidence)
        self.data_gap_ids = sorted(set(self.data_gap_ids))
        self.override_ids = sorted(set(self.override_ids))
        self.depends_on = sorted(set(self.depends_on))
        required_target = {
            ChangeType.LEAVE: (self.worker_id, "worker_id"),
            ChangeType.ELDER_CANCELLATION: (self.elder_id, "elder_id"),
            ChangeType.ESCORT_CANCELLED: (
                self.escort_request_id, "escort_request_id"
            ),
            ChangeType.ESCORT_NEW: (self.new_escort, "new_escort"),
        }[self.type]
        if required_target[0] is None:
            raise ValueError(
                f"{self.type.value} change event requires {required_target[1]}"
            )
        if self.type == ChangeType.ESCORT_NEW and self.new_escort is not None:
            if self.change_date != self.new_escort.service_date:
                raise ValueError(
                    "escort_new change_date must match new_escort.service_date"
                )
            if self.period is None:
                self.period = self.new_escort.period
            elif self.period != self.new_escort.period:
                raise ValueError(
                    "escort_new period must match new_escort.period"
                )
        if not self.id:
            self.id = stable_id("chg_", "change_event", {
                "type": self.type,
                "change_date": self.change_date,
                "period": self.period,
                "worker_id": self.worker_id,
                "elder_id": self.elder_id,
                "escort_request_id": self.escort_request_id,
                "new_escort_id": self.new_escort.id if self.new_escort else None,
            })
        return self


class ScheduleEntry(BaseModel):
    id: str
    demand_id: str | None = None
    entry_role: Literal["current", "alternative", "manual"] = "current"
    revision: int = 1
    schedule_date: date
    weekday: Weekday
    period: Period
    session_index: Literal[1, 2] | None = 1  # None = occupies the whole half-day
    worker_id: str | None = None
    worker_name: str | None = None
    service_code: ServiceCode
    elder_id: str | None = None
    elder_name: str | None = None
    center: str | None = None
    district: str | None = None
    route: str | None = None
    destination: str | None = None
    start_time: time | None = None
    end_time: time | None = None
    source: EntrySource = EntrySource.TEMPLATE
    status: EntryStatus = EntryStatus.SCHEDULED
    explanation: str | None = None
    review_reasons: list[ManualReviewReason] = Field(default_factory=list)
    constraint_flags: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    source_evidence: list[SourceEvidence] = Field(default_factory=list)
    data_gap_ids: list[str] = Field(default_factory=list)
    data_gap_policies: dict[str, GapPolicy] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    audit_ids: list[str] = Field(default_factory=list)
    override_ids: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    origin_fixed_service_id: str | None = None
    origin_escort_request_id: str | None = None
    superseded_by: str | None = None  # entry id that replaced this one
    notes: str | None = None

    @model_validator(mode="after")
    def _canonical_provenance(self) -> "ScheduleEntry":
        self.source_refs = sorted(set(self.source_refs))
        self.source_evidence = merge_source_evidence(self.source_evidence)
        self.data_gap_ids = sorted(set(self.data_gap_ids))
        self.audit_ids = sorted(set(self.audit_ids))
        self.override_ids = sorted(set(self.override_ids))
        self.depends_on = sorted(set(self.depends_on))
        return self

    @property
    def occupies_full_period(self) -> bool:
        return self.session_index is None


class AuditItem(BaseModel):
    id: str
    version_id: str | None = None
    dedupe_key: str | None = None
    kind: AuditKind
    severity: Severity = Severity.WARNING
    blocking: bool = False
    status: AuditStatus = AuditStatus.PENDING
    reason: str  # human-readable one-liner (kept for frontend compatibility)
    reasons: list[ManualReviewReason] = Field(default_factory=list)
    original_entry: ScheduleEntry | None = None
    suggested_entry: ScheduleEntry | None = None
    alternatives: list[ScheduleEntry] = Field(default_factory=list)
    chain: list["ChainStep"] = Field(default_factory=list)  # displacement chains
    trigger_event_id: str | None = None
    demand_ids: list[str] = Field(default_factory=list)
    entry_ids: list[str] = Field(default_factory=list)
    data_gap_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    decision_id: str | None = None
    override_ids: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    human_note: str | None = None
    decided_at: datetime | None = None


class ChainStep(BaseModel):
    step: int
    action: Literal["assign", "reassign", "cancel"]
    entry_before: ScheduleEntry | None = None
    entry_after: ScheduleEntry
    explanation: str


class ImpactItem(BaseModel):
    id: str
    severity: Severity
    title: str
    description: str
    requires_review: bool = False
    affected_entry_ids: list[str] = Field(default_factory=list)
    affected_worker_ids: list[str] = Field(default_factory=list)
    affected_elder_ids: list[str] = Field(default_factory=list)
    suggested_entry_ids: list[str] = Field(default_factory=list)


class ImpactReport(BaseModel):
    """Per-change-event impact analysis (Task: impact analyzer output)."""

    event: ChangeEvent
    risk_level: Severity
    requires_review: bool
    summary: str
    impacts: list[ImpactItem] = Field(default_factory=list)
    audit_item_ids: list[str] = Field(default_factory=list)


class ScheduleVersion(BaseModel):
    """A complete roster state. Immutable once stored; repairs create children.

    Merges the old mock's ``ScheduleResult`` shape (entries/impacts/audit_items/
    unassigned/summary — kept for frontend compatibility) with versioning
    metadata.
    """

    id: str
    kind: VersionKind = VersionKind.BASELINE
    parent_version_id: str | None = None
    created_at: datetime
    week_start: date
    entries: list[ScheduleEntry] = Field(default_factory=list)
    impacts: list[ImpactItem] = Field(default_factory=list)
    audit_items: list[AuditItem] = Field(default_factory=list)
    unassigned: list[ScheduleEntry] = Field(default_factory=list)
    demand_dispositions: list[DemandDisposition] = Field(default_factory=list)
    reconciliation: DemandReconciliationReport | None = None
    trigger_events: list[ChangeEvent] = Field(default_factory=list)
    summary: dict[str, float] = Field(default_factory=dict)

    def entry_by_id(self, entry_id: str) -> ScheduleEntry | None:
        for entry in self.entries:
            if entry.id == entry_id:
                return entry
        return None

    def pending_audit_items(self) -> list[AuditItem]:
        return [a for a in self.audit_items if a.status == AuditStatus.PENDING]


class AuditDecision(BaseModel):
    status: AuditStatus
    human_note: str | None = None
    edited_entry: ScheduleEntry | None = None


class HardViolation(BaseModel):
    """Output of the shared validator — must always be empty for accepted rosters."""

    entry_id: str
    code: ReviewReasonCode
    message: str
