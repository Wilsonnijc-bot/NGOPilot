"""Baseline weekly scheduler — transparent greedy passes, no black box.

Pass order mirrors the NGO's own workflow (rulebook RB-PRIO-01):
1. fixed template services (they are pre-committed appointments),
2. escort requests (time-fixed, scarce-qualified, whole half-day),
3. centre-duty fill from remaining free capacity (the absorber).

Every placement carries an explanation; every problem becomes an AuditItem —
nothing fails silently (RB-DATA-01).

Phase 1 scheduler bridge work should lower ``SchedulerSnapshot`` into the
engine's task/domain structures. Excel workbooks stay upstream fixture/evidence
inputs, not direct scheduler dependencies.
"""
from __future__ import annotations

import time as _time
import uuid
from datetime import datetime, timezone

from ..domain import (
    AuditItem,
    AuditKind,
    EntrySource,
    EntryStatus,
    ManualReviewReason,
    MockDataset,
    ReviewReasonCode,
    ScheduleEntry,
    ScheduleVersion,
    Severity,
    VersionKind,
)
from .builders import entry_from_task, make_audit, task_with_candidate_uncertainty
from .context import ScheduleContext, week_dates
from .eligibility import check_assignment, eligible_workers
from .metrics import compute_metrics
from .ranking import rank_candidates, ranking_explanation
from .tasks import Task, duty_tasks, task_from_escort, task_from_fixed
from .validator import validate_entries


def new_version_id() -> str:
    return f"v-{uuid.uuid4().hex[:10]}"


def build_baseline(dataset: MockDataset) -> ScheduleVersion:
    started = _time.perf_counter()
    ctx = ScheduleContext(dataset)
    audits: list[AuditItem] = []

    _place_fixed_services(ctx, audits)
    _place_escorts(ctx, audits)
    _fill_center_duty(ctx, audits)

    version = ScheduleVersion(
        id=new_version_id(),
        kind=VersionKind.BASELINE,
        created_at=datetime.now(timezone.utc),
        week_start=dataset.params.week_start,
        entries=ctx.entries,
        audit_items=audits,
        unassigned=[e for e in ctx.entries if e.status == EntryStatus.UNASSIGNED],
    )
    version.summary = compute_metrics(
        dataset, version, leaves=ctx.leaves,
        runtime_ms=(_time.perf_counter() - started) * 1000,
    )
    return version


# --------------------------------------------------------------------------
# Pass 1: fixed template services
# --------------------------------------------------------------------------

def _place_fixed_services(ctx: ScheduleContext, audits: list[AuditItem]) -> None:
    dates = week_dates(ctx.week_start)
    occurrences: list[Task] = []
    for fs in ctx.dataset.fixed_services:
        on = dates[fs.weekday - 1]
        if not fs.week_pattern.matches(on):
            continue
        elder = ctx.elders.get(fs.elder_id) if fs.elder_id else None
        if elder and elder.status != "active":
            continue  # suspended (e.g. hospitalised before the solve)
        occurrences.append(task_from_fixed(fs, on, elder))

    occurrences.sort(key=lambda t: (t.priority_tier, t.task_date, t.period.value,
                                    t.session_index or 0, t.key))
    # Pass A: honour every healthy template commitment first, so fallback
    # replacements (pass B) can only use genuinely free capacity and never
    # steal a slot a later template entry depends on.
    problems: list[tuple[Task, object, list[ManualReviewReason]]] = []
    for task in occurrences:
        worker = ctx.employees.get(task.pinned_worker_id or "")
        if worker is not None:
            reasons = check_assignment(worker, task, ctx)
            if not reasons:
                ctx.add_entry(entry_from_task(
                    task, worker, ctx,
                    source=EntrySource.TEMPLATE, status=EntryStatus.SCHEDULED,
                    explanation=f"固定安排：{worker.display_name} 一向跟開此個案",
                ))
                continue
            problems.append((task, worker, reasons))
        else:
            problems.append((task, None, []))

    # Pass B: resolve template problems against the settled roster.
    for task, worker, reasons in problems:
        if worker is not None:
            _handle_ineligible_template(task, worker, reasons, ctx, audits)
        else:
            _handle_missing_template_worker(task, ctx, audits)


