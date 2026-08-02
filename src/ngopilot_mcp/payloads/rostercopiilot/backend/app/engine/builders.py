"""Factories for ScheduleEntry and AuditItem objects (shared by baseline & repair)."""
from __future__ import annotations

from dataclasses import replace
from itertools import count

from ..domain import (
    AuditItem,
    AuditKind,
    Employee,
    EntrySource,
    EntryStatus,
    ManualReviewReason,
    ReviewReasonCode,
    ScheduleEntry,
    Severity,
    ServiceCode,
    merge_source_evidence,
)
from .context import ScheduleContext
from .tasks import Task

_audit_counter = count(1)


def reset_audit_counter() -> None:
    global _audit_counter
    _audit_counter = count(1)


def next_audit_id() -> str:
    return f"audit-{next(_audit_counter):05d}"


def entry_from_task(task: Task, worker: Employee | None, ctx: ScheduleContext, *,
                    source: EntrySource, status: EntryStatus,
                    explanation: str | None = None,
                    reasons: list[ManualReviewReason] | None = None,
                    id_prefix: str = "entry") -> ScheduleEntry:
    role = "alternative" if id_prefix == "alt" else "current"
    evidence = list(task.source_evidence)
    source_refs = set(task.source_refs)
    override_ids = set(task.override_ids)
    depends_on = set(task.depends_on)
    for row in ctx.dataset.unavailable_slots:
        if (
            worker is None
            or row.worker_id != worker.id
            or row.is_available
            or row.reason != "manual_override"
            or row.available_date != task.task_date
            or (row.period is not None and row.period != task.period)
            or (
                row.session_index is not None
                and row.session_index != task.session_index
            )
        ):
            continue
        source_refs.update(row.source_refs)
        evidence.extend(row.source_evidence)
        override_ids.update(row.override_ids)
        depends_on.update(row.depends_on)
    gap_policies = dict(task.data_gap_policies)
    gap_ids = (
        set(task.data_gap_ids)
        if status in {EntryStatus.UNASSIGNED, EntryStatus.CANCELLED}
        else {gap_id for gap_id, policy in gap_policies.items()
              if policy == "allowed_with_review"}
    )
    flags: list[str] = []
    review_reasons = list(reasons or [])
    used_seed_skill = bool(
        worker
        and task.service_code in getattr(worker, "seed_skills", [])
        and task.service_code in {
            ServiceCode.EXERCISE,
            ServiceCode.HOME_CLEAN,
            ServiceCode.PERSONAL_CARE,
            ServiceCode.BATH,
            ServiceCode.ESCORT,
            ServiceCode.DUTY_AMC,
            ServiceCode.DUTY_MRC,
            ServiceCode.DUTY_GC,
            ServiceCode.KITCHEN,
        }
    )
    if used_seed_skill and worker is not None:
        seed_gap = getattr(worker, "seed_skill_gap_ids", {}).get(task.service_code)
        if seed_gap:
            gap_ids.add(seed_gap)
            gap_policies[seed_gap] = getattr(
                worker, "data_gap_policies", {}
            ).get(seed_gap, "allowed_with_review")
        evidence.extend(
            item for item in getattr(worker, "source_evidence", [])
            if item.field == f"skill_facts:{task.service_code.value}"
        )
        flags.append("seed_skill_unverified")
        review_reasons.append(ManualReviewReason(
            code=ReviewReasonCode.SKILL_MISMATCH,
            message=f"{worker.display_name} 的 {task.service_code.value} 技能仍是 seed 資料",
            params={"worker_id": worker.id, "service": task.service_code.value},
            rule_ref="RB-SKILL-01",
        ))
    if worker and task.service_code == ServiceCode.MEAL and task.route:
        route_evidence = [
            item for item in getattr(worker, "source_evidence", [])
            if item.field == f"route_facts:{task.route}"
        ]
        evidence.extend(route_evidence)
        route_gap = getattr(worker, "route_gap_ids", {}).get(task.route)
        if route_gap:
            gap_ids.add(route_gap)
            gap_policies[route_gap] = getattr(
                worker, "data_gap_policies", {}
            ).get(route_gap, "allowed_with_review")
            flags.append("route_qualification_unverified")
            review_reasons.append(ManualReviewReason(
                code=ReviewReasonCode.ROUTE_UNQUALIFIED,
                message=(
                    f"{worker.display_name} 的送飯路線 {task.route} 資格尚未確認"
                ),
                params={"worker_id": worker.id, "route": task.route},
                rule_ref="RB-SKILL-03",
            ))
    if task.gender_ok_unverified and worker is not None:
        flags.append("gender_ok_unverified")
        if not any(reason.code == ReviewReasonCode.GENDER_UNKNOWN
                   for reason in review_reasons):
            review_reasons.append(ManualReviewReason(
                code=ReviewReasonCode.GENDER_UNKNOWN,
                message="長者性別要求未能核實，這個安排必須人工審核",
                params={"elder_id": task.elder_id or ""},
                rule_ref="RB-GEND-01",
            ))
    evidence = merge_source_evidence(evidence)
    low_confidence_used = any(item.confidence in {"low", "seed"} for item in evidence)
    if low_confidence_used:
        flags.append("low_confidence_evidence_used")
    if status == EntryStatus.SCHEDULED and (used_seed_skill or gap_ids or low_confidence_used):
        status = EntryStatus.NEEDS_REVIEW
    return ScheduleEntry(
        id=ctx.next_entry_id(id_prefix),
        demand_id=task.demand_id,
        entry_role=role,
        revision=ctx.next_demand_revision(task.demand_id, role),
        schedule_date=task.task_date,
        weekday=task.weekday,  # type: ignore[arg-type]
        period=task.period,
        session_index=task.session_index,  # type: ignore[arg-type]
        worker_id=worker.id if worker else None,
        worker_name=worker.display_name if worker else "待分配",
        service_code=task.service_code,
        elder_id=task.elder_id,
        elder_name=task.elder_name,
        center=task.center,
        district=task.district,
        route=task.route,
        destination=task.destination,
        start_time=task.start_time,
        end_time=task.end_time,
        source=source,
        status=status,
        explanation=explanation,
        review_reasons=review_reasons,
        constraint_flags=flags,
        source_refs=sorted(source_refs),
        source_evidence=evidence,
        data_gap_ids=sorted(gap_ids),
        data_gap_policies={
            gap_id: gap_policies[gap_id]
            for gap_id in sorted(gap_ids)
            if gap_id in gap_policies
        },
        assumptions=list(task.assumptions),
        override_ids=sorted(override_ids),
        depends_on=sorted(depends_on),
        origin_fixed_service_id=task.origin_fixed_service_id,
        origin_escort_request_id=task.origin_escort_request_id,
        notes=task.notes,
    )


