"""Event-driven repair of a published roster (rescheduling_algorithm.md).

Given a baseline version and a batch of ChangeEvents, produce a child
version in which:
- affected entries are marked, never silently mutated,
- every automatic proposal is a NEEDS_REVIEW entry plus an AuditItem,
- freed capacity is offered to duty gaps first (RB-DUTY-04),
- hard constraints are never relaxed (shared eligibility gate).

Event order: free capacity first (cancellations), then consume (leaves,
new escorts) — deterministic and maximises repair room (§9 of the spec).
"""
from __future__ import annotations

import time as _time
import uuid
from datetime import datetime, timezone

from ..domain import (
    AuditItem,
    AuditKind,
    ChainStep,
    ChangeEvent,
    ChangeType,
    EntrySource,
    EntryStatus,
    ImpactItem,
    ImpactReport,
    ManualReviewReason,
    MockDataset,
    Period,
    PRIORITY_TIER,
    ReviewReasonCode,
    ScheduleEntry,
    ScheduleVersion,
    ServiceCode,
    Severity,
    VersionKind,
    merge_source_evidence,
)
from .builders import entry_from_task, make_audit, task_with_candidate_uncertainty
from .context import ScheduleContext, week_dates
from .eligibility import check_assignment, eligible_workers
from .metrics import compute_metrics
from .ranking import rank_candidates, ranking_explanation
from .scheduler import _diagnose_unassignable
from .tasks import Task, duty_tasks, task_from_escort

_EVENT_ORDER = {
    ChangeType.ELDER_CANCELLATION: 0,
    ChangeType.ESCORT_CANCELLED: 1,
    ChangeType.LEAVE: 2,
    ChangeType.ESCORT_NEW: 3,
}


def apply_changes(dataset: MockDataset, baseline: ScheduleVersion,
                  events: list[ChangeEvent]) -> tuple[ScheduleVersion, list[ImpactReport]]:
    started = _time.perf_counter()
    # working copy — the baseline stays immutable
    entries = [e.model_copy(deep=True) for e in baseline.entries]
    ctx = ScheduleContext(dataset, entries)
    audits: list[AuditItem] = [a.model_copy(deep=True) for a in baseline.audit_items]
    _rebind_audit_entries(audits, {entry.id: entry for entry in entries})
    reports: list[ImpactReport] = []

    ordered = sorted(events, key=lambda ev: (_EVENT_ORDER[ev.type], ev.change_date,
                                             ev.id or ""))
    for i, event in enumerate(ordered):
        if not event.id:
            event.id = f"ev-{i + 1}"
        handler = {
            ChangeType.LEAVE: _handle_leave,
            ChangeType.ELDER_CANCELLATION: _handle_elder_cancellation,
            ChangeType.ESCORT_CANCELLED: _handle_escort_cancelled,
            ChangeType.ESCORT_NEW: _handle_escort_new,
        }[event.type]
        new_audits = handler(event, ctx)
        _attach_event_provenance(event, new_audits)
        audits.extend(new_audits)
        reports.append(_report_for(event, new_audits))

    version = ScheduleVersion(
        id=f"v-{uuid.uuid4().hex[:10]}",
        kind=VersionKind.REPAIR,
        parent_version_id=baseline.id,
        created_at=datetime.now(timezone.utc),
        week_start=baseline.week_start,
        entries=ctx.entries,
        audit_items=audits,
        unassigned=[e for e in ctx.entries if e.status == EntryStatus.UNASSIGNED],
        trigger_events=ordered,
        impacts=[imp for r in reports for imp in r.impacts],
    )
    version.summary = compute_metrics(
        dataset, version, leaves=ctx.leaves,
        runtime_ms=(_time.perf_counter() - started) * 1000, parent=baseline,
    )
    return version, reports