def _handle_ineligible_template(task: Task, worker, reasons: list[ManualReviewReason],
                                ctx: ScheduleContext, audits: list[AuditItem]) -> None:
    if task.is_exclusive:
        # Exclusive service cannot be substituted — propose cancellation
        # (RB-EXCL-02); blocking human review.
        entry = ctx.add_entry(entry_from_task(
            task, worker, ctx, source=EntrySource.TEMPLATE,
            status=EntryStatus.CANCELLED,
            explanation="專屬服務：指定同工不可用，按規則建議取消（待人工確認）",
            reasons=reasons,
        ))
        audits.append(make_audit(
            kind=AuditKind.EXCLUSIVE_CANCELLATION, severity=Severity.HIGH,
            blocking=True,
            reason=f"{task.elder_name or ''} 的專屬服務（{task.service_code.value}）"
                   f"因 {worker.display_name} 不可用而建議取消",
            reasons=reasons + [ManualReviewReason(
                code=ReviewReasonCode.EXCLUSIVE_WORKER_ABSENT,
                message="專屬同工不可用，服務不設代更",
                rule_ref="RB-EXCL-02")],
            original_entry=entry,
        ))
        return
    _assign_with_fallback(
        task, ctx, audits,
        exclude={worker.id},
        template_reasons=reasons,
        audit_kind=AuditKind.TEMPLATE_ISSUE,
        context_note=f"模板同工 {worker.display_name} 不合資格/不可用",
    )


def _handle_missing_template_worker(task: Task, ctx: ScheduleContext,
                                    audits: list[AuditItem]) -> None:
    _assign_with_fallback(
        task, ctx, audits, exclude=set(),
        template_reasons=[ManualReviewReason(
            code=ReviewReasonCode.TEMPLATE_WORKER_INELIGIBLE,
            message="模板沒有指定同工", rule_ref="RB-FIX-01")],
        audit_kind=AuditKind.TEMPLATE_ISSUE,
        context_note="模板沒有指定同工",
    )


def _assign_with_fallback(task: Task, ctx: ScheduleContext,
                          audits: list[AuditItem], *, exclude: set[str],
                          template_reasons: list[ManualReviewReason],
                          audit_kind: AuditKind, context_note: str) -> None:
    candidates = rank_candidates(eligible_workers(task, ctx, exclude=exclude), task, ctx)
    task = task_with_candidate_uncertainty(task, ctx)
    if candidates:
        best = candidates[0]
        entry = ctx.add_entry(entry_from_task(
            task, best, ctx, source=EntrySource.SYSTEM_REASSIGNED,
            status=EntryStatus.NEEDS_REVIEW,
            explanation=f"{context_note}；建議改派 {best.display_name}"
                        f"（{ranking_explanation(best, task, ctx)}）",
            reasons=template_reasons,
        ))
        alternatives = [
            entry_from_task(task, alt, ctx, source=EntrySource.SYSTEM_REASSIGNED,
                            status=EntryStatus.NEEDS_REVIEW,
                            explanation=ranking_explanation(alt, task, ctx),
                            id_prefix="alt")
            for alt in candidates[1:3]
        ]
        audits.append(make_audit(
            kind=audit_kind, severity=Severity.WARNING, blocking=False,
            reason=f"{context_note}；建議 {best.display_name} 接手 "
                   f"{task.service_code.value}:{task.elder_name or task.route or ''}",
            reasons=template_reasons, suggested_entry=entry,
            alternatives=alternatives,
        ))
    else:
        task = task_with_candidate_uncertainty(task, ctx)
        entry = ctx.add_entry(entry_from_task(
            task, None, ctx, source=EntrySource.SYSTEM_REASSIGNED,
            status=EntryStatus.UNASSIGNED,
            explanation=f"{context_note}；找不到符合所有硬性條件的同工",
            reasons=template_reasons + [ManualReviewReason(
                code=ReviewReasonCode.NO_QUALIFIED_WORKER,
                message="沒有同時滿足技能／性別／時間的可用同工",
                rule_ref="RB-DATA-01")],
        ))
        audits.append(make_audit(
            kind=AuditKind.UNASSIGNED_TASK, severity=Severity.HIGH, blocking=True,
            reason=f"{task.service_code.value}:{task.elder_name or task.route or ''} "
                   f"未能分配（{context_note}）",
            reasons=entry.review_reasons, original_entry=entry,
        ))


# --------------------------------------------------------------------------
# Pass 2: escorts
# --------------------------------------------------------------------------

