"""Scheduler-first input contract.

The production scheduler bridge should consume ``SchedulerSnapshot`` objects
assembled from confirmed NGO rules, operator inputs, and fixture-derived data.
Excel importers can help create fixtures and source evidence, but scheduler
runtime code should not depend on workbook files.
"""
from __future__ import annotations

from datetime import date, time
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .entities import Elder, Employee, WeekPattern, Weekday
from .enums import GenderRequirement, Period, ServiceCode
from .provenance import (
    ExcludedSourceRecord,
    GapPolicy,
    SourceEvidence,
    merge_source_evidence,
    normalize_identity_string,
    stable_id,
)
from .schedule import ChangeEvent

SessionIndex = Literal[1, 2]
UnknownPolicyAction = Literal[
    "ineligible_and_data_gap",
    "manual_review_required",
    "allowed_with_review",
]


class TaskKind(str, Enum):
    """Schedulable demand categories needed for Phase 1 task generation."""

    FIXED_SERVICE = "fixed_service"
    HC_PATTERN = "hc_pattern"
    ESCORT = "escort"
    CENTRE_DUTY = "centre_duty"
    MEAL_LOGISTICS = "meal_logistics"
    LEAVE_EVENT = "leave_event"
    CANCELLATION_EVENT = "cancellation_event"


class TaskSource(str, Enum):
    """Where a demand/config fact came from before scheduling."""

    RULEBOOK = "rulebook"
    FIXTURE = "fixture"
    OPERATOR_INPUT = "operator_input"
    WEEKLY_CHANGE = "weekly_change"
    GENERATED = "generated"