def _rebind_audit_entries(
    audits: list[AuditItem],
    entries: dict[str, ScheduleEntry],
) -> None:
    """Make inherited audit references point at the child working-copy entry."""

    for audit in audits:
        if audit.original_entry and audit.original_entry.id in entries:
            audit.original_entry = entries[audit.original_entry.id]
        if audit.suggested_entry and audit.suggested_entry.id in entries:
            audit.suggested_entry = entries[audit.suggested_entry.id]
        audit.alternatives = [
            entries.get(entry.id, entry) for entry in audit.alternatives
        ]
        for step in audit.chain:
            if step.entry_before and step.entry_before.id in entries:
                step.entry_before = entries[step.entry_before.id]
            if step.entry_after.id in entries:
                step.entry_after = entries[step.entry_after.id]


def _attach_event_provenance(
    event: ChangeEvent,
    audits: list[AuditItem],
) -> None:
    evidence = {item.id: item for item in event.source_evidence}
    for audit in audits:
        audit.evidence_refs = sorted({*audit.evidence_refs, *evidence})
        audit.data_gap_ids = sorted({*audit.data_gap_ids, *event.data_gap_ids})
        audit.override_ids = sorted({*audit.override_ids, *event.override_ids})
        audit.depends_on = sorted({*audit.depends_on, *event.depends_on})
        embedded = [
            entry for entry in (audit.original_entry, audit.suggested_entry)
            if entry is not None
        ]
        embedded.extend(audit.alternatives)
        for step in audit.chain:
            if step.entry_before is not None:
                embedded.append(step.entry_before)
            embedded.append(step.entry_after)
        for entry in embedded:
            entry.source_refs = sorted({*entry.source_refs, *event.source_refs})
            entry.source_evidence = merge_source_evidence(
                entry.source_evidence, event.source_evidence
            )
            entry.data_gap_ids = sorted({*entry.data_gap_ids, *event.data_gap_ids})
            entry.data_gap_policies.update(event.data_gap_policies)
            entry.override_ids = sorted({*entry.override_ids, *event.override_ids})
            entry.depends_on = sorted({*entry.depends_on, *event.depends_on})


# --------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------

def _handle_leave(event: ChangeEvent, ctx: ScheduleContext) -> list[AuditItem]:
    audits: list[AuditItem] = []
    if not event.worker_id:
        return audits
    ctx.add_leave(
        event.worker_id,
        event.change_date,
        event.period,
        source_refs=event.source_refs,
        source_evidence=event.source_evidence,
        data_gap_ids=event.data_gap_ids,
        data_gap_policies=event.data_gap_policies,
        override_ids=event.override_ids,
        depends_on=event.depends_on,
    )
    worker = ctx.employees.get(event.worker_id)
    wname = worker.display_name if worker else event.worker_id

    affected = ctx.entries_for_worker(event.worker_id, event.change_date, event.period)
    # duty first: scarcest, and freed replacements may need the others' slots
    affected.sort(key=lambda e: PRIORITY_TIER[e.service_code])

    for entry in affected:
        ctx.set_status(entry, EntryStatus.AFFECTED)
        entry.review_reasons.append(ManualReviewReason(
            code=ReviewReasonCode.WORKER_ON_LEAVE,
            message=f"{wname} 請假：{event.reason or ''}".strip(),
            params={"event_id": event.id or ""}, rule_ref="RB-LEAVE-01"))

        if _is_exclusive_entry(entry, ctx):
            # RB-EXCL-02: cancel, never substitute; blocking review.
            suggestion = entry.model_copy(deep=True)
            suggestion.id = ctx.next_entry_id("cancel")
            suggestion.entry_role = "alternative"
            suggestion.revision = ctx.next_demand_revision(
                suggestion.demand_id, suggestion.entry_role
            )
            suggestion.status = EntryStatus.CANCELLED
            suggestion.source = EntrySource.SYSTEM_REASSIGNED
            suggestion.explanation = "專屬服務：同工請假建議取消（不設代更），待人工確認"
            audits.append(make_audit(
                kind=AuditKind.EXCLUSIVE_CANCELLATION, severity=Severity.HIGH,
                blocking=True,
                reason=f"{wname} 請假，{entry.elder_name} 的專屬"
                       f"{entry.service_code.value} 建議取消",
                reasons=[ManualReviewReason(
                    code=ReviewReasonCode.EXCLUSIVE_WORKER_ABSENT,
                    message="專屬服務不設代更（RB-EXCL-02）",
                    rule_ref="RB-EXCL-02")],
                original_entry=entry, suggested_entry=suggestion,
                trigger_event_id=event.id))
            continue

        task = _task_from_entry(entry, ctx)
        audits.append(_propose_replacement(
            entry, task, ctx, exclude={event.worker_id},
            trigger_event_id=event.id,
            context=f"{wname} 請假"))
    return audits


