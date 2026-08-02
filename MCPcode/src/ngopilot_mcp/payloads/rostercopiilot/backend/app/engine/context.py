"""Scheduling context: availability, occupancy and entry bookkeeping.

One ScheduleContext wraps one working copy of a roster. Both the baseline
scheduler and the repair engine mutate rosters exclusively through it, so
occupancy accounting stays consistent everywhere.
"""
from __future__ import annotations

from datetime import date, timedelta
from itertools import count

from ..domain import (
    Employee,
    EntryStatus,
    MockDataset,
    Period,
    ScheduleEntry,
    SourceEvidence,
    merge_source_evidence,
)

# Entry statuses that occupy capacity.
OCCUPYING = {EntryStatus.SCHEDULED, EntryStatus.NEEDS_REVIEW}
SESSIONS = (1, 2)


def saturday_team_for(on: date) -> str:
    """Saturday A/B alternation by ISO week parity (assumption Q-A5)."""
    return "A" if on.isocalendar().week % 2 == 1 else "B"


def week_dates(week_start: date) -> list[date]:
    return [week_start + timedelta(days=i) for i in range(6)]  # Mon..Sat


class ScheduleContext:
    def __init__(self, dataset: MockDataset, entries: list[ScheduleEntry] | None = None):
        self.dataset = dataset
        self.employees = dataset.employee_map()
        self.elders = dataset.elder_map()
        self.week_start = dataset.params.week_start
        self.entries: list[ScheduleEntry] = []
        self.leaves: set[tuple[str, date, str]] = set()  # (worker_id, date, period)
        self._leave_evidence: dict[tuple[str, date, str], list[SourceEvidence]] = {}
        self._leave_source_refs: dict[tuple[str, date, str], set[str]] = {}
        self._leave_gap_ids: dict[tuple[str, date, str], set[str]] = {}
        self._leave_gap_policies: dict[tuple[str, date, str], dict[str, str]] = {}
        self._leave_override_ids: dict[tuple[str, date, str], set[str]] = {}
        self._leave_dependencies: dict[tuple[str, date, str], set[str]] = {}
        self.forbidden_slots: set[tuple[str, date, str]] = set()
        self._occupancy: dict[tuple[str, date, str], dict[int, str]] = {}
        self._full: dict[tuple[str, date, str], str] = {}  # full-period entry id
        self._id_counter = count(1)
        self._demand_revisions: dict[tuple[str, str], int] = {}
        for row in dataset.unavailable_slots:
            if row.is_available or row.available_date is None:
                continue
            if row.reason == "manual_override":
                self.add_unavailable(
                    row.worker_id,
                    row.available_date,
                    row.period,
                    reason=row.reason,
                )
            else:
                self.add_leave(
                    row.worker_id,
                    row.available_date,
                    row.period,
                    source_refs=row.source_refs,
                    source_evidence=row.source_evidence,
                    data_gap_ids=row.data_gap_ids,
                    data_gap_policies=row.data_gap_policies,
                    override_ids=row.override_ids,
                    depends_on=row.depends_on,
                )
        for entry in entries or []:
            self.add_entry(entry)
            if entry.demand_id:
                key = (entry.demand_id, entry.entry_role)
                self._demand_revisions[key] = max(
                    self._demand_revisions.get(key, 0), entry.revision
                )

    # ------------------------------------------------------------------ ids
    def next_entry_id(self, prefix: str = "entry") -> str:
        return f"{prefix}-{next(self._id_counter):05d}"

    def next_demand_revision(self, demand_id: str | None, role: str) -> int:
        if demand_id is None:
            return 1
        key = (demand_id, role)
        revision = self._demand_revisions.get(key, 0) + 1
        self._demand_revisions[key] = revision
        return revision

    # ---------------------------------------------------------- availability
    def add_leave(
        self,
        worker_id: str,
        on: date,
        period: Period | None,
        *,
        source_refs=(),
        source_evidence=(),
        data_gap_ids=(),
        data_gap_policies=None,
        override_ids=(),
        depends_on=(),
    ) -> None:
        periods = [period.value] if period else [Period.AM.value, Period.PM.value]
        for p in periods:
            slot = (worker_id, on, p)
            self.leaves.add(slot)
            self._leave_evidence[slot] = merge_source_evidence(
                self._leave_evidence.get(slot, []), source_evidence
            )
            self._leave_source_refs.setdefault(slot, set()).update(source_refs)
            self._leave_gap_ids.setdefault(slot, set()).update(data_gap_ids)
            policies = self._leave_gap_policies.setdefault(slot, {})
            for gap_id, policy in (data_gap_policies or {}).items():
                if gap_id in policies and policies[gap_id] != policy:
                    raise ValueError(f"conflicting leave gap policy for {gap_id}")
                policies[gap_id] = policy
            self._leave_override_ids.setdefault(slot, set()).update(override_ids)
            self._leave_dependencies.setdefault(slot, set()).update(depends_on)

    def leave_provenance(
        self, worker_id: str, on: date, period: Period
    ) -> dict[str, object]:
        slot = (worker_id, on, period.value)
        return {
            "source_refs": sorted(self._leave_source_refs.get(slot, set())),
            "source_evidence": list(self._leave_evidence.get(slot, [])),
            "data_gap_ids": sorted(self._leave_gap_ids.get(slot, set())),
            "data_gap_policies": dict(self._leave_gap_policies.get(slot, {})),
            "override_ids": sorted(self._leave_override_ids.get(slot, set())),
            "depends_on": sorted(self._leave_dependencies.get(slot, set())),
        }

    def add_unavailable(
        self,
        worker_id: str,
        on: date,
        period: Period | None,
        *,
        reason: str,
    ) -> None:
        periods = [period.value] if period else [Period.AM.value, Period.PM.value]
        target = self.forbidden_slots if reason == "manual_override" else self.leaves
        for p in periods:
            target.add((worker_id, on, p))

    def on_leave(self, worker_id: str, on: date, period: Period) -> bool:
        return (worker_id, on, period.value) in self.leaves

    def is_forbidden(self, worker_id: str, on: date, period: Period) -> bool:
        return (worker_id, on, period.value) in self.forbidden_slots

    def is_working_day(self, worker: Employee, on: date) -> bool:
        wd = on.isoweekday()
        if wd <= 5:
            return True
        if wd == 6:
            return worker.saturday_team == saturday_team_for(on)
        return False

    def is_available(self, worker: Employee, on: date, period: Period) -> bool:
        return (
            self.is_working_day(worker, on)
            and not self.on_leave(worker.id, on, period)
            and not self.is_forbidden(worker.id, on, period)
        )

    # ------------------------------------------------------------- occupancy
    def _slot(self, worker_id: str, on: date, period: Period) -> tuple[str, date, str]:
        return (worker_id, on, period.value)

    def free_sessions(self, worker_id: str, on: date, period: Period) -> list[int]:
        slot = self._slot(worker_id, on, period)
        if slot in self._full:
            return []
        used = self._occupancy.get(slot, {})
        return [s for s in SESSIONS if s not in used]

    def can_place(self, worker_id: str, on: date, period: Period,
                  session_index: int | None) -> bool:
        free = self.free_sessions(worker_id, on, period)
        if session_index is None:  # needs the whole half-day
            return len(free) == len(SESSIONS)
        return session_index in free

    def period_is_empty(self, worker_id: str, on: date, period: Period) -> bool:
        return len(self.free_sessions(worker_id, on, period)) == len(SESSIONS)

    def add_entry(self, entry: ScheduleEntry) -> ScheduleEntry:
        self.entries.append(entry)
        self._occupy(entry)
        return entry

    def _occupy(self, entry: ScheduleEntry) -> None:
        if entry.status not in OCCUPYING or not entry.worker_id:
            return
        slot = self._slot(entry.worker_id, entry.schedule_date, entry.period)
        if entry.session_index is None:
            self._full[slot] = entry.id
        else:
            self._occupancy.setdefault(slot, {})[entry.session_index] = entry.id

    def release(self, entry: ScheduleEntry) -> None:
        if not entry.worker_id:
            return
        slot = self._slot(entry.worker_id, entry.schedule_date, entry.period)
        if entry.session_index is None:
            if self._full.get(slot) == entry.id:
                del self._full[slot]
        else:
            sessions = self._occupancy.get(slot, {})
            if sessions.get(entry.session_index) == entry.id:
                del sessions[entry.session_index]

    def set_status(self, entry: ScheduleEntry, status: EntryStatus) -> None:
        """Status transition with occupancy bookkeeping."""
        was_occupying = entry.status in OCCUPYING
        entry.status = status
        now_occupying = status in OCCUPYING
        if was_occupying and not now_occupying:
            self.release(entry)
        elif not was_occupying and now_occupying:
            self._occupy(entry)

    # --------------------------------------------------------------- queries
    def entries_for_worker(self, worker_id: str, on: date,
                           period: Period | None = None) -> list[ScheduleEntry]:
        return [
            e for e in self.entries
            if e.worker_id == worker_id and e.schedule_date == on
            and (period is None or e.period == period)
            and e.status in OCCUPYING
        ]

    def entries_for_elder(self, elder_id: str, on: date,
                          period: Period | None = None) -> list[ScheduleEntry]:
        return [
            e for e in self.entries
            if e.elder_id == elder_id and e.schedule_date == on
            and (period is None or e.period == period)
            and e.status in OCCUPYING
        ]

    def workload(self, worker_id: str) -> int:
        """Occupied sessions this week (full-period entries count as 2)."""
        n = 0
        for e in self.entries:
            if e.worker_id == worker_id and e.status in OCCUPYING:
                n += 2 if e.session_index is None else 1
        return n

    def duty_count(self, worker_id: str) -> int:
        from ..domain import SERVICE_CATEGORY, ServiceCategory
        return sum(
            1 for e in self.entries
            if e.worker_id == worker_id and e.status in OCCUPYING
            and SERVICE_CATEGORY[e.service_code] == ServiceCategory.CENTER_DUTY
        )

    def duty_assigned(self, center: str, on: date, period: Period) -> int:
        return sum(
            1 for e in self.entries
            if e.center == center and e.schedule_date == on
            and e.period == period and e.status in OCCUPYING
            and e.service_code.value == center
        )
