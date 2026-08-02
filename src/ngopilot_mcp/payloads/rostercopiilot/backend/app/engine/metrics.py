"""Roster quality metrics (docs/evaluation/evaluation_metrics.md)."""
from __future__ import annotations

from datetime import date
from statistics import mean, pstdev

from ..domain import (
    AuditStatus,
    EntryStatus,
    MockDataset,
    PRIORITY_TIER,
    ScheduleVersion,
    ServiceCode,
)
from .context import week_dates
from .validator import validate_entries

DEMAND_STATUSES = {EntryStatus.SCHEDULED, EntryStatus.NEEDS_REVIEW,
                   EntryStatus.UNASSIGNED, EntryStatus.AFFECTED}
ASSIGNED_STATUSES = {EntryStatus.SCHEDULED, EntryStatus.NEEDS_REVIEW}


def compute_metrics(dataset: MockDataset, version: ScheduleVersion, *,
                    leaves: set[tuple[str, date, str]],
                    runtime_ms: float,
                    parent: ScheduleVersion | None = None) -> dict[str, float]:
    entries = version.entries
    demand = [e for e in entries if e.status in DEMAND_STATUSES]
    assigned = [e for e in entries if e.status in ASSIGNED_STATUSES and e.worker_id]
    unassigned = [e for e in entries if e.status == EntryStatus.UNASSIGNED]

    # escort fulfilment
    escort_demand = [e for e in demand if e.service_code == ServiceCode.ESCORT]
    escort_ok = [e for e in escort_demand if e.status in ASSIGNED_STATUSES]

    # duty coverage vs requirements
    dates = week_dates(version.week_start)
    slots_below = 0
    duty_slots = 0
    for req in dataset.duty_requirements:
        on = dates[req.weekday - 1]
        got = sum(
            1 for e in assigned
            if e.service_code == req.service_code and e.schedule_date == on
            and e.period == req.period
        )
        duty_slots += 1
        if got < req.required_count:
            slots_below += 1

    # workload balance over active full-time workers
    loads = []
    per_worker: dict[str, int] = {}
    for e in assigned:
        per_worker[e.worker_id] = per_worker.get(e.worker_id, 0) + (
            2 if e.session_index is None else 1)
    for w in dataset.employees:
        if w.employment_type == "full":
            loads.append(per_worker.get(w.id, 0))
    balance = 1.0 - (pstdev(loads) / mean(loads)) if loads and mean(loads) > 0 else 0.0

    violations = validate_entries(dataset, entries, leaves)
    pending = [a for a in version.audit_items if a.status == AuditStatus.PENDING]

    metrics: dict[str, float] = {
        "total_entries": len(entries),
        "demand_tasks": len(demand),
        "coverage_rate": round(len([e for e in demand if e.status in ASSIGNED_STATUSES])
                               / len(demand), 4) if demand else 1.0,
        "unassigned_count": len(unassigned),
        "unassigned_duty": sum(1 for e in unassigned
                               if PRIORITY_TIER[e.service_code] == 1),
        "unassigned_escort": sum(1 for e in unassigned
                                 if e.service_code == ServiceCode.ESCORT),
        "escort_fulfillment_rate": round(len(escort_ok) / len(escort_demand), 4)
                                   if escort_demand else 1.0,
        "center_duty_slots_below_required": slots_below,
        "center_duty_slot_total": duty_slots,
        "workload_balance_score": round(balance, 4),
        "hard_constraint_violations": len(violations),
        "manual_review_total": len(pending),
        "manual_review_blocking": sum(1 for a in pending if a.blocking),
        "cancelled_count": sum(1 for e in entries
                               if e.status == EntryStatus.CANCELLED),
        "needs_review_entries": sum(1 for e in entries
                                    if e.status == EntryStatus.NEEDS_REVIEW),
        "runtime_ms": round(runtime_ms, 1),
    }
    if parent is not None:
        metrics["change_distance_from_original"] = change_distance(parent, version)
    return metrics


def change_distance(parent: ScheduleVersion, child: ScheduleVersion) -> int:
    """Entries added, removed, or altered (worker/status) vs the parent."""
    parent_map = {e.id: e for e in parent.entries}
    child_map = {e.id: e for e in child.entries}
    distance = 0
    for eid, e in child_map.items():
        p = parent_map.get(eid)
        if p is None:
            distance += 1  # new entry
        elif (p.worker_id, p.status) != (e.worker_id, e.status):
            distance += 1  # altered entry
    distance += sum(1 for eid in parent_map if eid not in child_map)
    return distance