def _handle_elder_cancellation(event: ChangeEvent, ctx: ScheduleContext) -> list[AuditItem]:
    audits: list[AuditItem] = []
    if not event.elder_id:
        return audits
    elder = ctx.elders.get(event.elder_id)
    ename = elder.display_name if elder else event.elder_id

    for entry in ctx.entries_for_elder(event.elder_id, event.change_date, event.period):
        was_exclusive = _is_exclusive_entry(entry, ctx)
        freed_worker_id = entry.worker_id
        ctx.set_status(entry, EntryStatus.CANCELLED)
        entry.review_reasons.append(ManualReviewReason(
            code=ReviewReasonCode.ELDER_CANCELLED,
            message=f"長者取消：{event.reason or ''}".strip(),
            params={"event_id": event.id or ""}))
        entry.explanation = (entry.explanation or "") + f"｜長者取消（{event.reason or ''}）"
        audits.append(make_audit(
            kind=AuditKind.SERVICE_CANCELLATION,
            severity=Severity.HIGH if was_exclusive else Severity.INFO,
            blocking=was_exclusive,
            reason=f"{ename} 取消 {entry.service_code.value}（{event.reason or ''}）",
            reasons=list(entry.review_reasons), original_entry=entry,
            trigger_event_id=event.id))
        if freed_worker_id:
            refill = _propose_refill(freed_worker_id, entry, ctx, event)
            if refill:
                audits.append(refill)
    return audits


def _handle_escort_cancelled(event: ChangeEvent, ctx: ScheduleContext) -> list[AuditItem]:
    audits: list[AuditItem] = []
    target = next((e for e in ctx.entries
                   if e.origin_escort_request_id == event.escort_request_id
                   and e.status in (EntryStatus.SCHEDULED, EntryStatus.NEEDS_REVIEW,
                                    EntryStatus.UNASSIGNED)), None)
    if target is None:
        return audits
    freed_worker_id = target.worker_id
    ctx.set_status(target, EntryStatus.CANCELLED)
    target.explanation = (target.explanation or "") + f"｜護送取消（{event.reason or ''}）"
    audits.append(make_audit(
        kind=AuditKind.ESCORT_ADJUSTMENT, severity=Severity.INFO, blocking=False,
        reason=f"{target.elder_name} {target.schedule_date} {target.period.value} "
               f"護送取消（{event.reason or ''}）",
        original_entry=target, trigger_event_id=event.id))
    if freed_worker_id:
        refill = _propose_refill(freed_worker_id, target, ctx, event)
        if refill:
            audits.append(refill)
    return audits


