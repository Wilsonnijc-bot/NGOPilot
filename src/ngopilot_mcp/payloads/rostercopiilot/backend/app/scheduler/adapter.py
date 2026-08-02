"""Adapter: SchedulerSnapshot → engine ``MockDataset``.

The existing greedy engine (``build_baseline`` / ``apply_changes``) consumes a
``MockDataset`` and does its own task generation, eligibility gating, ranking,
audit emission, validation and metrics. Rather than rewrite that mature engine,
this adapter *lowers* a snapshot's generated demand into the domain objects the
engine already understands (ENGINEERING_SPEC.md §2: "if the current engine
model is too mock-specific, introduce an adapter").

Because the generator already applied week-of-month patterns and dated every
task to the target week, the lowered ``FixedService`` objects carry a plain
weekly pattern — the engine must not re-filter what the generator already
decided.
"""
from __future__ import annotations

from ..domain import (
    CenterDutyRequirement,
    Elder,
    EscortRequest,
    FixedService,
    GenderRequirement,
    MockDataset,
    Period,
    ScheduleParams,
    ServiceCode,
    TaskDemand,
    TaskKind,
    WeekPattern,
    merge_source_evidence,
)
from .generator import GeneratedDemands

# Fixed-template kinds the engine schedules as FixedService occurrences.
_FIXED_KINDS = {
    TaskKind.FIXED_SERVICE,
    TaskKind.HC_PATTERN,
    TaskKind.MEAL_LOGISTICS,
}


def to_dataset(snapshot, generated: GeneratedDemands) -> MockDataset:
    """Build the engine dataset from a snapshot and its generated demand."""
    fixed_services = [
        _fixed_from_demand(t)
        for t in generated.tasks
        if t.kind in _FIXED_KINDS
    ]
    escort_requests = [
        _escort_from_demand(t)
        for t in generated.tasks
        if t.kind == TaskKind.ESCORT
    ]
    params = ScheduleParams(
        week_start=snapshot.week_start,
        escort_baseline=snapshot.config.escort_occupancy
        .baseline_reserved_workers_per_half_day,
        districts=sorted({e.district for e in snapshot.elders if e.district}),
    )
    employees = [worker.model_copy(deep=True) for worker in snapshot.workers]
    employee_by_id = {worker.id: worker for worker in employees}
    generated_evidence = {item.id: item for item in generated.source_evidence}
    for worker in employees:
        worker.source_evidence = merge_source_evidence(
            generated_evidence.get(item.id, item)
            for item in worker.source_evidence
        )
    for gap in generated.data_gaps:
        if not gap.entity_id:
            continue
        worker = employee_by_id.get(gap.entity_id)
        if worker is None:
            continue
        worker.data_gap_ids = sorted({*worker.data_gap_ids, gap.id})
        worker.data_gap_policies[gap.id] = gap.policy
        worker.data_gap_fields[gap.id] = gap.field or gap.kind
        prefix = "route_facts:"
        if gap.kind == "route" and gap.field and gap.field.startswith(prefix):
            route = gap.field.removeprefix(prefix)
            worker.route_gap_ids[route] = gap.id
        linked_evidence = []
        for evidence_id in gap.source_ref_ids:
            if evidence_id in generated_evidence:
                linked_evidence.append(generated_evidence[evidence_id])
        worker.source_evidence = merge_source_evidence(
            worker.source_evidence, linked_evidence
        )
    return MockDataset(
        employees=employees,
        elders=list(snapshot.elders),
        fixed_services=fixed_services,
        escort_requests=escort_requests,
        duty_requirements=list(generated.duty_requirements),
        unavailable_slots=[
            row.model_copy(update={
                "source_evidence": merge_source_evidence(
                    generated_evidence.get(item.id, item)
                    for item in row.source_evidence
                ),
            })
            for row in snapshot.availability
            if not row.is_available and row.reason == "manual_override"
        ],
        params=params,
    )


def _fixed_from_demand(demand: TaskDemand) -> FixedService:
    exclusive = demand.exclusive_worker_id is not None
    assigned = demand.exclusive_worker_id or demand.pinned_worker_id
    gaps = {gap.id: gap for gap in demand.data_gaps}
    return FixedService(
        id=demand.id,
        elder_id=demand.elder_id,
        service_code=demand.service_code or ServiceCode.MEAL,
        weekday=demand.weekday,  # type: ignore[arg-type]
        period=demand.period or Period.AM,
        session_index=demand.session_index or 1,  # type: ignore[arg-type]
        start_time=demand.start_time,
        end_time=demand.end_time,
        # The generator already gated the week-of-month pattern; a weekly pattern
        # here prevents the engine from filtering the occurrence a second time.
        week_pattern=WeekPattern(),
        assigned_worker_id=assigned,
        is_exclusive=exclusive,
        district=demand.district,
        route=demand.route,
        center=demand.centre,
        priority=0,
        notes=demand.notes,
        demand_id=demand.demand_id,
        source_refs=list(demand.source_refs),
        source_evidence=list(demand.source_evidence),
        data_gap_ids=list(demand.data_gap_ids),
        data_gap_policies={
            gap_id: gaps[gap_id].policy if gap_id in gaps else "ineligible"
            for gap_id in demand.data_gap_ids
        },
        gender_ok_unverified=any(
            gap.kind == "gender" and gap.policy == "allowed_with_review"
            for gap in demand.data_gaps
        ),
        assumptions=list(demand.assumptions),
        override_ids=list(demand.override_ids),
        depends_on=list(demand.depends_on),
    )


def _escort_from_demand(demand: TaskDemand) -> EscortRequest:
    gaps = {gap.id: gap for gap in demand.data_gaps}
    return EscortRequest(
        id=demand.id,
        service_date=demand.task_date,  # type: ignore[arg-type]
        period=demand.period or Period.AM,
        elder_id=demand.elder_id or "",
        appointment_time=demand.start_time,
        destination=demand.destination or "",
        subject=demand.notes,
        gender_requirement=demand.gender_requirement or GenderRequirement.ANY,
        preferred_worker_id=demand.preferred_worker_id,
        preference_strength=demand.preference_strength,
        status="requested",
        notes=demand.notes,
        demand_id=demand.demand_id,
        source_refs=list(demand.source_refs),
        source_evidence=list(demand.source_evidence),
        data_gap_ids=list(demand.data_gap_ids),
        data_gap_policies={
            gap_id: gaps[gap_id].policy if gap_id in gaps else "ineligible"
            for gap_id in demand.data_gap_ids
        },
        gender_ok_unverified=any(
            gap.kind == "gender" and gap.policy == "allowed_with_review"
            for gap in demand.data_gaps
        ),
        assumptions=list(demand.assumptions),
        override_ids=list(demand.override_ids),
        depends_on=list(demand.depends_on),
    )