def _place_escorts(ctx: ScheduleContext, audits: list[AuditItem]) -> None:
    dates = set(week_dates(ctx.week_start))
    requests = [r for r in ctx.dataset.escort_requests
                if r.service_date in dates and r.status == "requested"]
    requests.sort(key=lambda r: (r.service_date, r.period.value,
                                 r.appointment_time or _MIDNIGHT, r.id))
    for req in requests:
        elder = ctx.elders.get(req.elder_id)
        if elder and elder.status != "active":
            continue
        task = task_from_escort(req, elder)
        candidates = rank_candidates(eligible_workers(task, ctx), task, ctx)
        if candidates:
            best = candidates[0]
            pref_note = ""
            if task.preferred_worker_id and best.id != task.preferred_worker_id:
                pref_note = "（未能滿足個案建議同工，已按條件排最合適人選）"
            ctx.add_entry(entry_from_task(
                task, best, ctx, source=EntrySource.WEEKLY_FILL,
                status=EntryStatus.SCHEDULED,
                explanation=f"護送：{ranking_explanation(best, task, ctx)}{pref_note}",
                id_prefix="escort",
            ))
            if pref_note and task.preference_strength == "prefer":
                audits.append(make_audit(
                    kind=AuditKind.ESCORT_ADJUSTMENT, severity=Severity.INFO,
                    blocking=False,
                    reason=f"{task.elder_name} 護送建議同工不可用，已改派 {best.display_name}",
                    reasons=[ManualReviewReason(
                        code=ReviewReasonCode.PREFERENCE_UNMET,
                        message="建議同工不可用（非硬性）", rule_ref="RB-ESC-07")],
                ))
            continue
        # No eligible worker — diagnose why (explainability requirement).
        task = task_with_candidate_uncertainty(task, ctx)
        diagnosis = _diagnose_unassignable(task, ctx)
        entry = ctx.add_entry(entry_from_task(
            task, None, ctx, source=EntrySource.WEEKLY_FILL,
            status=EntryStatus.UNASSIGNED,
            explanation="護送未能分配：" + "；".join(r.message for r in diagnosis[:3]),
            reasons=diagnosis, id_prefix="escort",
        ))
        audits.append(make_audit(
            kind=AuditKind.UNASSIGNED_TASK,
            severity=Severity.HIGH, blocking=True,
            reason=f"{task.task_date} {task.period.value} {task.elder_name} 護送未能分配",
            reasons=diagnosis, original_entry=entry,
        ))


_MIDNIGHT = __import__("datetime").time(0, 0)


def _diagnose_unassignable(task: Task, ctx: ScheduleContext) -> list[ManualReviewReason]:
    """Aggregate the binding reasons across all workers (why nobody fits)."""
    tally: dict[ReviewReasonCode, int] = {}
    sample: dict[ReviewReasonCode, ManualReviewReason] = {}
    for worker in ctx.dataset.employees:
        for reason in check_assignment(worker, task, ctx):
            tally[reason.code] = tally.get(reason.code, 0) + 1
            sample.setdefault(reason.code, reason)
    out = []
    for code, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        r = sample[code]
        out.append(ManualReviewReason(
            code=code, message=f"{r.message}（{n} 位同工受此限）",
            params=r.params, rule_ref=r.rule_ref))
    if not out:
        out.append(ManualReviewReason(
            code=ReviewReasonCode.NO_QUALIFIED_WORKER,
            message="沒有可用同工", rule_ref="RB-DATA-01"))
    return out


# --------------------------------------------------------------------------
# Pass 3: centre duty fill
# --------------------------------------------------------------------------

def _fill_center_duty(ctx: ScheduleContext, audits: list[AuditItem]) -> None:
    tasks: list[Task] = []
    for req in ctx.dataset.duty_requirements:
        tasks.extend(duty_tasks(req, ctx.week_start))
    tasks.sort(key=lambda t: (t.task_date, t.period.value, t.center or "", t.priority))
    for task in tasks:
        # duty may take either free session; try session 1 then 2
        placed = False
        for session in (1, 2):
            trial = Task(**{**task.__dict__, "session_index": session,
                            "key": f"{task.key}:s{session}"})
            candidates = rank_candidates(eligible_workers(trial, ctx), trial, ctx)
            if candidates:
                best = candidates[0]
                ctx.add_entry(entry_from_task(
                    trial, best, ctx, source=EntrySource.WEEKLY_FILL,
                    status=EntryStatus.SCHEDULED,
                    explanation=f"中心當值：{ranking_explanation(best, trial, ctx)}",
                    id_prefix="duty",
                ))
                placed = True
                break
        if placed:
            continue
        task = task_with_candidate_uncertainty(task, ctx)
        entry = ctx.add_entry(entry_from_task(
            task, None, ctx, source=EntrySource.WEEKLY_FILL,
            status=EntryStatus.UNASSIGNED,
            explanation=f"{task.center} 當值未能補足（無合資格且有空檔的同工）",
            reasons=[ManualReviewReason(
                code=ReviewReasonCode.DUTY_SHORTFALL,
                message=f"{task.center} {task.task_date} {task.period.value} 當值人手不足",
                rule_ref="RB-DUTY-01")],
            id_prefix="duty",
        ))
        audits.append(make_audit(
            kind=AuditKind.DUTY_UNDER_COVERAGE, severity=Severity.HIGH, blocking=True,
            reason=f"{task.task_date} {task.period.value} {task.center} 中心當值人手不足",
            reasons=entry.review_reasons, original_entry=entry,
        ))