def _handle_escort_new(event: ChangeEvent, ctx: ScheduleContext) -> list[AuditItem]:
    audits: list[AuditItem] = []
    if event.new_escort is None:
        return audits
    req = event.new_escort
    elder = ctx.elders.get(req.elder_id)
    task = task_from_escort(req, elder)

    candidates = rank_candidates(eligible_workers(task, ctx), task, ctx)
    if candidates:
        best = candidates[0]
        suggestion = ctx.add_entry(entry_from_task(
            task, best, ctx, source=EntrySource.SYSTEM_REASSIGNED,
            status=EntryStatus.NEEDS_REVIEW,
            explanation=f"臨時新增護送：建議 {best.display_name}"
                        f"（{ranking_explanation(best, task, ctx)}）",
            id_prefix="escort"))
        audits.append(make_audit(
            kind=AuditKind.ESCORT_ADJUSTMENT, severity=Severity.WARNING,
            blocking=False,
            reason=f"新增護送 {task.elder_name} {task.task_date} "
                   f"{task.period.value}：建議 {best.display_name}",
            reasons=[ManualReviewReason(
                code=ReviewReasonCode.ESCORT_OVER_BASELINE,
                message="臨時新增護送，需人手確認", rule_ref="RB-ESC-03")],
            suggested_entry=suggestion,
            alternatives=[entry_from_task(
                task, alt, ctx, source=EntrySource.SYSTEM_REASSIGNED,
                status=EntryStatus.NEEDS_REVIEW,
                explanation=ranking_explanation(alt, task, ctx), id_prefix="alt")
                for alt in candidates[1:3]],
            trigger_event_id=event.id))
        return audits

    # nobody free -> displacement chain, depth 1 (RB-ESC-03)
    chain_audit = _try_displacement_chain(task, ctx, event)
    if chain_audit:
        audits.append(chain_audit)
        return audits

    diagnosis = _diagnose_unassignable(task, ctx)
    entry = ctx.add_entry(entry_from_task(
        task, None, ctx, source=EntrySource.SYSTEM_REASSIGNED,
        status=EntryStatus.UNASSIGNED,
        explanation="新增護送未能分配：" + "；".join(r.message for r in diagnosis[:3]),
        reasons=diagnosis, id_prefix="escort"))
    audits.append(make_audit(
        kind=AuditKind.UNASSIGNED_TASK, severity=Severity.HIGH, blocking=True,
        reason=f"新增護送 {task.elder_name} 未能分配（連調動方案都不可行）",
        reasons=diagnosis, original_entry=entry, trigger_event_id=event.id))
    return audits


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

def _is_exclusive_entry(entry: ScheduleEntry, ctx: ScheduleContext) -> bool:
    fs = next((f for f in ctx.dataset.fixed_services
               if f.id == entry.origin_fixed_service_id), None)
    if fs is not None and fs.is_exclusive:
        return True
    elder = ctx.elders.get(entry.elder_id or "")
    return bool(elder and elder.exclusive_worker_id
                and elder.exclusive_worker_id == entry.worker_id
                and entry.service_code == ServiceCode.EXERCISE)


def _task_from_entry(entry: ScheduleEntry, ctx: ScheduleContext) -> Task:
    """Rebuild the demand task behind an existing entry (for re-assignment)."""
    elder = ctx.elders.get(entry.elder_id or "")
    fs = next((f for f in ctx.dataset.fixed_services
               if f.id == entry.origin_fixed_service_id), None)
    escort = ctx.dataset.escort_map().get(entry.origin_escort_request_id or "")
    if escort is not None:
        return task_from_escort(escort, elder)
    source_policies = dict(entry.data_gap_policies)
    if fs is not None:
        source_policies.update(fs.data_gap_policies)
    else:
        matching_duties = [
            requirement
            for requirement in ctx.dataset.duty_requirements
            if entry.demand_id in requirement.demand_ids
            or (
                not requirement.demand_ids
                and requirement.center == entry.center
                and requirement.weekday == entry.weekday
                and requirement.period == entry.period
            )
        ]
        for requirement in matching_duties:
            source_policies.update(requirement.data_gap_policies)
    from .tasks import resolve_gender_requirement
    from ..domain import GenderRequirement
    return Task(
        key=f"reassign:{entry.id}",
        demand_id=entry.demand_id,
        service_code=entry.service_code,
        task_date=entry.schedule_date,
        weekday=entry.weekday,
        period=entry.period,
        session_index=entry.session_index,
        elder_id=entry.elder_id,
        elder_name=entry.elder_name,
        district=entry.district,
        center=entry.center,
        route=entry.route,
        destination=entry.destination,
        start_time=entry.start_time,
        end_time=entry.end_time,
        pinned_worker_id=fs.assigned_worker_id if fs else None,
        is_exclusive=bool(fs and fs.is_exclusive),
        gender_requirement=resolve_gender_requirement(
            entry.service_code, elder,
            elder.gender_requirement if elder else GenderRequirement.ANY),
        origin_fixed_service_id=entry.origin_fixed_service_id,
        origin_escort_request_id=entry.origin_escort_request_id,
        notes=entry.notes,
        source_refs=tuple(entry.source_refs),
        source_evidence=tuple(entry.source_evidence),
        data_gap_ids=tuple(entry.data_gap_ids),
        # Missing policy metadata is fail-safe.  Never turn an unresolved gap
        # into a placeable repair merely because an older entry omitted the
        # policy carrier.
        data_gap_policies={
            gap_id: source_policies.get(gap_id, "ineligible")
            for gap_id in entry.data_gap_ids
        },
        gender_ok_unverified="gender_ok_unverified" in entry.constraint_flags,
        assumptions=tuple(entry.assumptions),
        override_ids=tuple(entry.override_ids),
        depends_on=tuple(entry.depends_on),
    )


