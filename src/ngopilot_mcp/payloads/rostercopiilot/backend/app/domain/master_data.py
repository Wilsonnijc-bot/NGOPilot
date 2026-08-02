"""Persisted Phase 1A master data contract.

The API exposes entity-shaped CRUD, but the authoritative store is an
append-only ``MasterDataSet`` document version in SQLite. This follows
``docs/spec/MASTER_DATA_AND_VALIDATOR_SPEC.md`` while keeping the scheduler's
existing compatibility models unchanged.
"""
from __future__ import annotations

from datetime import date as Date, datetime, time
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .entities import WeekPattern, Weekday
from .enums import ChangeType, Gender, GenderRequirement, Period, ServiceCode
from .provenance import normalize_identity_string
from .snapshot import SchedulerConfig, WorkerAvailability


IssueLevel = Literal["error", "warning", "info"]
FactSource = Literal["matrix", "ngo_confirmed", "seed", "manual", "template_bootstrap"]


class MasterDataIssue(BaseModel):
    level: IssueLevel
    code: str
    message: str
    entity_type: str | None = None
    entity_id: str | None = None
    field: str | None = None


class WorkerSkillFact(BaseModel):
    service_code: ServiceCode
    level: Literal["qualified", "training", "unknown"] = "unknown"
    source: FactSource = "manual"
    evidence: str | None = None


