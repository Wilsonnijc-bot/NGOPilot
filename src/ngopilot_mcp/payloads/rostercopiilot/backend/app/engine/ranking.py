"""Deterministic, explainable candidate ranking (soft preferences).

The tuple order *is* the product behaviour (rescheduling_algorithm.md §0):
1. district/route match (less travel)     — RB-GEO-01
2. stated preference for this worker      — RB-ESC-07
3. lighter current workload               — RB-LOAD-01
4. centre affinity (duty tasks)           — RB-DUTY-03
5. duty-count fairness (duty tasks)       — RB-DUTY-02
6. stable id tie-break (determinism)
"""
from __future__ import annotations

from ..domain import Employee, SERVICE_CATEGORY, ServiceCategory, ServiceCode
from .context import ScheduleContext
from .tasks import Task


def rank_key(worker: Employee, task: Task, ctx: ScheduleContext) -> tuple:
    if task.service_code == ServiceCode.MEAL and task.route:
        route_match = 0 if task.route in worker.routes else 1
    else:
        route_match = 0 if (task.district and task.district in worker.routes) else 1
    uncertainty = int(
        task.service_code in worker.seed_skills
        or (
            task.service_code == ServiceCode.MEAL
            and bool(task.route)
            and (
                task.route not in worker.routes
                or task.route in worker.seed_routes
            )
        )
    )
    preferred = 0 if worker.id == task.preferred_worker_id else 1
    workload = ctx.workload(worker.id)
    is_duty = SERVICE_CATEGORY[task.service_code] == ServiceCategory.CENTER_DUTY
    affinity = 0 if (is_duty and worker.home_team == task.center) else 1
    fairness = ctx.duty_count(worker.id) if is_duty else 0
    return (route_match, uncertainty, preferred, workload, affinity, fairness, worker.id)


def rank_candidates(candidates: list[Employee], task: Task,
                    ctx: ScheduleContext) -> list[Employee]:
    return sorted(candidates, key=lambda w: rank_key(w, task, ctx))


def ranking_explanation(worker: Employee, task: Task, ctx: ScheduleContext) -> str:
    parts: list[str] = []
    if task.service_code == ServiceCode.MEAL and task.route in worker.routes:
        parts.append(f"熟悉{task.route}路線")
    elif task.district and task.district in worker.routes:
        parts.append(f"熟悉{task.district}路線")
    if worker.id == task.preferred_worker_id:
        parts.append("個案指定/建議同工")
    if SERVICE_CATEGORY[task.service_code] == ServiceCategory.CENTER_DUTY:
        if worker.home_team == task.center:
            parts.append(f"常駐{task.center}")
        parts.append(f"本週當值{ctx.duty_count(worker.id)}節（輪換平均）")
    parts.append(f"本週已排{ctx.workload(worker.id)}節")
    return "；".join(parts)