def _propose_replacement(entry: ScheduleEntry, task: Task, ctx: ScheduleContext, *,
                         exclude: set[str], trigger_event_id: str | None,
                         context: str) -> AuditItem:
    # exclusivity/pins must not block re-assignment of a *non-exclusive* task
    candidates = rank_candidates(eligible_workers(task, ctx, exclude=exclude), task, ctx)
    is_duty = PRIORITY_TIER[task.service_code] == 1
    if candidates:
        best = candidates[0]
        suggestion = ctx.add_entry(entry_from_task(
            task, best, ctx, source=EntrySource.SYSTEM_REASSIGNED,
            status=EntryStatus.NEEDS_REVIEW,
            explanation=f"{context}；建議 {best.display_name} 代更"
                        f"（{ranking_explanation(best, task, ctx)}）",
            id_prefix="sub"))
        suggestion.superseded_by = None
        entry.superseded_by = suggestion.id
        return make_audit(
            kind=AuditKind.REPLACEMENT_SUGGESTION, severity=Severity.WARNING,
            blocking=False,
            reason=f"{context}：{task.service_code.value}:"
                   f"{task.elder_name or task.center or task.route or ''} "
                   f"建議由 {best.display_name} 代更",
            reasons=[ManualReviewReason(
                code=ReviewReasonCode.REPLACEMENT_PROPOSED,
                message=ranking_explanation(best, task, ctx),
                rule_ref="RB-LEAVE-02")],
            original_entry=entry, suggested_entry=suggestion,
            alternatives=[entry_from_task(
                task, alt, ctx, source=EntrySource.SYSTEM_REASSIGNED,
                status=EntryStatus.NEEDS_REVIEW,
                explanation=ranking_explanation(alt, task, ctx), id_prefix="alt")
                for alt in candidates[1:3]],
            trigger_event_id=trigger_event_id)

    task = task_with_candidate_uncertainty(task, ctx)
    entry.data_gap_ids = sorted({*entry.data_gap_ids, *task.data_gap_ids})
    entry.data_gap_policies.update(task.data_gap_policies)
    entry.source_evidence = merge_source_evidence(
        entry.source_evidence, task.source_evidence
    )
    entry.source_refs = sorted({*entry.source_refs, *task.source_refs})
    entry.override_ids = sorted({*entry.override_ids, *task.override_ids})
    entry.depends_on = sorted({*entry.depends_on, *task.depends_on})
    entry.constraint_flags = [
        flag for flag in entry.constraint_flags
        if flag not in {
            "gender_ok_unverified",
            "seed_skill_unverified",
            "route_qualification_unverified",
        }
    ]
    ctx.set_status(entry, EntryStatus.UNASSIGNED)
    diagnosis = _diagnose_unassignable(task, ctx)
    entry.review_reasons.extend(diagnosis)
    return make_audit(
        kind=AuditKind.DUTY_UNDER_COVERAGE if is_duty else AuditKind.UNASSIGNED_TASK,
        severity=Severity.HIGH, blocking=True,
        reason=f"{context}：{task.service_code.value}:"
               f"{task.elder_name or task.center or task.route or ''} 未能找到代更",
        reasons=diagnosis, original_entry=entry, trigger_event_id=trigger_event_id)


