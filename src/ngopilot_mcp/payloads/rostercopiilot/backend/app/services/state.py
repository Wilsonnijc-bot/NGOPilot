"""Application state facade.

Holds the compatibility dataset and version tree in memory for the scheduler
while persisting snapshots into SQLite. Tests can still construct fresh
instances; the API singleton loads the existing DB when one is present.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from threading import Lock

from ..domain import (
    AuditDecision,
    AuditItem,
    AuditKind,
    AuditStatus,
    ChangeEvent,
    ChangeType,
    EntryStatus,
    ImpactReport,
    MockDataset,
    Period,
    ScheduleVersion,
)
from ..engine import apply_changes, build_baseline, compute_metrics, validate_entries
from ..engine.builders import reset_audit_counter
from ..mockdata import DEFAULT_SEED, example_changes, generate_dataset
from ..store import RosterStore


def leaves_from_events(events: list[ChangeEvent]) -> set[tuple[str, date, str]]:
    leaves: set[tuple[str, date, str]] = set()
    for ev in events:
        if ev.type == ChangeType.LEAVE and ev.worker_id:
            periods = [ev.period.value] if ev.period else [Period.AM.value,
                                                           Period.PM.value]
            for p in periods:
                leaves.add((ev.worker_id, ev.change_date, p))
    return leaves


class AppState:
    def __init__(
        self,
        seed: int = DEFAULT_SEED,
        *,
        store: RosterStore | None = None,
        db_path: Path | None = None,
        load_existing: bool = False,
        persist: bool = True,
    ):
        self.store = store or (RosterStore(db_path) if persist else None)
        if load_existing and self.store is not None and self._load_from_store():
            return
        self.regenerate(seed)

    # ------------------------------------------------------------- lifecycle
    def regenerate(self, seed: int) -> MockDataset:
        reset_audit_counter()
        self.seed = seed
        self.dataset: MockDataset = generate_dataset(seed)
        self.versions: dict[str, ScheduleVersion] = {}
        baseline = build_baseline(self.dataset)
        self.versions[baseline.id] = baseline
        self.baseline_id = baseline.id
        self.current_id = baseline.id
        self._persist()
        return self.dataset

    def reset_schedule(self) -> ScheduleVersion:
        """Drop repairs/decisions; rebuild the baseline from the same dataset."""
        reset_audit_counter()
        baseline = build_baseline(self.dataset)
        self.versions = {baseline.id: baseline}
        self.baseline_id = baseline.id
        self.current_id = baseline.id
        self._persist()
        return baseline

    # --------------------------------------------------------------- queries
    @property
    def current(self) -> ScheduleVersion:
        return self.versions[self.current_id]

    @property
    def baseline(self) -> ScheduleVersion:
        return self.versions[self.baseline_id]

    def get_version(self, version_id: str) -> ScheduleVersion | None:
        return self.versions.get(version_id)

    def example_events(self) -> list[ChangeEvent]:
        return example_changes(self.dataset)

    # --------------------------------------------------------------- changes
    def simulate(self, events: list[ChangeEvent],
                 base: ScheduleVersion | None = None
                 ) -> tuple[ScheduleVersion, list[ImpactReport]]:
        """Run repair without committing (impact preview)."""
        return apply_changes(self.dataset, base or self.current, events)

    def apply(self, events: list[ChangeEvent]) -> tuple[ScheduleVersion, list[ImpactReport]]:
        version, reports = apply_changes(self.dataset, self.current, events)
        self.versions[version.id] = version
        self.current_id = version.id
        self._persist()
        return version, reports

    def generate(self, events: list[ChangeEvent]) -> ScheduleVersion:
        """Mock-compat: rebuild baseline, then apply events (if any)."""
        baseline = self.reset_schedule()
        if not events:
            return baseline
        version, _ = self.apply(events)
        return version

    # -------------------------------------------------------------- decisions
    def audit_queue(self) -> list[AuditItem]:
        order = {"high": 0, "warning": 1, "info": 2}
        items = list(self.current.audit_items)
        items.sort(key=lambda a: (a.status != AuditStatus.PENDING, not a.blocking,
                                  order[a.severity.value], a.id))
        return items

    def decide(self, audit_id: str, decision: AuditDecision) -> ScheduleVersion:
        version = self.current
        item = next((a for a in version.audit_items if a.id == audit_id), None)
        if item is None:
            raise KeyError(audit_id)
        if item.status != AuditStatus.PENDING:
            raise ValueError(f"audit item {audit_id} already decided ({item.status})")
        if decision.status == AuditStatus.REJECTED and not decision.human_note:
            raise ValueError("rejecting a suggestion requires a note (human_note)")

        if decision.status == AuditStatus.APPROVED:
            self._apply_approval(version, item)
        elif decision.status == AuditStatus.REJECTED:
            self._apply_rejection(version, item)
        elif decision.status == AuditStatus.EDITED:
            if decision.edited_entry is None:
                raise ValueError("edited decision requires edited_entry")
            self._apply_edit(version, item, decision)

        item.status = decision.status
        item.human_note = decision.human_note
        item.decided_at = datetime.now(timezone.utc)
        self._refresh_metrics(version)
        self._persist()
        return version

    # ------------------------------------------------------------- internals
    def _load_from_store(self) -> bool:
        assert self.store is not None
        loaded = self.store.load_app_state()
        if loaded is None:
            return False
        self.seed = loaded["seed"]
        self.dataset = loaded["dataset"]
        self.versions = loaded["versions"]
        self.baseline_id = loaded["baseline_id"]
        self.current_id = loaded["current_id"]
        return True

    def _persist(self) -> None:
        if self.store is None:
            return
        self.store.save_app_state(
            seed=self.seed,
            dataset=self.dataset,
            versions=self.versions,
            baseline_id=self.baseline_id,
            current_id=self.current_id,
        )

    def _entry(self, version: ScheduleVersion, entry_id: str | None):
        if not entry_id:
            return None
        return version.entry_by_id(entry_id)

    def _apply_approval(self, version: ScheduleVersion, item: AuditItem) -> None:
        original = self._entry(version, item.original_entry.id
                               if item.original_entry else None)
        suggested = self._entry(version, item.suggested_entry.id
                                if item.suggested_entry else None)
        if item.kind == AuditKind.DISPLACEMENT_CHAIN:
            for step in item.chain:
                after = self._entry(version, step.entry_after.id)
                if after is not None:
                    after.status = EntryStatus.SCHEDULED
                if step.entry_before is not None:
                    before = self._entry(version, step.entry_before.id)
                    if before is not None:
                        before.status = EntryStatus.CANCELLED
            return
        if item.kind in (AuditKind.EXCLUSIVE_CANCELLATION,
                         AuditKind.SERVICE_CANCELLATION):
            if original is not None:
                original.status = EntryStatus.CANCELLED
            return
        if suggested is not None:
            suggested.status = EntryStatus.SCHEDULED
            if original is not None and original.status == EntryStatus.AFFECTED:
                original.status = EntryStatus.CANCELLED
                original.superseded_by = suggested.id
        # unassigned_task / duty_under_coverage / data_gap: approval is an
        # acknowledgement — the gap stays visible until resolved by edit.

    def _apply_rejection(self, version: ScheduleVersion, item: AuditItem) -> None:
        original = self._entry(version, item.original_entry.id
                               if item.original_entry else None)
        suggested = self._entry(version, item.suggested_entry.id
                                if item.suggested_entry else None)
        if item.kind == AuditKind.DISPLACEMENT_CHAIN:
            for step in item.chain:
                after = self._entry(version, step.entry_after.id)
                if after is not None:
                    after.status = EntryStatus.CANCELLED
                if step.entry_before is not None:
                    before = self._entry(version, step.entry_before.id)
                    if before is not None:
                        before.status = EntryStatus.SCHEDULED
            return
        if suggested is not None and suggested.status == EntryStatus.NEEDS_REVIEW:
            suggested.status = EntryStatus.CANCELLED
            suggested.explanation = (suggested.explanation or "") + "｜人工否決"
        if original is not None and original.status == EntryStatus.AFFECTED:
            original.status = EntryStatus.UNASSIGNED
        # exclusive/service cancellation rejection: original stays as-is
        # (the reviewer keeps the service running / handles it manually).

    def _apply_edit(self, version: ScheduleVersion, item: AuditItem,
                    decision: AuditDecision) -> None:
        edited = decision.edited_entry
        assert edited is not None
        suggested = self._entry(version, item.suggested_entry.id
                                if item.suggested_entry else None)
        original = self._entry(version, item.original_entry.id
                               if item.original_entry else None)
        # withdraw the system suggestion, insert the human's entry
        if suggested is not None and suggested.status == EntryStatus.NEEDS_REVIEW:
            suggested.status = EntryStatus.CANCELLED
            suggested.explanation = (suggested.explanation or "") + "｜由人工修改取代"
        from ..domain import EntrySource
        edited = edited.model_copy(update={"status": EntryStatus.SCHEDULED,
                                           "source": EntrySource.MANUAL})
        version.entries.append(edited)
        if original is not None and original.status in (EntryStatus.AFFECTED,
                                                        EntryStatus.UNASSIGNED):
            original.status = EntryStatus.CANCELLED
            original.superseded_by = edited.id
        # hard-rule check on the human edit: violations are allowed only with
        # an explicit note (explainability over enforcement)
        leaves = leaves_from_events(version.trigger_events)
        violations = [v for v in validate_entries(self.dataset, version.entries, leaves)
                      if v.entry_id == edited.id]
        if violations and not decision.human_note:
            version.entries.remove(edited)
            if suggested is not None:
                suggested.status = EntryStatus.NEEDS_REVIEW
            if original is not None and original.superseded_by == edited.id:
                original.status = EntryStatus.AFFECTED
                original.superseded_by = None
            raise ValueError(
                "edited entry violates hard constraints "
                f"({'; '.join(v.message for v in violations)}); "
                "provide human_note to override")

    def _refresh_metrics(self, version: ScheduleVersion) -> None:
        leaves = leaves_from_events(version.trigger_events)
        runtime = version.summary.get("runtime_ms", 0.0)
        parent = self.versions.get(version.parent_version_id or "")
        version.summary = compute_metrics(self.dataset, version, leaves=leaves,
                                          runtime_ms=runtime, parent=parent)
        version.unassigned = [e for e in version.entries
                              if e.status == EntryStatus.UNASSIGNED]


_STATE: AppState | None = None
_STATE_LOCK = Lock()


def get_state() -> AppState:
    global _STATE
    if _STATE is None:
        with _STATE_LOCK:
            if _STATE is None:
                _STATE = AppState(load_existing=True)
    return _STATE


def reset_state(seed: int = DEFAULT_SEED, *, db_path: Path | None = None) -> AppState:
    global _STATE
    with _STATE_LOCK:
        _STATE = AppState(seed, db_path=db_path)
        return _STATE