def task_with_candidate_uncertainty(task: Task, ctx: ScheduleContext) -> Task:
    """Attach only worker gaps that actually explain why nobody is eligible."""

    from .eligibility import check_assignment

    gap_ids = set(task.data_gap_ids)
    policies = dict(task.data_gap_policies)
    evidence = list(task.source_evidence)
    source_refs = set(task.source_refs)
    override_ids = set(task.override_ids)
    depends_on = set(task.depends_on)
    for worker in ctx.dataset.employees:
        codes = {reason.code for reason in check_assignment(worker, task, ctx)}
        relevant_fields: set[str] = set()
        if ReviewReasonCode.SKILL_MISMATCH in codes:
            relevant_fields.update({
                "skill_facts",
                f"skill_facts:{task.service_code.value}",
            })
        if ReviewReasonCode.GENDER_UNKNOWN in codes:
            relevant_fields.add("gender")
        if ReviewReasonCode.ROUTE_UNQUALIFIED in codes and task.route:
            relevant_fields.add(f"route_facts:{task.route}")
        if ReviewReasonCode.NOT_WORKING_DAY in codes and task.weekday == 6:
            relevant_fields.add("saturday_team")
        if ReviewReasonCode.WORKER_ON_LEAVE in codes:
            leave = ctx.leave_provenance(
                worker.id, task.task_date, task.period
            )
            source_refs.update(leave["source_refs"])
            evidence.extend(leave["source_evidence"])
            gap_ids.update(leave["data_gap_ids"])
            policies.update(leave["data_gap_policies"])
            override_ids.update(leave["override_ids"])
            depends_on.update(leave["depends_on"])
        if ReviewReasonCode.FORBIDDEN_ASSIGNMENT in codes:
            for row in ctx.dataset.unavailable_slots:
                if (
                    row.reason == "manual_override"
                    and row.worker_id == worker.id
                    and row.available_date == task.task_date
                    and (row.period is None or row.period == task.period)
                ):
                    source_refs.update(row.source_refs)
                    evidence.extend(row.source_evidence)
                    override_ids.update(row.override_ids)
                    depends_on.update(row.depends_on)
        for gap_id, field_name in worker.data_gap_fields.items():
            if field_name not in relevant_fields:
                continue
            gap_ids.add(gap_id)
            policies[gap_id] = worker.data_gap_policies.get(gap_id, "ineligible")
            for item in worker.source_evidence:
                if item.field == field_name:
                    evidence.append(item)
    return replace(
        task,
        data_gap_ids=tuple(sorted(gap_ids)),
        data_gap_policies=policies,
        source_evidence=tuple(merge_source_evidence(evidence)),
        source_refs=tuple(sorted(source_refs)),
        override_ids=tuple(sorted(override_ids)),
        depends_on=tuple(sorted(depends_on)),
    )


def make_audit(*, kind: AuditKind, severity: Severity, blocking: bool,
               reason: str, reasons: list[ManualReviewReason] | None = None,
               original_entry: ScheduleEntry | None = None,
               suggested_entry: ScheduleEntry | None = None,
               alternatives: list[ScheduleEntry] | None = None,
               chain=None, trigger_event_id: str | None = None) -> AuditItem:
    return AuditItem(
        id=next_audit_id(),
        kind=kind,
        severity=severity,
        blocking=blocking,
        reason=reason,
        reasons=reasons or [],
        original_entry=original_entry,
        suggested_entry=suggested_entry,
        alternatives=alternatives or [],
        chain=chain or [],
        trigger_event_id=trigger_event_id,
    )