def _propose_refill(worker_id: str, cancelled: ScheduleEntry,
                    ctx: ScheduleContext, event: ChangeEvent) -> AuditItem | None:
    """Freed capacity -> duty gaps first (RB-DUTY-04); else idle-release info."""
    worker = ctx.employees.get(worker_id)
    if worker is None:
        return None
    on, period = cancelled.schedule_date, cancelled.period
    dates = week_dates(ctx.week_start)
    for req in ctx.dataset.duty_requirements:
        if dates[req.weekday - 1] != on or req.period != period:
            continue
        assigned = ctx.duty_assigned(req.center, on, period)
        if assigned >= req.required_count:
            continue
        unassigned = next((
            entry for entry in ctx.entries
            if entry.center == req.center
            and entry.schedule_date == on
            and entry.period == period
            and entry.status == EntryStatus.UNASSIGNED
            and entry.superseded_by is None
        ), None)
        if unassigned is None:
            continue
        for t in [_task_from_entry(unassigned, ctx)]:
            reasons = check_assignment(worker, t, ctx)
            if not reasons:
                ctx.set_status(unassigned, EntryStatus.AFFECTED)
                suggestion = ctx.add_entry(entry_from_task(
                    t, worker, ctx, source=EntrySource.SYSTEM_REASSIGNED,
                    status=EntryStatus.NEEDS_REVIEW,
                    explanation=f"{worker.display_name} 因取消而騰空，"
                                f"建議補入 {req.center} 當值（尚欠 "
                                f"{req.required_count - assigned} 人）",
                    id_prefix="refill"))
                unassigned.superseded_by = suggestion.id
                return make_audit(
                    kind=AuditKind.REFILL, severity=Severity.WARNING, blocking=False,
                    reason=f"{worker.display_name} 騰空，建議補 {req.center} 當值",
                    reasons=[ManualReviewReason(
                        code=ReviewReasonCode.WORKER_RELEASED,
                        message="服務取消釋放人手，優先補中心當值",
                        rule_ref="RB-DUTY-04")],
                    suggested_entry=suggestion, trigger_event_id=event.id)
    return make_audit(
        kind=AuditKind.REFILL, severity=Severity.INFO, blocking=False,
        reason=f"{worker.display_name} {on} {period.value} 騰空；"
               f"當值已足，暫無需補位",
        reasons=[ManualReviewReason(
            code=ReviewReasonCode.WORKER_RELEASED,
            message="釋放人手，無待補崗位", rule_ref="RB-DUTY-04")],
        trigger_event_id=event.id)


