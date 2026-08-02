"""Master data bootstrap and SchedulerSnapshot lowering.

This module is the Phase 1A bridge between persisted NGO-maintained master data
and the scheduler-first runtime contract. It deliberately lowers master data
into ``SchedulerSnapshot`` objects before the greedy engine runs; it does not
open weekly upload workbooks and it does not implement a solver.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from pathlib import Path

from ..domain import (
    ChangeEvent,
    ChangeType,
    DataGap,
    Elder,
    Employee,
    ExcludedSourceRecord,
    GenderRequirement,
    LeaveEvent,
    ManualOverride,
    MasterDataSet,
    MasterElder,
    MasterFixedService,
    MasterRuleConfig,
    MasterWorker,
    Period,
    RuleConfigValue,
    SchedulerSnapshot,
    ServiceCode,
    SourceEvidence,
    TaskDemand,
    TaskKind,
    TaskSource,
    WeekPattern,
    WorkerAvailability,
    WorkerSkillFact,
    content_fingerprint,
    merge_source_evidence,
)
from ..importer import DivisionImportResult, parse_division_workbook
from ..importer.division_models import FixedServiceCandidate, ParsedAssignment, WorkerColumn

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DIVISION_TEMPLATE = REPO_ROOT / "docs" / "照顧員工作分工表2026(HKU).xlsx"

SEED_BOOTSTRAP_SKILLS = [
    ServiceCode.EXERCISE,
    ServiceCode.HOME_CLEAN,
    ServiceCode.PERSONAL_CARE,
    ServiceCode.BATH,
    ServiceCode.ESCORT,
    ServiceCode.DUTY_AMC,
    ServiceCode.DUTY_MRC,
    ServiceCode.DUTY_GC,
    ServiceCode.KITCHEN,
]

DUTY_CODES = {ServiceCode.DUTY_AMC, ServiceCode.DUTY_MRC, ServiceCode.DUTY_GC}
HOME_VISIT_CODES = {
    ServiceCode.EXERCISE,
    ServiceCode.HOME_CLEAN,
    ServiceCode.PERSONAL_CARE,
    ServiceCode.BATH,
}


@dataclass
class MasterDataLowering:
    workers: list[Employee]
    worker_aliases: dict[str, str]
    elders_by_id: dict[str, Elder]
    elder_aliases: dict[str, str]
    demands: list[TaskDemand]
    availability: list[WorkerAvailability]
    change_events: list[ChangeEvent]
    data_gaps: list[DataGap]
    source_evidence: list[SourceEvidence]
    excluded_source_records: list[ExcludedSourceRecord]
    source_counts: Counter[str] = field(default_factory=Counter)


def bootstrap_master_data_from_template(
    template_path: Path = DEFAULT_DIVISION_TEMPLATE,
) -> MasterDataSet:
    return bootstrap_master_data_from_division(parse_division_workbook(template_path))


def bootstrap_master_data_from_division(division: DivisionImportResult) -> MasterDataSet:
    """Build the initial persisted document from the real division template.

    The bootstrap keeps worker genders unknown and uses seed skill facts only to
    preserve the existing demo's ability to draft a roster. Those seed facts are
    surfaced as data gaps later; they are not NGO-confirmed capability facts.
    """

    worker_aliases: dict[str, str] = {}
    workers = [
        _master_worker_from_column(i, worker, worker_aliases)
        for i, worker in enumerate(division.workers, start=1)
    ]
    active_worker_ids = {worker.id for worker in workers if worker.active}

    elder_aliases: dict[str, str] = {}
    elders: list[MasterElder] = []
    fixed_services: list[MasterFixedService] = []

    for candidate in division.fixed_service_candidates:
        service = _service_code(candidate.service_code or candidate.service_code_raw)
        if service is None or service in (ServiceCode.ESCORT, ServiceCode.OFF):
            continue
        elder_id = _ensure_master_elder(
            elders,
            elder_aliases,
            candidate.elder_alias,
            district=candidate.district,
            unit=candidate.unit,
        )
        worker_id = _resolve_alias(worker_aliases, candidate.worker_alias)
        fixed_services.append(_master_fixed_from_candidate(
            candidate,
            service=service,
            elder_id=elder_id,
            worker_id=worker_id,
            assigned_worker_active=(worker_id in active_worker_ids if worker_id else True),
            ordinal=len(fixed_services) + 1,
        ))

    for assignment in division.assignments:
        service = _service_code(assignment.service_code or assignment.service_code_raw)
        if service == ServiceCode.MEAL:
            fixed_services.append(_master_meal_from_assignment(
                assignment,
                worker_id=_resolve_alias(worker_aliases, assignment.worker_alias),
                ordinal=len(fixed_services) + 1,
            ))
        elif service in DUTY_CODES:
            fixed_services.append(_master_duty_from_assignment(
                assignment,
                service=service,
                worker_id=_resolve_alias(worker_aliases, assignment.worker_alias),
                ordinal=len(fixed_services) + 1,
            ))

    return MasterDataSet(
        origin="template_bootstrap",
        workers=workers,
        elders=elders,
        fixed_services=fixed_services,
        rule_config=MasterRuleConfig(values={
            "saturday_anchor": RuleConfigValue(
                value="odd_iso_week_team_A",
                confirmed=False,
                assumption="Bootstrap preserves the existing ISO-week A/B assumption.",
            ),
            "week_of_month_definition": RuleConfigValue(
                value="kth_weekday_occurrence",
                confirmed=False,
                assumption="Bootstrap uses WeekPattern.matches until NGO confirmation.",
            ),
            "duty_requirements": RuleConfigValue(
                value="counted_from_division_template",
                confirmed=False,
                assumption="Centre duty headcount is counted from template duty cells.",
            ),
        }),
    )


def lower_master_data(master_data: MasterDataSet, week_start: date) -> MasterDataLowering:
    data_gaps: list[DataGap] = []
    source_counts: Counter[str] = Counter()
    workers, worker_aliases = _workers_from_master_data(master_data, data_gaps)
    elders_by_id, elder_aliases = _elders_from_master_data(master_data, data_gaps)
    demands = _demands_from_master_data(
        master_data,
        week_start,
        elders_by_id,
        data_gaps,
        source_counts,
    )
    availability, change_events = _availability_from_master_data(
        master_data,
        week_start,
        data_gaps,
    )
    _config_gaps(master_data, data_gaps)
    evidence_registry = merge_source_evidence((
            *[item for worker in workers for item in worker.source_evidence],
            *[item for demand in demands for item in demand.source_evidence],
            *[_master_service_evidence(master_data, service)
              for service in master_data.fixed_services],
            *[_manual_override_evidence(master_data, override)
              for override in master_data.manual_overrides],
            *[item for event in change_events for item in event.source_evidence],
            *[item for row in availability for item in row.source_evidence],
    ))
    excluded_source_records = [
        ExcludedSourceRecord(
            source_record_id=service.id,
            reason_code="inactive_source",
            source_evidence=[_master_service_evidence(master_data, service)],
            detail="inactive or incomplete master-data source",
        )
        for service in master_data.fixed_services
        if not service.active
    ]
    return MasterDataLowering(
        workers=workers,
        worker_aliases=worker_aliases,
        elders_by_id=elders_by_id,
        elder_aliases=elder_aliases,
        demands=demands,
        availability=availability,
        change_events=change_events,
        data_gaps=_dedupe_gaps(data_gaps),
        source_evidence=evidence_registry,
        excluded_source_records=excluded_source_records,
        source_counts=source_counts,
    )


def build_scheduler_snapshot_from_master_data(
    master_data: MasterDataSet,
    *,
    week_start: date,
    extra_demands: list[TaskDemand] | None = None,
    extra_change_events: list[ChangeEvent] | None = None,
    extra_availability: list[WorkerAvailability] | None = None,
    extra_data_gaps: list[DataGap] | None = None,
    source_note: str = "master data snapshot",
) -> SchedulerSnapshot:
    lowered = lower_master_data(master_data, week_start)
    return SchedulerSnapshot(
        week_start=week_start,
        config=master_data.rule_config.scheduler_config,
        workers=lowered.workers,
        elders=sorted(lowered.elders_by_id.values(), key=lambda elder: elder.id),
        availability=[*lowered.availability, *(extra_availability or [])],
        demands=[*lowered.demands, *(extra_demands or [])],
        change_events=[*lowered.change_events, *(extra_change_events or [])],
        data_gaps=[*lowered.data_gaps, *(extra_data_gaps or [])],
        source_evidence=list(lowered.source_evidence),
        excluded_source_records=list(lowered.excluded_source_records),
        source=TaskSource.OPERATOR_INPUT,
        source_note=source_note,
    )


def _master_worker_from_column(
    ordinal: int,
    worker: WorkerColumn,
    aliases: dict[str, str],
) -> MasterWorker:
    worker_id = f"W{ordinal:03d}"
    active = worker.status_inferred != "departed_inferred"
    for alias in _alias_variants(worker.display_name, worker.raw_header, worker_id):
        aliases[alias] = worker_id
    return MasterWorker(
        id=worker_id,
        display_name=worker.display_name,
        aliases=sorted({
            text for text in (worker.display_name, worker.raw_header)
            if _clean(text) and _clean(text) != worker.display_name
        }),
        gender=None,
        home_team=(worker.tags[0] if worker.tags else "EH"),
        skill_facts=[
            WorkerSkillFact(service_code=skill, level="qualified", source="seed")
            for skill in SEED_BOOTSTRAP_SKILLS
        ],
        saturday_team=worker.saturday_team,
        active=active,
        work_start=_parse_time(worker.work_start) or time(8, 30),
        work_end=_parse_time(worker.work_end) or time(17, 30),
        notes="Template bootstrap; skills are seed facts pending NGO confirmation.",
    )


def _master_fixed_from_candidate(
    candidate: FixedServiceCandidate,
    *,
    service: ServiceCode,
    elder_id: str | None,
    worker_id: str | None,
    assigned_worker_active: bool,
    ordinal: int,
) -> MasterFixedService:
    pattern, pattern_low_confidence = _master_week_pattern(
        candidate.week_pattern_raw,
        candidate.week_pattern_weeks,
    )
    inactive_exclusive_worker = (
        service == ServiceCode.EXERCISE
        and worker_id is not None
        and not assigned_worker_active
    )
    active = not (
        (service in HOME_VISIT_CODES and elder_id is None)
        or pattern_low_confidence
        or inactive_exclusive_worker
    )
    low_confidence = (
        candidate.confidence != "high"
        or bool(candidate.warnings)
        or not active
        or pattern_low_confidence
    )
    assigned_worker_id = None if inactive_exclusive_worker else worker_id
    note_parts = [part for part in [
        candidate.inline_note,
        "parked: exclusive worker column is inactive" if inactive_exclusive_worker else None,
    ] if part]
    return MasterFixedService(
        id=f"FS{ordinal:04d}",
        elder_id=elder_id,
        service_code=service,
        weekday=candidate.weekday,  # type: ignore[arg-type]
        period=Period(candidate.period),
        session_index=candidate.session_index if candidate.session_index in (1, 2) else 1,
        start_time=_parse_time(candidate.start_time),
        end_time=_parse_time(candidate.end_time),
        week_pattern=pattern,
        assigned_worker_id=assigned_worker_id,
        is_exclusive=(service == ServiceCode.EXERCISE),
        district=candidate.district,
        active=active,
        source_ref=candidate.source_ref,
        source_confidence="low" if low_confidence else "high",
        notes=" | ".join(note_parts) or None,
    )


def _master_meal_from_assignment(
    assignment: ParsedAssignment,
    *,
    worker_id: str | None,
    ordinal: int,
) -> MasterFixedService:
    return MasterFixedService(
        id=f"FS{ordinal:04d}",
        service_code=ServiceCode.MEAL,
        weekday=assignment.weekday,  # type: ignore[arg-type]
        period=Period(assignment.period),
        session_index=assignment.session_index if assignment.session_index in (1, 2) else 1,
        assigned_worker_id=worker_id,
        route=assignment.route_or_place,
        active=True,
        source_ref=_assignment_ref(assignment),
        source_confidence="high" if assignment.confidence == "high" else "medium",
        notes=assignment.inline_note or assignment.raw_text,
    )


def _master_duty_from_assignment(
    assignment: ParsedAssignment,
    *,
    service: ServiceCode,
    worker_id: str | None,
    ordinal: int,
) -> MasterFixedService:
    return MasterFixedService(
        id=f"FS{ordinal:04d}",
        service_code=service,
        weekday=assignment.weekday,  # type: ignore[arg-type]
        period=Period(assignment.period),
        session_index=assignment.session_index if assignment.session_index in (1, 2) else 1,
        assigned_worker_id=worker_id,
        center=assignment.duty_center or service.value,
        active=True,
        source_ref=_assignment_ref(assignment),
        source_confidence="high" if assignment.confidence == "high" else "medium",
        notes=assignment.inline_note or assignment.raw_text,
    )


def _workers_from_master_data(
    master_data: MasterDataSet,
    data_gaps: list[DataGap],
) -> tuple[list[Employee], dict[str, str]]:
    workers: list[Employee] = []
    aliases: dict[str, str] = {}
    for worker in master_data.workers:
        if not worker.active:
            continue
        skill_facts_by_code: dict[ServiceCode, list[WorkerSkillFact]] = {}
        for fact in worker.skill_facts:
            skill_facts_by_code.setdefault(fact.service_code, []).append(fact)
        conflicting_skill_codes = {
            code for code, facts in skill_facts_by_code.items()
            if any(fact.level == "qualified" for fact in facts)
            and any(fact.level != "qualified" for fact in facts)
        }
        qualified_facts = sorted(
            (
                fact for fact in worker.skill_facts
                if fact.level == "qualified"
                and fact.service_code not in conflicting_skill_codes
            ),
            key=lambda fact: (
                fact.service_code.value,
                fact.source,
                fact.evidence or "",
            ),
        )
        skills = sorted(
            {fact.service_code for fact in qualified_facts},
            key=lambda code: code.value,
        )
        confirmed_skills = {
            fact.service_code for fact in qualified_facts if fact.source != "seed"
        }
        seed_skills = sorted(
            {
                fact.service_code
                for fact in qualified_facts
                if fact.source == "seed" and fact.service_code not in confirmed_skills
            },
            key=lambda code: code.value,
        )
        route_facts_by_code = {}
        for fact in worker.route_facts:
            route_facts_by_code.setdefault(fact.route_code, []).append(fact)
        conflicting_routes = {
            route for route, facts in route_facts_by_code.items()
            if any(fact.qualified for fact in facts)
            and any(not fact.qualified for fact in facts)
        }
        explicitly_unqualified_routes = {
            route for route, facts in route_facts_by_code.items()
            if not any(fact.qualified for fact in facts)
        }
        routes = sorted({
            fact.route_code
            for fact in worker.route_facts
            if fact.qualified and fact.route_code not in conflicting_routes
        })
        seed_routes = sorted({
            fact.route_code
            for fact in worker.route_facts
            if fact.qualified and fact.source == "seed"
            and fact.route_code not in conflicting_routes
        })
        evidence_by_id = {
            evidence.id: evidence
            for evidence in (
                _worker_skill_evidence(master_data, worker.id, fact)
                for fact in worker.skill_facts
            )
        }
        evidence_by_id.update({
            evidence.id: evidence
            for evidence in (
                _worker_route_evidence(master_data, worker.id, fact)
                for fact in worker.route_facts
            )
        })
        worker_gap_ids: list[str] = []
        seed_skill_gap_ids: dict[ServiceCode, str] = {}

        for code in sorted(conflicting_skill_codes, key=lambda item: item.value):
            refs = sorted(
                evidence.id for evidence in evidence_by_id.values()
                if evidence.field == f"skill_facts:{code.value}"
            )
            gap = DataGap(
                kind="skill",
                entity_id=worker.id,
                field=f"skill_facts:{code.value}",
                reason_code="conflicting_skill_facts",
                message=(f"同工 {worker.display_name} 的 {code.value} 技能資料互相矛盾，"
                         "未解決前不可用作資格。"),
                blocking=False,
                policy="ineligible",
                source_ref_ids=refs,
                source=TaskSource.OPERATOR_INPUT,
            )
            data_gaps.append(gap)
            worker_gap_ids.append(gap.id)

        for route in sorted(conflicting_routes | explicitly_unqualified_routes):
            refs = sorted(
                evidence.id for evidence in evidence_by_id.values()
                if evidence.field == f"route_facts:{route}"
            )
            conflict = route in conflicting_routes
            gap = DataGap(
                kind="route",
                entity_id=worker.id,
                field=f"route_facts:{route}",
                reason_code=(
                    "conflicting_route_facts" if conflict
                    else "route_explicitly_unqualified"
                ),
                message=(
                    f"同工 {worker.display_name} 的路線 {route} 資格資料互相矛盾，"
                    "未解決前不可派送。"
                    if conflict else
                    f"同工 {worker.display_name} 已明確標記為不具路線 {route} 資格。"
                ),
                blocking=False,
                policy="ineligible",
                source_ref_ids=refs,
                source=TaskSource.OPERATOR_INPUT,
            )
            data_gaps.append(gap)
            worker_gap_ids.append(gap.id)

        if worker.gender is None:
            evidence = _master_field_evidence(
                master_data,
                entity_type="worker",
                entity_id=worker.id,
                field="gender",
                confidence="low",
            )
            evidence_by_id[evidence.id] = evidence
            gap = DataGap(
                kind="gender",
                entity_id=worker.id,
                field="gender",
                message=f"同工 {worker.display_name} 性別資料未提供；性別限制服務不會自動派給此人。",
                blocking=False,
                policy="ineligible",
                source_ref_ids=[evidence.id],
                source=TaskSource.OPERATOR_INPUT,
            )
            data_gaps.append(gap)
            worker_gap_ids.append(gap.id)

        for skill in seed_skills:
            skill_evidence = sorted(
                (
                    evidence
                    for evidence in evidence_by_id.values()
                    if evidence.field == f"skill_facts:{skill.value}"
                    and evidence.confidence == "seed"
                ),
                key=lambda evidence: evidence.id,
            )
            gap = DataGap(
                kind="skill",
                entity_id=worker.id,
                field=f"skill_facts:{skill.value}",
                message=(
                    f"同工 {worker.display_name} 的 {skill.value} 技能仍是 seed 資料，"
                    "需 NGO 確認。"
                ),
                blocking=False,
                policy="allowed_with_review",
                source_ref_ids=[item.id for item in skill_evidence],
                source=TaskSource.OPERATOR_INPUT,
            )
            data_gaps.append(gap)
            worker_gap_ids.append(gap.id)
            seed_skill_gap_ids[skill] = gap.id

        if not skills:
            evidence = _master_field_evidence(
                master_data,
                entity_type="worker",
                entity_id=worker.id,
                field="skill_facts",
                confidence="low",
            )
            evidence_by_id[evidence.id] = evidence
            gap = DataGap(
                kind="skill",
                entity_id=worker.id,
                field="skill_facts",
                message=f"同工 {worker.display_name} 沒有已確認技能資料。",
                blocking=False,
                policy="ineligible",
                source_ref_ids=[evidence.id],
                source=TaskSource.OPERATOR_INPUT,
            )
            data_gaps.append(gap)
            worker_gap_ids.append(gap.id)

        if worker.employment_type == "full" and worker.saturday_team is None:
            evidence = _master_field_evidence(
                master_data,
                entity_type="worker",
                entity_id=worker.id,
                field="saturday_team",
                confidence="low",
            )
            evidence_by_id[evidence.id] = evidence
            gap = DataGap(
                kind="availability",
                entity_id=worker.id,
                field="saturday_team",
                message=f"同工 {worker.display_name} 未提供 Saturday A/B team；星期六不會自動排班。",
                blocking=False,
                policy="ineligible",
                source_ref_ids=[evidence.id],
                source=TaskSource.OPERATOR_INPUT,
            )
            data_gaps.append(gap)
            worker_gap_ids.append(gap.id)

        workers.append(Employee(
            id=worker.id,
            display_name=worker.display_name,
            gender=worker.gender,
            home_team=worker.home_team,
            skills=skills,
            routes=routes,
            seed_skills=seed_skills,
            seed_routes=seed_routes,
            seed_skill_gap_ids=seed_skill_gap_ids,
            source_evidence=merge_source_evidence(evidence_by_id.values()),
            data_gap_ids=sorted(set(worker_gap_ids)),
            data_gap_policies={
                gap.id: gap.policy
                for gap in data_gaps
                if gap.id in worker_gap_ids
            },
            data_gap_fields={
                gap.id: gap.field or gap.kind
                for gap in data_gaps
                if gap.id in worker_gap_ids
            },
            saturday_team=worker.saturday_team,
            employment_type=worker.employment_type,
            work_start=worker.work_start,
            work_end=worker.work_end,
            notes=worker.notes,
        ))
        for alias in _alias_variants(worker.id, worker.display_name, *worker.aliases):
            aliases[alias] = worker.id
    return workers, aliases


def _elders_from_master_data(
    master_data: MasterDataSet,
    data_gaps: list[DataGap],
) -> tuple[dict[str, Elder], dict[str, str]]:
    elders_by_id: dict[str, Elder] = {}
    aliases: dict[str, str] = {}
    for elder in master_data.elders:
        status = "hospitalised" if elder.status == "paused" else elder.status
        elders_by_id[elder.id] = Elder(
            id=elder.id,
            display_name=elder.display_name,
            gender=elder.gender,
            district=elder.district or "未提供",
            owning_unit=elder.owning_unit,
            gender_requirement=elder.gender_requirement,
            exclusive_worker_id=elder.exclusive_worker_id,
            status=status,  # type: ignore[arg-type]
            notes=elder.notes,
        )
        for alias in _alias_variants(elder.id, elder.display_name, *elder.aliases):
            aliases[alias] = elder.id
        if elder.district is None:
            data_gaps.append(DataGap(
                kind="other",
                entity_id=elder.id,
                message=f"長者 {elder.display_name} 地區資料未提供；路線排序不會使用此長者。",
                blocking=False,
                source=TaskSource.OPERATOR_INPUT,
            ))
    return elders_by_id, aliases


def _demands_from_master_data(
    master_data: MasterDataSet,
    week_start: date,
    elders_by_id: dict[str, Elder],
    data_gaps: list[DataGap],
    counts: Counter[str],
) -> list[TaskDemand]:
    demands: list[TaskDemand] = []
    for service in master_data.fixed_services:
        service_evidence = _master_service_evidence(master_data, service)
        if not service.active:
            data_gaps.append(DataGap(
                kind="other",
                entity_id=service.id,
                field="active",
                message=f"固定服務 {service.id} 已停用或資料未齊，未產生本週需求。",
                blocking=False,
                policy="informational",
                source_ref_ids=[service_evidence.id],
                source=TaskSource.OPERATOR_INPUT,
            ))
            continue

        demand_gaps: list[DataGap] = []
        if service.source_confidence == "low":
            gap = DataGap(
                kind="other",
                entity_id=service.id,
                field="source_confidence",
                message=f"固定服務 {service.id} 來源信心低，需人工覆核。",
                blocking=False,
                policy="allowed_with_review",
                source_ref_ids=[service_evidence.id],
                source=TaskSource.OPERATOR_INPUT,
            )
            data_gaps.append(gap)
            demand_gaps.append(gap)

        elder = elders_by_id.get(service.elder_id or "")
        if (
            service.service_code in (ServiceCode.BATH, ServiceCode.PERSONAL_CARE)
            and elder is not None
            and elder.gender is None
            and elder.gender_requirement == GenderRequirement.ANY
        ):
            gap = DataGap(
                kind="gender",
                entity_id=elder.id,
                field="gender_requirement",
                message=f"長者 {elder.display_name} 的 {service.service_code.value} 需要性別核實。",
                blocking=False,
                policy="allowed_with_review",
                source_ref_ids=[service_evidence.id],
                source=TaskSource.OPERATOR_INPUT,
            )
            data_gaps.append(gap)
            demand_gaps.append(gap)

        cancelling_override = _matching_override(
            master_data.manual_overrides,
            service,
            week_start,
            action="cancel",
        )
        pinning_override = None if cancelling_override else _matching_override(
            master_data.manual_overrides,
            service,
            week_start,
            action="pin_assignment",
        )
        pinned_worker_id = (
            pinning_override.pin.worker_id
            if pinning_override and pinning_override.pin.worker_id
            else service.assigned_worker_id
        )
        provenance = [service_evidence]
        source_refs = [service.source_ref] if service.source_ref else []
        applied_overrides = [
            override for override in (cancelling_override, pinning_override)
            if override is not None
        ]
        for override in applied_overrides:
            provenance.append(_manual_override_evidence(master_data, override))
            source_refs.append(f"manual_override:{override.id}")

        is_duty = service.service_code in DUTY_CODES
        centre = service.center or service.service_code.value if is_duty else service.center
        demand = TaskDemand(
            id=service.id,
            kind=TaskKind.CENTRE_DUTY if is_duty else _kind_for_service(service.service_code),
            source=TaskSource.OPERATOR_INPUT,
            service_code=service.service_code,
            weekday=service.weekday,
            period=service.period,
            session_index=service.session_index,
            week_pattern=service.week_pattern,
            elder_id=service.elder_id,
            pinned_worker_id=None if service.is_exclusive else pinned_worker_id,
            exclusive_worker_id=pinned_worker_id if service.is_exclusive else None,
            district=service.district or (elder.district if elder else None),
            route=service.route,
            centre=centre,
            start_time=service.start_time,
            end_time=service.end_time,
            status="cancelled" if cancelling_override else "active",
            data_gaps=sorted(demand_gaps, key=lambda gap: gap.id),
            data_gap_ids=sorted({gap.id for gap in demand_gaps}),
            assumptions=(
                ["headcount inferred from master-data duty template cell"]
                if is_duty else []
            ),
            source_refs=sorted(set(source_refs)),
            source_evidence=merge_source_evidence(provenance),
            primary_source_evidence_id=service_evidence.id,
            override_ids=sorted(override.id for override in applied_overrides),
            depends_on=sorted({
                override.origin_audit_item_id
                for override in applied_overrides
                if override.origin_audit_item_id
            }),
            notes=service.notes,
        )
        demands.append(demand)
        if is_duty:
            counts["division_duty_slots"] += 1
        elif service.service_code == ServiceCode.MEAL:
            counts["division_meal"] += 1
        else:
            counts["division_fixed"] += 1
    return demands


def _availability_from_master_data(
    master_data: MasterDataSet,
    week_start: date,
    data_gaps: list[DataGap],
) -> tuple[list[WorkerAvailability], list[ChangeEvent]]:
    availability: list[WorkerAvailability] = []
    events: list[ChangeEvent] = []
    week = set(_week_dates(week_start))

    for row in master_data.availability:
        expanded = _expand_availability_row(row, week_start, data_gaps)
        availability.extend(expanded)

    for leave in master_data.leave_events:
        if leave.date not in week:
            continue
        period = _period_from_leave(leave)
        leave_identity = {
            "worker_id": leave.worker_id,
            "date": leave.date,
            "period": period,
        }
        fingerprint = content_fingerprint(leave_identity)
        evidence = SourceEvidence(
            kind="master_data",
            source_id="leave_events",
            source_version=master_data.schema_version,
            locator=f"master_data.leave_events:{fingerprint[:20]}",
            field="leave",
            content_fingerprint=fingerprint,
            confidence="high",
        )
        events.append(ChangeEvent(
            type=ChangeType.LEAVE,
            change_date=leave.date,
            period=period,
            worker_id=leave.worker_id,
            reason=leave.reason or "master data leave",
            source_refs=[f"master_data.leave_events:{fingerprint[:20]}"],
            source_evidence=[evidence],
        ))
        availability.append(WorkerAvailability(
            worker_id=leave.worker_id,
            available_date=leave.date,
            period=period,
            is_available=False,
            reason="leave",
            source=TaskSource.OPERATOR_INPUT,
            source_refs=[f"master_data.leave_events:{fingerprint[:20]}"],
            source_evidence=[evidence],
            notes=leave.reason,
        ))

    for override in master_data.manual_overrides:
        if override.action != "forbid_assignment":
            continue
        if not override.pin.worker_id:
            data_gaps.append(DataGap(
                kind="availability",
                entity_id=override.id,
                message=f"Manual override {override.id} 缺少 worker_id，未套用容量鎖。",
                blocking=True,
                source=TaskSource.OPERATOR_INPUT,
            ))
            continue
        dates = _dates_for_pin(override, week_start, data_gaps)
        override_evidence = _manual_override_evidence(master_data, override)
        periods = [override.pin.period] if override.pin.period else [Period.AM, Period.PM]
        for on in dates:
            if not _override_active_on(override, on):
                continue
            for period in periods:
                availability.append(WorkerAvailability(
                    worker_id=override.pin.worker_id,
                    available_date=on,
                    period=period,
                    is_available=False,
                    reason="manual_override",
                    source=TaskSource.OPERATOR_INPUT,
                    source_refs=[f"manual_override:{override.id}"],
                    source_evidence=[override_evidence],
                    override_ids=[override.id],
                    depends_on=(
                        [override.origin_audit_item_id]
                        if override.origin_audit_item_id else []
                    ),
                    notes=override.reason,
                ))

    return availability, events


def _expand_availability_row(
    row: WorkerAvailability,
    week_start: date,
    data_gaps: list[DataGap],
) -> list[WorkerAvailability]:
    if row.available_date is not None:
        if row.available_date in set(_week_dates(week_start)):
            return [row]
        return []
    if row.weekday is None:
        data_gaps.append(DataGap(
            kind="availability",
            entity_id=row.worker_id,
            message="Availability row 缺少 date/weekday，未套用。",
            blocking=True,
            source=row.source,
        ))
        return []
    on = week_start + timedelta(days=row.weekday - 1)
    return [row.model_copy(update={"available_date": on})]


def _config_gaps(master_data: MasterDataSet, data_gaps: list[DataGap]) -> None:
    for name, value in master_data.rule_config.values.items():
        if value.confirmed:
            continue
        data_gaps.append(DataGap(
            kind="other",
            entity_id=name,
            message=f"Rule config {name} 尚未由 NGO 確認：{value.assumption or value.value}",
            blocking=False,
            source=TaskSource.RULEBOOK,
        ))


def _master_field_evidence(
    master_data: MasterDataSet,
    *,
    entity_type: str,
    entity_id: str,
    field: str,
    confidence: str = "high",
    fingerprint_value: object | None = None,
) -> SourceEvidence:
    """Point at a canonical master-data field without using list position."""

    return SourceEvidence(
        kind="master_data",
        source_id=f"{entity_type}:{entity_id}",
        source_version=master_data.schema_version,
        locator=f"master_data.{entity_type}s:{entity_id}",
        field=field,
        content_fingerprint=(
            content_fingerprint(fingerprint_value)
            if fingerprint_value is not None else None
        ),
        confidence=confidence,  # type: ignore[arg-type]
    )


def _worker_skill_evidence(
    master_data: MasterDataSet,
    worker_id: str,
    fact: WorkerSkillFact,
) -> SourceEvidence:
    confidence = {
        "seed": "seed",
        "ngo_confirmed": "high",
        "manual": "high",
        "matrix": "medium",
        "template_bootstrap": "medium",
    }[fact.source]
    return _master_field_evidence(
        master_data,
        entity_type="worker",
        entity_id=worker_id,
        field=f"skill_facts:{fact.service_code.value}",
        confidence=confidence,
        fingerprint_value={
            "service_code": fact.service_code,
            "level": fact.level,
            "source": fact.source,
        },
    )


def _worker_route_evidence(
    master_data: MasterDataSet,
    worker_id: str,
    fact,
) -> SourceEvidence:
    confidence = {
        "seed": "seed",
        "ngo_confirmed": "high",
        "manual": "high",
        "matrix": "medium",
        "template_bootstrap": "medium",
    }[fact.source]
    return _master_field_evidence(
        master_data,
        entity_type="worker",
        entity_id=worker_id,
        field=f"route_facts:{fact.route_code}",
        confidence=confidence,
        fingerprint_value={
            "route_code": fact.route_code,
            "qualified": fact.qualified,
            "source": fact.source,
        },
    )


def _master_service_evidence(
    master_data: MasterDataSet,
    service: MasterFixedService,
) -> SourceEvidence:
    return _master_field_evidence(
        master_data,
        entity_type="fixed_service",
        entity_id=service.id,
        field="weekly_demand",
        confidence=service.source_confidence,
        fingerprint_value=service.model_dump(
            mode="json",
            exclude={"notes", "source_ref", "source_confidence"},
        ),
    )


def _manual_override_evidence(
    master_data: MasterDataSet,
    override: ManualOverride,
) -> SourceEvidence:
    return _master_field_evidence(
        master_data,
        entity_type="manual_override",
        entity_id=override.id,
        field="action",
        confidence="high",
        fingerprint_value=override.model_dump(
            mode="json",
            exclude={"reason"},
        ),
    )


def _ensure_master_elder(
    elders: list[MasterElder],
    aliases: dict[str, str],
    alias: object,
    *,
    district: object | None,
    unit: object | None,
) -> str | None:
    name = _clean(alias)
    if not name:
        return None
    key = _normalize_alias(name)
    if key in aliases:
        return aliases[key]
    elder_id = f"E{len(elders) + 1:04d}"
    elders.append(MasterElder(
        id=elder_id,
        display_name=name,
        gender=None,
        district=_clean(district) or _clean(unit) or "未提供",
        owning_unit=_clean(unit) or "EH",
        gender_requirement=GenderRequirement.ANY,
        status="active",
        notes="Template bootstrap elder alias; gender pending NGO confirmation.",
    ))
    aliases[key] = elder_id
    return elder_id


def _master_week_pattern(
    raw: str | None,
    weeks: tuple[int, ...] | None,
) -> tuple[WeekPattern, bool]:
    if weeks:
        return (
            WeekPattern(kind="weeks_of_month", weeks=list(weeks),
                        raw=",".join(str(w) for w in weeks)),
            False,
        )
    if not raw:
        return WeekPattern(), False
    try:
        return WeekPattern.parse(raw), False
    except ValueError:
        return WeekPattern(raw=raw), True


def _kind_for_service(service_code: ServiceCode) -> TaskKind:
    if service_code == ServiceCode.HOME_CLEAN:
        return TaskKind.HC_PATTERN
    if service_code == ServiceCode.MEAL:
        return TaskKind.MEAL_LOGISTICS
    return TaskKind.FIXED_SERVICE


def _matching_override(
    overrides: list[ManualOverride],
    service: MasterFixedService,
    week_start: date,
    *,
    action: str,
) -> ManualOverride | None:
    for override in overrides:
        if (
            override.action == action
            and _override_matches_service(override, service, week_start)
        ):
            return override
    return None


def _override_matches_service(
    override: ManualOverride,
    service: MasterFixedService,
    week_start: date,
) -> bool:
    pin = override.pin
    on = week_start + timedelta(days=service.weekday - 1)
    if not _override_active_on(override, on):
        return False
    checks = [
        pin.worker_id is None or pin.worker_id == service.assigned_worker_id,
        pin.elder_id is None or pin.elder_id == service.elder_id,
        pin.date is None or pin.date == on,
        pin.weekday is None or pin.weekday == service.weekday,
        pin.period is None or pin.period == service.period,
        pin.service_code is None or pin.service_code == service.service_code,
    ]
    return all(checks)


def _dates_for_pin(
    override: ManualOverride,
    week_start: date,
    data_gaps: list[DataGap],
) -> list[date]:
    if override.pin.date is not None:
        return [override.pin.date] if override.pin.date in set(_week_dates(week_start)) else []
    if override.pin.weekday is not None:
        return [week_start + timedelta(days=override.pin.weekday - 1)]
    data_gaps.append(DataGap(
        kind="availability",
        entity_id=override.id,
        message=f"Manual override {override.id} 缺少 date/weekday，未套用容量鎖。",
        blocking=True,
        source=TaskSource.OPERATOR_INPUT,
    ))
    return []


def _override_active_on(override: ManualOverride, on: date) -> bool:
    if override.effective_from and on < override.effective_from:
        return False
    if override.effective_to and on > override.effective_to:
        return False
    return True


def _period_from_leave(leave: LeaveEvent) -> Period | None:
    if leave.scope == "AM":
        return Period.AM
    if leave.scope == "PM":
        return Period.PM
    return None


def _service_code(value: object) -> ServiceCode | None:
    text = _clean(value).upper()
    if not text:
        return None
    aliases = {
        "ESC": ServiceCode.ESCORT,
        "ESCORT": ServiceCode.ESCORT,
        "E+RO": ServiceCode.EXERCISE,
        "ERO": ServiceCode.EXERCISE,
        "HC": ServiceCode.HOME_CLEAN,
        "PC": ServiceCode.PERSONAL_CARE,
        "B": ServiceCode.BATH,
        "D": ServiceCode.MEAL,
        "AMC": ServiceCode.DUTY_AMC,
        "MRC": ServiceCode.DUTY_MRC,
        "GC": ServiceCode.DUTY_GC,
        "KITCHEN": ServiceCode.KITCHEN,
    }
    return aliases.get(text)


def _parse_time(value: object) -> time | None:
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    text = _clean(value)
    if not text:
        return None
    match = re.search(r"(\d{1,2})[:：](\d{2})", text)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return time(hour, minute)
    return None


def _assignment_ref(assignment: ParsedAssignment) -> str:
    return assignment.cell.label


def _week_dates(week_start: date) -> list[date]:
    return [week_start + timedelta(days=i) for i in range(6)]


def _clean(value: object) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = text.replace("：", ":").replace("（", "(").replace("）", ")")
    return re.sub(r"\s+", " ", text).strip()


def _normalize_alias(value: object) -> str:
    text = _clean(value)
    text = re.sub(r"(照顧員|姑娘|姐姐|姐)$", "", text)
    text = re.sub(r"[^\w一-鿿]+", "", text)
    return text.lower()


def _alias_variants(*values: object) -> set[str]:
    out: set[str] = set()
    for value in values:
        text = _clean(value)
        if not text:
            continue
        candidates = {text}
        candidates.add(re.sub(r"\([^)]*\)", "", text).strip())
        candidates.add(text.split()[0])
        for candidate in candidates:
            key = _normalize_alias(candidate)
            if key:
                out.add(key)
    return out


def _resolve_alias(mapping: dict[str, str], alias: object) -> str | None:
    for variant in _alias_variants(alias):
        if variant in mapping:
            return mapping[variant]
    return None


def _dedupe_gaps(gaps: list[DataGap]) -> list[DataGap]:
    by_id: dict[str, DataGap] = {}
    for gap in gaps:
        prior = by_id.get(gap.id)
        if prior is None:
            by_id[gap.id] = gap
            continue
        by_id[gap.id] = prior.model_copy(update={
            "blocking": prior.blocking or gap.blocking,
            "message": min(prior.message, gap.message),
            "source": min((prior.source, gap.source), key=lambda item: item.value),
        })
    return [by_id[gap_id] for gap_id in sorted(by_id)]
