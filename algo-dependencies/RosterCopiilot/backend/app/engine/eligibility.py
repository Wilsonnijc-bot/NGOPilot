"""Hard-constraint eligibility checks (the shared gate).

``check_assignment`` is the single source of truth for "may worker W take
task T": used by the baseline scheduler, the repair engine, the validator and
the audit-decision editor. An empty result means eligible.

Hard rules (rulebook): RB-SKILL-01/02, RB-GEND-01/02, RB-EXCL-01/03,
RB-TIME-01, RB-LEAVE-01, RB-CAP-01. Never silently relaxed.
"""
from __future__ import annotations

from ..domain import (
    Employee,
    GenderRequirement,
    ManualReviewReason,
    ReviewReasonCode,
    ServiceCode,
    SKILL_GATED,
)
from .context import ScheduleContext
from .tasks import Task


def check_assignment(worker: Employee, task: Task, ctx: ScheduleContext,
                     *, check_capacity: bool = True) -> list[ManualReviewReason]:
    reasons: list[ManualReviewReason] = []

    ineligible_gaps = sorted(
        gap_id for gap_id, policy in task.data_gap_policies.items()
        if policy == "ineligible"
    )
    if ineligible_gaps:
        reasons.append(ManualReviewReason(
            code=ReviewReasonCode.NO_QUALIFIED_WORKER,
            message="需求含有未解決資料缺口，按政策不可自動分配",
            params={"data_gap_ids": ",".join(ineligible_gaps)},
            rule_ref="RB-DATA-01",
        ))

    if task.service_code == ServiceCode.MEAL and task.route:
        route_gap_id = worker.route_gap_ids.get(task.route)
        if (
            route_gap_id
            and worker.data_gap_policies.get(route_gap_id) == "ineligible"
        ):
            reasons.append(ManualReviewReason(
                code=ReviewReasonCode.ROUTE_UNQUALIFIED,
                message=(f"{worker.display_name} 的送飯路線 {task.route} 資格"
                         "明確不符或資料互相矛盾"),
                params={"worker_id": worker.id, "route": task.route},
                rule_ref="RB-SKILL-03",
            ))

    # -- skill (MEAL is universal, RB-SKILL-02) ----------------------------
    if task.service_code in SKILL_GATED and not worker.has_skill(task.service_code):
        reasons.append(ManualReviewReason(
            code=ReviewReasonCode.SKILL_MISMATCH,
            message=f"{worker.display_name} 沒有 {task.service_code.value} 技能",
            params={"worker_id": worker.id, "service": task.service_code.value},
            rule_ref="RB-SKILL-01",
        ))

    # -- gender (fail-safe on unknown, RB-GEND-01/02) -----------------------
    req = task.gender_requirement
    if req == GenderRequirement.UNKNOWN:
        if not task.gender_ok_unverified or worker.gender is None:
            reasons.append(ManualReviewReason(
                code=ReviewReasonCode.GENDER_UNKNOWN,
                message="性別要求無法核實（長者或同工性別資料缺失）",
                params={"elder_id": task.elder_id or "", "worker_id": worker.id},
                rule_ref="RB-GEND-01",
            ))
    elif req in (GenderRequirement.MALE, GenderRequirement.FEMALE):
        if worker.gender is None:
            reasons.append(ManualReviewReason(
                code=ReviewReasonCode.GENDER_UNKNOWN,
                message=f"{worker.display_name} 性別資料缺失，無法核實性別要求",
                params={"worker_id": worker.id},
                rule_ref="RB-GEND-01",
            ))
        elif worker.gender.value != req.value:
            reasons.append(ManualReviewReason(
                code=ReviewReasonCode.GENDER_MISMATCH,
                message=f"服務要求{ '男' if req == GenderRequirement.MALE else '女' }性同工，"
                        f"{worker.display_name} 不符",
                params={"worker_id": worker.id, "required": req.value},
                rule_ref="RB-GEND-01",
            ))

    # -- exclusivity (RB-EXCL-01) -------------------------------------------
    if task.is_exclusive and task.pinned_worker_id and worker.id != task.pinned_worker_id:
        reasons.append(ManualReviewReason(
            code=ReviewReasonCode.EXCLUSIVE_BINDING,
            message="專屬服務只可由指定同工提供，不可代更",
            params={"required_worker_id": task.pinned_worker_id},
            rule_ref="RB-EXCL-01",
        ))

    # -- must-preference behaves like a binding (RB-EXCL-03) ----------------
    if (task.preference_strength == "must" and task.preferred_worker_id
            and worker.id != task.preferred_worker_id):
        reasons.append(ManualReviewReason(
            code=ReviewReasonCode.PREFERENCE_UNMET,
            message="個案指明只接受特定同工（『只要…』），不可代更",
            params={"required_worker_id": task.preferred_worker_id},
            rule_ref="RB-EXCL-03",
        ))

    # -- availability (RB-LEAVE-01 / RB-TIME-03) ----------------------------
    if not ctx.is_working_day(worker, task.task_date):
        reasons.append(ManualReviewReason(
            code=ReviewReasonCode.NOT_WORKING_DAY,
            message=f"{worker.display_name} 當日不上班（星期六 A/B 更）",
            params={"worker_id": worker.id, "date": task.task_date.isoformat()},
            rule_ref="RB-TIME-03",
        ))
    elif ctx.on_leave(worker.id, task.task_date, task.period):
        reasons.append(ManualReviewReason(
            code=ReviewReasonCode.WORKER_ON_LEAVE,
            message=f"{worker.display_name} 當時段已請假",
            params={"worker_id": worker.id, "date": task.task_date.isoformat(),
                    "period": task.period.value},
            rule_ref="RB-LEAVE-01",
        ))
    if ctx.is_forbidden(worker.id, task.task_date, task.period):
        reasons.append(ManualReviewReason(
            code=ReviewReasonCode.FORBIDDEN_ASSIGNMENT,
            message=f"{worker.display_name} 該時段有人工容量鎖（不可加Case）",
            params={"worker_id": worker.id, "date": task.task_date.isoformat(),
                    "period": task.period.value},
            rule_ref="RB-CAP-01",
        ))

    # -- time conflict (RB-TIME-01) ------------------------------------------
    if check_capacity and not ctx.can_place(worker.id, task.task_date, task.period,
                                            task.session_index):
        reasons.append(ManualReviewReason(
            code=ReviewReasonCode.TIME_CONFLICT,
            message=f"{worker.display_name} 該時段已有其他工作",
            params={"worker_id": worker.id, "date": task.task_date.isoformat(),
                    "period": task.period.value},
            rule_ref="RB-TIME-01",
        ))

    return reasons


def eligible_workers(task: Task, ctx: ScheduleContext,
                     *, exclude: set[str] | None = None) -> list[Employee]:
    """All workers passing every hard gate for this task."""
    out = []
    for worker in ctx.dataset.employees:
        if exclude and worker.id in exclude:
            continue
        if not check_assignment(worker, task, ctx):
            out.append(worker)
    return out