class RouteFact(BaseModel):
    route_code: str
    qualified: bool = True
    source: FactSource = "manual"
    evidence: str | None = None

    @field_validator("route_code", mode="before")
    @classmethod
    def _normalize_route_code(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = normalize_identity_string(value)
        if not normalized:
            raise ValueError("route_code must not be blank")
        return normalized


class MasterWorker(BaseModel):
    id: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    gender: Gender | None = None
    home_team: str = "EH"
    skill_facts: list[WorkerSkillFact] = Field(default_factory=list)
    route_facts: list[RouteFact] = Field(default_factory=list)
    saturday_team: Literal["A", "B"] | None = None
    employment_type: Literal["full", "part"] = "full"
    active: bool = True
    effective_from: Date | None = None
    effective_to: Date | None = None
    work_start: time = time(8, 30)
    work_end: time = time(17, 30)
    notes: str | None = None

    @field_validator("aliases")
    @classmethod
    def _unique_aliases(cls, value: list[str]) -> list[str]:
        return sorted({alias.strip() for alias in value if alias.strip()})


class MasterElder(BaseModel):
    id: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    gender: Gender | None = None
    gender_requirement: GenderRequirement = GenderRequirement.ANY
    district: str | None = None
    owning_unit: str = "EH"
    exclusive_worker_id: str | None = None
    status: Literal["active", "hospitalised", "paused", "exited"] = "active"
    notes: str | None = None

    @field_validator("aliases")
    @classmethod
    def _unique_aliases(cls, value: list[str]) -> list[str]:
        return sorted({alias.strip() for alias in value if alias.strip()})


class MasterFixedService(BaseModel):
    id: str
    elder_id: str | None = None
    service_code: ServiceCode
    weekday: Weekday
    period: Period
    session_index: Literal[1, 2] = 1
    start_time: time | None = None
    end_time: time | None = None
    week_pattern: WeekPattern = Field(default_factory=WeekPattern)
    assigned_worker_id: str | None = None
    is_exclusive: bool = False
    alternate_group: str | None = None
    district: str | None = None
    route: str | None = None
    center: str | None = None
    active: bool = True
    effective_from: Date | None = None
    effective_to: Date | None = None
    source_ref: str = "api"
    source_confidence: Literal["high", "medium", "low"] = "high"
    notes: str | None = None


class LeaveEvent(BaseModel):
    worker_id: str
    date: Date
    scope: Literal["full_day", "AM", "PM"] = "full_day"
    reason: str | None = None


class TemporaryChange(BaseModel):
    type: ChangeType
    change_date: Date
    period: Period | None = None
    worker_id: str | None = None
    worker_alias: str | None = None
    elder_id: str | None = None
    elder_alias: str | None = None
    escort_request_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None


class RuleConfigValue(BaseModel):
    value: Any
    confirmed: bool = False
    assumption: str | None = None


class MasterRuleConfig(BaseModel):
    """Versioned rule configuration with assumption metadata.

    ``scheduler_config`` keeps compatibility with the existing engine contract;
    ``values`` is the Phase 1A admin-facing map where each setting carries
    confirmation state.
    """

    version: str = "phase1a-default"
    scheduler_config: SchedulerConfig = Field(default_factory=SchedulerConfig)
    values: dict[str, RuleConfigValue] = Field(default_factory=dict)


class ManualOverridePin(BaseModel):
    worker_id: str | None = None
    elder_id: str | None = None
    date: Date | None = None
    weekday: Weekday | None = None
    period: Period | None = None
    service_code: ServiceCode | None = None

    def is_empty(self) -> bool:
        return all(value is None for value in self.model_dump().values())


class ManualOverride(BaseModel):
    id: str
    scope: Literal["entry", "week", "recurring"]
    pin: ManualOverridePin
    action: Literal["pin_assignment", "forbid_assignment", "cancel"]
    reason: str
    effective_from: Date | None = None
    effective_to: Date | None = None
    origin_audit_item_id: str | None = None
    # Phase 1B review provenance.  These remain optional because master-data
    # policy overrides created before Phase 1B are not tied to a weekly run.
    decision_id: str | None = None
    run_id: str | None = None
    source_version_id: str | None = None
    resulting_version_id: str | None = None
    actor: str | None = None
    created_at: datetime | None = None


class MasterDataSet(BaseModel):
    schema_version: str = "phase1a"
    origin: str = "api"
    workers: list[MasterWorker] = Field(default_factory=list)
    elders: list[MasterElder] = Field(default_factory=list)
    fixed_services: list[MasterFixedService] = Field(default_factory=list)
    availability: list[WorkerAvailability] = Field(default_factory=list)
    leave_events: list[LeaveEvent] = Field(default_factory=list)
    temporary_changes: list[TemporaryChange] = Field(default_factory=list)
    rule_config: MasterRuleConfig = Field(default_factory=MasterRuleConfig)
    manual_overrides: list[ManualOverride] = Field(default_factory=list)

    @model_validator(mode="after")
    def _stable_entity_ids(self) -> "MasterDataSet":
        self.workers.sort(key=lambda row: row.id)
        self.elders.sort(key=lambda row: row.id)
        self.fixed_services.sort(key=lambda row: row.id)
        self.leave_events.sort(key=lambda row: (row.date, row.worker_id, row.scope))
        self.temporary_changes.sort(key=lambda row: (
            row.change_date,
            row.type.value,
            row.worker_id or "",
            row.elder_id or "",
        ))
        self.manual_overrides.sort(key=lambda row: row.id)
        return self


class MasterDataVersionEnvelope(BaseModel):
    version: int
    id: str
    created_at: str
    origin: str
    payload: MasterDataSet


HOME_VISIT_CODES = {
    ServiceCode.EXERCISE,
    ServiceCode.HOME_CLEAN,
    ServiceCode.PERSONAL_CARE,
    ServiceCode.BATH,
}


def validate_master_data(payload: MasterDataSet) -> list[MasterDataIssue]:
    """Return Phase 1A save-time validation issues.

    ``error`` issues reject document replacement. Warnings and info issues are
    persisted with the version and exposed through ``/api/master-data/issues``.
    """

    issues: list[MasterDataIssue] = []
    workers = {worker.id: worker for worker in payload.workers}
    elders = {elder.id: elder for elder in payload.elders}

    _flag_duplicate_ids("worker", [worker.id for worker in payload.workers], issues)
    _flag_duplicate_ids("elder", [elder.id for elder in payload.elders], issues)
    _flag_duplicate_ids(
        "fixed_service",
        [service.id for service in payload.fixed_services],
        issues,
    )
    _flag_duplicate_ids(
        "manual_override",
        [override.id for override in payload.manual_overrides],
        issues,
    )

    alias_owner: dict[str, str] = {}
    for worker in payload.workers:
        if worker.work_start >= worker.work_end:
            issues.append(MasterDataIssue(
                level="error",
                code="invalid_work_hours",
                message="worker work_start must be before work_end",
                entity_type="worker",
                entity_id=worker.id,
                field="work_start",
            ))
        if worker.active and worker.gender is None:
            issues.append(MasterDataIssue(
                level="warning",
                code="data_gap_gender",
                message="worker gender is unknown; gender-constrained pairings are unavailable",
                entity_type="worker",
                entity_id=worker.id,
                field="gender",
            ))
        confirmed_facts = [
            fact for fact in worker.skill_facts
            if fact.source != "seed" and fact.level == "qualified"
        ]
        if worker.active and not confirmed_facts:
            issues.append(MasterDataIssue(
                level="warning",
                code="data_gap_skill",
                message="worker has no confirmed qualified skill facts",
                entity_type="worker",
                entity_id=worker.id,
                field="skill_facts",
            ))
        if worker.active and worker.employment_type == "full" and worker.saturday_team is None:
            issues.append(MasterDataIssue(
                level="warning",
                code="data_gap_saturday_team",
                message="active full-time worker has no Saturday team",
                entity_type="worker",
                entity_id=worker.id,
                field="saturday_team",
            ))
        if not worker.active:
            continue
        for alias in worker.aliases:
            prior = alias_owner.get(alias)
            if prior and prior != worker.id:
                issues.append(MasterDataIssue(
                    level="error",
                    code="duplicate_worker_alias",
                    message=f"active workers share alias {alias!r}",
                    entity_type="worker",
                    entity_id=worker.id,
                    field="aliases",
                ))
            else:
                alias_owner[alias] = worker.id

    for elder in payload.elders:
        if elder.exclusive_worker_id:
            worker = workers.get(elder.exclusive_worker_id)
            if worker is None:
                issues.append(MasterDataIssue(
                    level="error",
                    code="broken_fk",
                    message="elder exclusive_worker_id references a missing worker",
                    entity_type="elder",
                    entity_id=elder.id,
                    field="exclusive_worker_id",
                ))
            elif not worker.active:
                issues.append(MasterDataIssue(
                    level="error",
                    code="inactive_exclusive_worker",
                    message="elder exclusive_worker_id references an inactive worker",
                    entity_type="elder",
                    entity_id=elder.id,
                    field="exclusive_worker_id",
                ))
        if elder.status == "active" and elder.district is None:
            issues.append(MasterDataIssue(
                level="info",
                code="data_gap_district",
                message="elder district is unknown; district ranking is disabled",
                entity_type="elder",
                entity_id=elder.id,
                field="district",
            ))

    for service in payload.fixed_services:
        if service.assigned_worker_id and service.assigned_worker_id not in workers:
            issues.append(MasterDataIssue(
                level="error",
                code="broken_fk",
                message="fixed service assigned_worker_id references a missing worker",
                entity_type="fixed_service",
                entity_id=service.id,
                field="assigned_worker_id",
            ))
        if service.assigned_worker_id:
            worker = workers.get(service.assigned_worker_id)
            if service.is_exclusive and worker is not None and not worker.active:
                issues.append(MasterDataIssue(
                    level="error",
                    code="inactive_exclusive_worker",
                    message="exclusive fixed service is assigned to an inactive worker",
                    entity_type="fixed_service",
                    entity_id=service.id,
                    field="assigned_worker_id",
                ))
        if service.elder_id and service.elder_id not in elders:
            issues.append(MasterDataIssue(
                level="error",
                code="broken_fk",
                message="fixed service elder_id references a missing elder",
                entity_type="fixed_service",
                entity_id=service.id,
                field="elder_id",
            ))
        if service.active and service.service_code in HOME_VISIT_CODES and service.elder_id is None:
            issues.append(MasterDataIssue(
                level="error",
                code="missing_home_visit_elder",
                message="active home-visit fixed service requires elder_id",
                entity_type="fixed_service",
                entity_id=service.id,
                field="elder_id",
            ))
        if not service.active and service.service_code in HOME_VISIT_CODES and service.elder_id is None:
            issues.append(MasterDataIssue(
                level="warning",
                code="parked_incomplete_service",
                message="inactive home-visit service is parked until elder_id is confirmed",
                entity_type="fixed_service",
                entity_id=service.id,
                field="elder_id",
            ))
        if service.active and service.week_pattern.raw not in {"weekly", "逢週", "每週", "單月", "雙月", "odd_month", "even_month"}:
            try:
                WeekPattern.parse(service.week_pattern.raw)
            except ValueError:
                issues.append(MasterDataIssue(
                    level="error",
                    code="unparseable_week_pattern",
                    message=f"active fixed service has unparseable week pattern {service.week_pattern.raw!r}",
                    entity_type="fixed_service",
                    entity_id=service.id,
                    field="week_pattern",
                ))
        elder = elders.get(service.elder_id or "")
        if (
            service.active
            and elder is not None
            and elder.gender is None
            and service.service_code in {ServiceCode.BATH, ServiceCode.PERSONAL_CARE}
        ):
            issues.append(MasterDataIssue(
                level="warning",
                code="data_gap_gender",
                message=(
                    f"elder gender is unknown for gender-sensitive service {service.id}"
                ),
                entity_type="elder",
                entity_id=elder.id,
                field="gender",
            ))

    for leave in payload.leave_events:
        if leave.worker_id not in workers:
            issues.append(MasterDataIssue(
                level="error",
                code="broken_fk",
                message="leave event worker_id references a missing worker",
                entity_type="leave_event",
                entity_id=leave.worker_id,
                field="worker_id",
            ))

    for override in payload.manual_overrides:
        if override.pin.is_empty():
            issues.append(MasterDataIssue(
                level="error",
                code="empty_override_pin",
                message="manual override pin must contain at least one key",
                entity_type="manual_override",
                entity_id=override.id,
                field="pin",
            ))
        if override.pin.worker_id and override.pin.worker_id not in workers:
            issues.append(MasterDataIssue(
                level="error",
                code="broken_fk",
                message="manual override pin.worker_id references a missing worker",
                entity_type="manual_override",
                entity_id=override.id,
                field="pin.worker_id",
            ))
        if override.pin.elder_id and override.pin.elder_id not in elders:
            issues.append(MasterDataIssue(
                level="error",
                code="broken_fk",
                message="manual override pin.elder_id references a missing elder",
                entity_type="manual_override",
                entity_id=override.id,
                field="pin.elder_id",
            ))

    for name, value in payload.rule_config.values.items():
        if not value.confirmed:
            issues.append(MasterDataIssue(
                level="info",
                code="unconfirmed_rule_config",
                message=f"rule config {name!r} is unconfirmed: {value.assumption or 'no assumption noted'}",
                entity_type="rule_config",
                entity_id=name,
            ))

    return issues


def has_error_issues(issues: list[MasterDataIssue]) -> bool:
    return any(issue.level == "error" for issue in issues)


def _flag_duplicate_ids(
    entity_type: str,
    ids: list[str],
    issues: list[MasterDataIssue],
) -> None:
    seen: set[str] = set()
    for entity_id in ids:
        if entity_id in seen:
            issues.append(MasterDataIssue(
                level="error",
                code="duplicate_id",
                message=f"duplicate {entity_type} id {entity_id!r}",
                entity_type=entity_type,
                entity_id=entity_id,
                field="id",
            ))
        seen.add(entity_id)