def _try_displacement_chain(task: Task, ctx: ScheduleContext,
                            event: ChangeEvent) -> AuditItem | None:
    """Depth-1 displacement: worker W takes the escort; W's displaced
    lower-priority work is re-covered by another worker."""
    escort_tier = PRIORITY_TIER[task.service_code]
    best_chain: tuple[int, list[ChainStep], list[ScheduleEntry]] | None = None

    for worker in ctx.dataset.employees:
        # would W be eligible if their period were free?
        reasons = check_assignment(worker, task, ctx, check_capacity=False)
        if reasons or not ctx.is_available(worker, task.task_date, task.period):
            continue
        current = ctx.entries_for_worker(worker.id, task.task_date, task.period)
        if not current:
            continue  # actually free — handled by the normal path
        if any(PRIORITY_TIER[e.service_code] <= escort_tier or
               _is_exclusive_entry(e, ctx) for e in current):
            continue  # only displace strictly lower-priority, non-exclusive work
        # every displaced entry needs a replacement
        steps: list[ChainStep] = []
        replacements: list[ScheduleEntry] = []
        feasible = True
        for i, disp in enumerate(current):
            dtask = _task_from_entry(disp, ctx)
            cands = rank_candidates(
                eligible_workers(dtask, ctx, exclude={worker.id}), dtask, ctx)
            if not cands:
                feasible = False
                break
            repl = entry_from_task(
                dtask, cands[0], ctx, source=EntrySource.SYSTEM_REASSIGNED,
                status=EntryStatus.NEEDS_REVIEW,
                explanation=f"連鎖調動：{cands[0].display_name} 接手 "
                            f"{disp.worker_name} 原有的 {disp.service_code.value}",
                id_prefix="chain")
            replacements.append(repl)
            steps.append(ChainStep(
                step=i + 2, action="reassign", entry_before=disp, entry_after=repl,
                explanation=f"{disp.service_code.value}:{disp.elder_name or ''} "
                            f"改由 {cands[0].display_name} 負責"))
        if not feasible:
            continue
        disturbance = len(steps)
        if best_chain is None or disturbance < best_chain[0]:
            escort_entry = entry_from_task(
                task, worker, ctx, source=EntrySource.SYSTEM_REASSIGNED,
                status=EntryStatus.NEEDS_REVIEW,
                explanation=f"連鎖調動：{worker.display_name} 抽調做護送",
                id_prefix="chain")
            head = ChainStep(step=1, action="assign", entry_after=escort_entry,
                             explanation=f"{worker.display_name} 抽調做護送 "
                                         f"{task.elder_name}")
            best_chain = (disturbance, [head] + steps, [escort_entry] + replacements)

    if best_chain is None:
        return None
    _, steps, new_entries = best_chain
    displaced_ids = [s.entry_before.id for s in steps if s.entry_before]
    # tentatively occupy: mark displaced as affected, add proposals
    for s in steps:
        if s.entry_before is not None:
            original = next(e for e in ctx.entries if e.id == s.entry_before.id)
            ctx.set_status(original, EntryStatus.AFFECTED)
            original.superseded_by = s.entry_after.id
    for e in new_entries:
        ctx.add_entry(e)
    return make_audit(
        kind=AuditKind.DISPLACEMENT_CHAIN, severity=Severity.HIGH, blocking=True,
        reason=f"新增護送需連鎖調動（影響 {len(displaced_ids)} 項原有安排）",
        reasons=[ManualReviewReason(
            code=ReviewReasonCode.DISPLACEMENT_REQUIRED,
            message="無空閒合資格同工，需抽調並補位（整組批核）",
            rule_ref="RB-ESC-03")],
        chain=steps, suggested_entry=new_entries[0],
        trigger_event_id=event.id)


def _report_for(event: ChangeEvent, audits: list[AuditItem]) -> ImpactReport:
    severity_order = {Severity.INFO: 0, Severity.WARNING: 1, Severity.HIGH: 2}
    top = max((a.severity for a in audits), key=lambda s: severity_order[s],
              default=Severity.INFO)
    impacts = []
    for a in audits:
        touched = [e for e in (a.original_entry, a.suggested_entry) if e]
        impacts.append(ImpactItem(
            id=f"impact-{a.id}",
            severity=a.severity,
            title=a.kind.value,
            description=a.reason,
            requires_review=a.blocking or a.severity != Severity.INFO,
            affected_entry_ids=[e.id for e in touched],
            affected_worker_ids=sorted({e.worker_id for e in touched if e.worker_id}),
            affected_elder_ids=sorted({e.elder_id for e in touched if e.elder_id}),
            suggested_entry_ids=[a.suggested_entry.id] if a.suggested_entry else [],
        ))
    return ImpactReport(
        event=event,
        risk_level=top,
        requires_review=any(a.blocking for a in audits)
                        or any(a.severity != Severity.INFO for a in audits),
        summary=f"{event.type.value}: {len(audits)} 項影響"
                f"（{sum(1 for a in audits if a.blocking)} 項需審批）",
        impacts=impacts,
        audit_item_ids=[a.id for a in audits],
    )