class DataGap(BaseModel):
    """A known missing fact that the scheduler must not silently guess."""

    id: str = ""
    kind: Literal[
        "gender",
        "skill",
        "route",
        "week_pattern",
        "duty_requirement",
        "availability",
        "other",
    ]
    entity_id: str | None = None
    message: str
    blocking: bool = True
    field: str | None = None
    policy: GapPolicy = "ineligible"
    reason_code: str | None = None
    source_ref_ids: list[str] = Field(default_factory=list)
    source: TaskSource = TaskSource.RULEBOOK

    @field_validator("entity_id", "field", "reason_code", mode="before")
    @classmethod
    def _normalize_optional_identity(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = normalize_identity_string(value)
        return normalized or None

    @field_validator("source_ref_ids", mode="before")
    @classmethod
    def _normalize_source_refs(cls, value: object) -> object:
        if not isinstance(value, (list, tuple)):
            return value
        normalized = [
            normalize_identity_string(item) for item in value
            if isinstance(item, str) and normalize_identity_string(item)
        ]
        return sorted(set(normalized))

    @model_validator(mode="after")
    def _derive_id(self) -> "DataGap":
        normalized_reason = self.reason_code or f"{self.kind}:{self.policy}"
        expected = stable_id("gap_", "data_gap", {
            "kind": self.kind,
            "entity_id": self.entity_id,
            "field": self.field,
            "source_ref_ids": sorted(self.source_ref_ids),
            "policy": self.policy,
            "reason_code": normalized_reason,
        })
        if self.id and self.id != expected:
            raise ValueError("data gap ID does not match its canonical identity")
        self.reason_code = normalized_reason
        self.id = expected
        return self


class SessionDefinition(BaseModel):
    id: str
    period: Period
    session_index: SessionIndex
    label: str
    start_time: time | None = None
    end_time: time | None = None
    assumption: str | None = None


class EscortOccupancyRule(BaseModel):
    occupies_full_half_day: bool = True
    max_requests_per_worker_per_half_day: int = 1
    baseline_reserved_workers_per_half_day: int = 4
    assumption: str | None = None

    @field_validator(
        "max_requests_per_worker_per_half_day",
        "baseline_reserved_workers_per_half_day",
    )
    @classmethod
    def _positive_count(cls, value: int) -> int:
        if value < 1:
            raise ValueError("count must be positive")
        return value


class CentreDutyPlaceholderRequirement(BaseModel):
    centre: str
    weekdays: list[Weekday]
    periods: list[Period]
    required_count: int = 1
    roles: list[str] = Field(default_factory=list)
    assumption: str | None = None

    @field_validator("required_count")
    @classmethod
    def _positive_required_count(cls, value: int) -> int:
        if value < 1:
            raise ValueError("required_count must be positive")
        return value


class UnknownDataPolicy(BaseModel):
    unknown_gender: UnknownPolicyAction = "ineligible_and_data_gap"
    unknown_skill: UnknownPolicyAction = "ineligible_and_data_gap"
    unknown_route: UnknownPolicyAction = "manual_review_required"
    unknown_week_pattern: UnknownPolicyAction = "manual_review_required"
    note: str = "Unknown eligibility facts must be surfaced for review."


class SchedulerConfig(BaseModel):
    """Rule/config values the scheduler needs before generating a draft."""

    version: str = "phase1-default"
    sessions: list[SessionDefinition] = Field(default_factory=list)
    service_priority_order: list[TaskKind] = Field(default_factory=list)
    service_code_priority_order: list[ServiceCode] = Field(default_factory=list)
    escort_occupancy: EscortOccupancyRule = Field(default_factory=EscortOccupancyRule)
    centre_duty_placeholders: list[CentreDutyPlaceholderRequirement] = (
        Field(default_factory=list)
    )
    unknown_data_policy: UnknownDataPolicy = Field(default_factory=UnknownDataPolicy)
    assumptions: list[str] = Field(default_factory=list)


class WorkerAvailability(BaseModel):
    """Worker capacity or absence for a date/weekday/period/session slot."""

    worker_id: str
    available_date: date | None = None
    weekday: Weekday | None = None
    period: Period | None = None
    session_index: SessionIndex | None = None
    is_available: bool = True
    reason: Literal[
        "regular_hours",
        "leave",
        "saturday_team",
        "manual_override",
        "unknown",
    ] = "regular_hours"
    source: TaskSource = TaskSource.OPERATOR_INPUT
    data_gaps: list[DataGap] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    source_evidence: list[SourceEvidence] = Field(default_factory=list)
    data_gap_ids: list[str] = Field(default_factory=list)
    data_gap_policies: dict[str, GapPolicy] = Field(default_factory=dict)
    override_ids: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    notes: str | None = None

    @field_validator("worker_id", mode="before")
    @classmethod
    def _normalize_required_worker_id(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = normalize_identity_string(value)
        if not normalized:
            raise ValueError("worker_id must not be blank")
        return normalized

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
    def _canonical_provenance(self) -> "WorkerAvailability":
        self.source_evidence = merge_source_evidence(self.source_evidence)
        self.source_refs = sorted(set(self.source_refs))
        self.override_ids = sorted(set(self.override_ids))
        self.depends_on = sorted(set(self.depends_on))
        return self


class TaskDemand(BaseModel):
    """One demand item before assignment to a worker/session slot."""

    id: str
    demand_id: str | None = None
    kind: TaskKind
    source: TaskSource = TaskSource.OPERATOR_INPUT
    service_code: ServiceCode | None = None
    task_date: date | None = None
    weekday: Weekday | None = None
    period: Period | None = None
    session_index: SessionIndex | None = 1
    occupies_full_period: bool = False
    week_pattern: WeekPattern | None = None
    elder_id: str | None = None
    worker_id: str | None = None
    pinned_worker_id: str | None = None
    exclusive_worker_id: str | None = None
    preferred_worker_id: str | None = None
    preference_strength: Literal["must", "prefer"] | None = None
    gender_requirement: GenderRequirement = GenderRequirement.ANY
    required_skills: list[ServiceCode] = Field(default_factory=list)
    required_count: int = 1
    centre: str | None = None
    district: str | None = None
    route: str | None = None
    destination: str | None = None
    start_time: time | None = None
    end_time: time | None = None
    status: Literal["active", "cancelled", "hospitalised", "leave"] = "active"
    data_gaps: list[DataGap] = Field(default_factory=list)
    data_gap_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    source_evidence: list[SourceEvidence] = Field(default_factory=list)
    primary_source_evidence_id: str | None = None
    override_ids: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    duplicate_ordinal: int = 1
    notes: str | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _normalize_required_id(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = normalize_identity_string(value)
        if not normalized:
            raise ValueError("task demand id must not be blank")
        return normalized

    @field_validator(
        "demand_id", "elder_id", "worker_id", "pinned_worker_id",
        "exclusive_worker_id", "preferred_worker_id", "centre", "district",
        "route", "destination", "primary_source_evidence_id",
        mode="before",
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

    @field_validator("required_count")
    @classmethod
    def _positive_required_count(cls, value: int) -> int:
        if value < 1:
            raise ValueError("required_count must be positive")
        return value

    @model_validator(mode="after")
    def _full_period_demand_has_no_session(self) -> "TaskDemand":
        if self.occupies_full_period and self.session_index is not None:
            raise ValueError("full-period demand must not target one session")
        self.source_evidence = merge_source_evidence(self.source_evidence)
        self.source_refs = sorted(set(self.source_refs))
        self.override_ids = sorted(set(self.override_ids))
        self.depends_on = sorted(set(self.depends_on))
        return self


class SchedulerSnapshot(BaseModel):
    """All normalized inputs needed to draft one roster week.

    ``change_events`` carries leave, service cancellation, elder cancellation,
    and new/cancelled escort events for the repair bridge. Tests and production
    code should be able to construct this object without opening Excel files.
    """

    week_start: date
    config: SchedulerConfig = Field(default_factory=SchedulerConfig)
    workers: list[Employee] = Field(default_factory=list)
    elders: list[Elder] = Field(default_factory=list)
    availability: list[WorkerAvailability] = Field(default_factory=list)
    demands: list[TaskDemand] = Field(default_factory=list)
    change_events: list[ChangeEvent] = Field(default_factory=list)
    data_gaps: list[DataGap] = Field(default_factory=list)
    source_evidence: list[SourceEvidence] = Field(default_factory=list)
    excluded_source_records: list[ExcludedSourceRecord] = Field(default_factory=list)
    source: TaskSource = TaskSource.GENERATED
    source_note: str | None = None

    @field_validator("week_start")
    @classmethod
    def _week_start_must_be_monday(cls, value: date) -> date:
        if value.weekday() != 0:
            raise ValueError("week_start must be a Monday")
        return value

    @model_validator(mode="after")
    def _canonical_source_registry(self) -> "SchedulerSnapshot":
        self.source_evidence = merge_source_evidence(self.source_evidence)
        return self
