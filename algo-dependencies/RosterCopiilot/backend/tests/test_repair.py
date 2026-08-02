"""Repair engine tests: leave, cancellation, escort changes, batches."""
from datetime import timedelta

from app.domain import (
    AuditKind,
    ChangeEvent,
    ChangeType,
    EntryStatus,
    Period,
    Severity,
)
from app.engine import apply_changes, validate_entries
from app.services.state import leaves_from_events

ACTIVE = {EntryStatus.SCHEDULED, EntryStatus.NEEDS_REVIEW}


def _leave(worker_id, on, period=None, id_="ev-t"):
    return ChangeEvent(id=id_, type=ChangeType.LEAVE, change_date=on,
                       period=period, worker_id=worker_id, reason="test")


def test_full_day_leave_removes_worker_and_repairs(dataset, baseline):
    ws = dataset.params.week_start
    tue = ws + timedelta(days=1)
    version, reports = apply_changes(dataset, baseline, [_leave("W002", tue)])
    # the worker holds nothing active that day
    for e in version.entries:
        if e.worker_id == "W002" and e.schedule_date == tue:
            assert e.status not in ACTIVE
    # roster still valid given the leave
    leaves = leaves_from_events(version.trigger_events)
    assert validate_entries(dataset, version.entries, leaves) == []
    assert version.summary["hard_constraint_violations"] == 0
    assert reports and reports[0].event.worker_id == "W002"


def test_exclusive_worker_leave_cancels_never_substitutes(dataset, baseline):
    """RB-EXCL-02: W001's Monday-AM exclusive visits -> cancellation proposals."""
    ws = dataset.params.week_start
    version, _ = apply_changes(dataset, baseline,
                               [_leave("W001", ws, Period.AM)])
    exclusive_audits = [a for a in version.audit_items
                        if a.kind == AuditKind.EXCLUSIVE_CANCELLATION
                        and a.trigger_event_id == "ev-t"]
    assert len(exclusive_audits) == 2  # E0001 + E0002 pinned to Mon AM
    for a in exclusive_audits:
        assert a.blocking and a.severity == Severity.HIGH
        assert a.suggested_entry.status == EntryStatus.CANCELLED
    # and no substitute was proposed for those services
    fixed_ids = {a.original_entry.origin_fixed_service_id for a in exclusive_audits}
    for e in version.entries:
        if e.origin_fixed_service_id in fixed_ids and e.status in ACTIVE:
            assert e.worker_id == "W001" or e.status not in ACTIVE


def test_half_day_leave_only_affects_that_period(dataset, baseline):
    ws = dataset.params.week_start
    version, _ = apply_changes(dataset, baseline, [_leave("W001", ws, Period.AM)])
    pm = [e for e in version.entries
          if e.worker_id == "W001" and e.schedule_date == ws and e.period == Period.PM]
    assert pm, "W001 has Monday PM work (exclusive E0003)"
    assert all(e.status in ACTIVE for e in pm)


def test_elder_cancellation_frees_worker_with_refill_or_release(dataset, baseline, events):
    ev = next(e for e in events if e.type == ChangeType.ELDER_CANCELLATION)
    version, reports = apply_changes(dataset, baseline, [ev])
    cancelled = [e for e in version.entries
                 if e.elder_id == ev.elder_id and e.schedule_date == ev.change_date
                 and e.status == EntryStatus.CANCELLED]
    assert cancelled
    report = next(r for r in reports if r.event.type == ChangeType.ELDER_CANCELLATION)
    kinds = {a for i in report.impacts for a in [i.title]}
    assert "service_cancellation" in kinds
    assert "refill" in kinds  # freed-capacity follow-up always reported
    assert version.summary["hard_constraint_violations"] == 0


def test_new_escort_gets_assigned_or_chained(dataset, baseline, events):
    ev = next(e for e in events if e.type == ChangeType.ESCORT_NEW)
    version, reports = apply_changes(dataset, baseline, [ev])
    report = next(r for r in reports if r.event.type == ChangeType.ESCORT_NEW)
    assert report.audit_item_ids
    added = [e for e in version.entries
             if e.origin_escort_request_id == ev.new_escort.id]
    assert added and added[0].status in (EntryStatus.NEEDS_REVIEW,
                                         EntryStatus.UNASSIGNED)
    assert version.summary["hard_constraint_violations"] == 0


def test_escort_cancelled_releases_worker(dataset, baseline, events):
    ev = next(e for e in events if e.type == ChangeType.ESCORT_CANCELLED)
    version, _ = apply_changes(dataset, baseline, [ev])
    entry = next(e for e in version.entries
                 if e.origin_escort_request_id == ev.escort_request_id)
    assert entry.status == EntryStatus.CANCELLED
    assert version.summary["hard_constraint_violations"] == 0


def test_batch_events_processed_free_before_consume(dataset, baseline, events):
    version, reports = apply_changes(dataset, baseline, events)
    types = [r.event.type for r in reports]
    order = {ChangeType.ELDER_CANCELLATION: 0, ChangeType.ESCORT_CANCELLED: 1,
             ChangeType.LEAVE: 2, ChangeType.ESCORT_NEW: 3}
    assert types == sorted(types, key=lambda t: order[t])
    assert version.summary["hard_constraint_violations"] == 0
    assert version.summary["change_distance_from_original"] > 0
    assert version.parent_version_id == baseline.id


def test_baseline_untouched_by_repair(dataset, baseline, events):
    before = [(e.id, e.status) for e in baseline.entries]
    apply_changes(dataset, baseline, events)
    after = [(e.id, e.status) for e in baseline.entries]
    assert before == after
