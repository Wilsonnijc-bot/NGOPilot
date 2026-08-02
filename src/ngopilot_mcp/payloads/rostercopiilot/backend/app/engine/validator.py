"""Shared hard-constraint validator.

Re-checks a finished roster from scratch (independent bookkeeping), so a bug
in scheduler/repair occupancy cannot hide a violation. Any accepted roster
must validate to an empty list — tests and the benchmark enforce this.
"""
from __future__ import annotations

from datetime import date

from ..domain import (
    EntryStatus,
    GenderRequirement,
    HardViolation,
    MockDataset,
    ReviewReasonCode,
    ScheduleEntry,
    ServiceCode,
    SKILL_GATED,
)
from .context import saturday_team_for

ACTIVE = {EntryStatus.SCHEDULED, EntryStatus.NEEDS_REVIEW}


def validate_entries(
    dataset: MockDataset,
    entries: list[ScheduleEntry],
    leaves: set[tuple[str, date, str]],
    forbidden_slots: set[tuple[str, date, str]] | None = None,
) -> list[HardViolation]:
    employees = dataset.employee_map()
    elders = dataset.elder_map()
    fixed = {fs.id: fs for fs in dataset.fixed_services}
    escorts = dataset.escort_map()
    forbidden = set(forbidden_slots or set())
    for row in dataset.unavailable_slots:
        if row.is_available or row.reason != "manual_override" or row.available_date is None:
            continue
        periods = [row.period.value] if row.period else ["AM", "PM"]
        for period in periods:
            forbidden.add((row.worker_id, row.available_date, period))
    violations: list[HardViolation] = []
    slots: dict[tuple[str, date, str], list[ScheduleEntry]] = {}

    for e in entries:
        if e.status not in ACTIVE or not e.worker_id:
            continue
        if "supervisor_hard_bypass" in e.constraint_flags:
            continue
        worker = employees.get(e.worker_id)
        if worker is None:
            violations.append(HardViolation(
                entry_id=e.id, code=ReviewReasonCode.NO_QUALIFIED_WORKER,
                message=f"unknown worker {e.worker_id}"))
            continue

        unresolved_evidence = any(
            item.confidence in {"low", "seed"} for item in e.source_evidence
        )
        if e.status == EntryStatus.SCHEDULED and (
            e.data_gap_ids
            or unresolved_evidence
            or "gender_ok_unverified" in e.constraint_flags
            or "seed_skill_unverified" in e.constraint_flags
        ):
            violations.append(HardViolation(
                entry_id=e.id,
                code=(ReviewReasonCode.GENDER_UNKNOWN
                      if "gender_ok_unverified" in e.constraint_flags
                      else ReviewReasonCode.NO_QUALIFIED_WORKER),
                message="ordinary scheduled entry uses unresolved uncertainty",
            ))

        # skill (MEAL universal)
        if e.service_code in SKILL_GATED and e.service_code not in worker.skills:
            violations.append(HardViolation(
                entry_id=e.id, code=ReviewReasonCode.SKILL_MISMATCH,
                message=f"{worker.display_name} lacks skill {e.service_code.value}"))

        # gender: resolve requirement the same way the scheduler does
        req = _gender_requirement(e, elders, dataset)
        if req == GenderRequirement.UNKNOWN:
            if worker.gender is None or not _allows_unverified_gender_review(e):
                violations.append(HardViolation(
                    entry_id=e.id, code=ReviewReasonCode.GENDER_UNKNOWN,
                    message="gender requirement unverifiable"))
        elif req in (GenderRequirement.MALE, GenderRequirement.FEMALE):
            if worker.gender is None:
                violations.append(HardViolation(
                    entry_id=e.id, code=ReviewReasonCode.GENDER_UNKNOWN,
                    message=f"{worker.display_name} gender is unknown"))
            elif worker.gender.value != req.value:
                violations.append(HardViolation(
                    entry_id=e.id, code=ReviewReasonCode.GENDER_MISMATCH,
                    message=f"{worker.display_name} does not satisfy gender "
                            f"requirement {req.value}"))

        # exclusivity
        origin = fixed.get(e.origin_fixed_service_id or "")
        if origin and origin.is_exclusive and origin.assigned_worker_id \
                and e.worker_id != origin.assigned_worker_id:
            violations.append(HardViolation(
                entry_id=e.id, code=ReviewReasonCode.EXCLUSIVE_BINDING,
                message=f"exclusive service assigned to {worker.display_name} "
                        f"instead of {origin.assigned_worker_id}"))

        escort = escorts.get(e.origin_escort_request_id or "")
        if (
            escort
            and escort.preference_strength == "must"
            and escort.preferred_worker_id
            and e.worker_id != escort.preferred_worker_id
        ):
            violations.append(HardViolation(
                entry_id=e.id, code=ReviewReasonCode.PREFERENCE_UNMET,
                message=f"must-preference escort assigned to {worker.display_name} "
                        f"instead of {escort.preferred_worker_id}"))

        # availability: leave + Saturday team
        if (e.worker_id, e.schedule_date, e.period.value) in leaves:
            violations.append(HardViolation(
                entry_id=e.id, code=ReviewReasonCode.WORKER_ON_LEAVE,
                message=f"{worker.display_name} scheduled while on leave"))
        if (e.worker_id, e.schedule_date, e.period.value) in forbidden:
            violations.append(HardViolation(
                entry_id=e.id, code=ReviewReasonCode.FORBIDDEN_ASSIGNMENT,
                message=f"{worker.display_name} scheduled in a forbidden slot"))
        wd = e.schedule_date.isoweekday()
        if wd == 6 and worker.saturday_team != saturday_team_for(e.schedule_date):
            violations.append(HardViolation(
                entry_id=e.id, code=ReviewReasonCode.NOT_WORKING_DAY,
                message=f"{worker.display_name} not on duty this Saturday"))
        if wd == 7:
            violations.append(HardViolation(
                entry_id=e.id, code=ReviewReasonCode.NOT_WORKING_DAY,
                message="Sunday scheduling is not allowed"))

        slots.setdefault((e.worker_id, e.schedule_date, e.period.value), []).append(e)

    # time conflicts: per (worker, date, period) — a full-period entry excludes
    # everything else; session entries must not collide on the same session.
    for (worker_id, on, period), slot_entries in slots.items():
        full = [e for e in slot_entries if e.session_index is None]
        if full and len(slot_entries) > 1:
            for e in slot_entries:
                violations.append(HardViolation(
                    entry_id=e.id, code=ReviewReasonCode.TIME_CONFLICT,
                    message=f"{worker_id} {on} {period}: full-period task "
                            f"overlaps other work"))
            continue
        seen: dict[int, ScheduleEntry] = {}
        reported: set[str] = set()
        for e in slot_entries:
            s = e.session_index or 1
            if s in seen:
                other = seen[s]
                for conflict in (other, e):
                    if conflict.id in reported:
                        continue
                    reported.add(conflict.id)
                    violations.append(HardViolation(
                        entry_id=conflict.id, code=ReviewReasonCode.TIME_CONFLICT,
                        message=f"{worker_id} {on} {period} session {s}: "
                                f"double-booked"))
            else:
                seen[s] = e
    return violations


def _allows_unverified_gender_review(e: ScheduleEntry) -> bool:
    if e.status != EntryStatus.NEEDS_REVIEW:
        return False
    if "gender_ok_unverified" in e.constraint_flags and e.data_gap_ids:
        return True
    return any(r.code == ReviewReasonCode.GENDER_UNKNOWN for r in e.review_reasons)


def _gender_requirement(e: ScheduleEntry, elders, dataset: MockDataset) -> GenderRequirement:
    from ..domain import GENDER_SENSITIVE
    elder = elders.get(e.elder_id or "")
    if e.service_code == ServiceCode.ESCORT:
        # re-derive from the origin escort request when available
        req = dataset.escort_map().get(e.origin_escort_request_id or "")
        return req.gender_requirement if req else GenderRequirement.ANY
    if e.service_code in GENDER_SENSITIVE:
        if elder is not None and elder.gender_requirement != GenderRequirement.ANY:
            return elder.gender_requirement
        if elder is None or elder.gender is None:
            return GenderRequirement.UNKNOWN
        return GenderRequirement(elder.gender.value)
    return GenderRequirement.ANY
