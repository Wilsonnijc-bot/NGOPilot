"""Audit queue + decision lifecycle via the AppState store."""
import pytest

from app.domain import (
    AuditDecision,
    AuditKind,
    AuditStatus,
    EntryStatus,
    Gender,
    ServiceCode,
)
from app.services.state import AppState


@pytest.fixture()
def state():
    return AppState()


def _applied_state():
    st = AppState()
    st.apply(st.example_events())
    return st


def test_audit_queue_orders_blocking_first(state):
    state.apply(state.example_events())
    queue = state.audit_queue()
    pending = [a for a in queue if a.status == AuditStatus.PENDING]
    first_non_blocking = next((i for i, a in enumerate(pending) if not a.blocking),
                              len(pending))
    assert all(not a.blocking for a in pending[first_non_blocking:])


def test_approve_replacement_promotes_suggestion():
    st = _applied_state()
    item = next(a for a in st.current.audit_items
                if a.kind == AuditKind.REPLACEMENT_SUGGESTION
                and a.status == AuditStatus.PENDING)
    st.decide(item.id, AuditDecision(status=AuditStatus.APPROVED))
    sug = st.current.entry_by_id(item.suggested_entry.id)
    orig = st.current.entry_by_id(item.original_entry.id)
    assert sug.status == EntryStatus.SCHEDULED
    assert orig.status == EntryStatus.CANCELLED
    assert orig.superseded_by == sug.id
    assert st.current.summary["hard_constraint_violations"] == 0


def test_reject_requires_note_and_withdraws_suggestion():
    st = _applied_state()
    item = next(a for a in st.current.audit_items
                if a.kind == AuditKind.REPLACEMENT_SUGGESTION
                and a.status == AuditStatus.PENDING)
    with pytest.raises(ValueError):
        st.decide(item.id, AuditDecision(status=AuditStatus.REJECTED))
    st.decide(item.id, AuditDecision(status=AuditStatus.REJECTED,
                                     human_note="長者不接受此同工"))
    sug = st.current.entry_by_id(item.suggested_entry.id)
    orig = st.current.entry_by_id(item.original_entry.id)
    assert sug.status == EntryStatus.CANCELLED
    assert orig.status == EntryStatus.UNASSIGNED  # gap stays visible


def test_approve_exclusive_cancellation_cancels_original():
    st = _applied_state()
    item = next(a for a in st.current.audit_items
                if a.kind == AuditKind.EXCLUSIVE_CANCELLATION
                and a.status == AuditStatus.PENDING)
    st.decide(item.id, AuditDecision(status=AuditStatus.APPROVED))
    orig = st.current.entry_by_id(item.original_entry.id)
    assert orig.status == EntryStatus.CANCELLED


def test_edit_with_hard_violation_requires_note():
    from app.domain import ChangeEvent, ChangeType

    st = AppState()
    # target a worker holding a scheduled ESC entry (skill-gated) and put
    # them on leave -> guaranteed skill-gated replacement suggestion
    escort_entry = next(e for e in st.baseline.entries
                        if e.service_code == ServiceCode.ESCORT
                        and e.status == EntryStatus.SCHEDULED)
    st.apply([ChangeEvent(id="ev-esc", type=ChangeType.LEAVE,
                          change_date=escort_entry.schedule_date,
                          period=escort_entry.period,
                          worker_id=escort_entry.worker_id, reason="test")])
    item = next(a for a in st.current.audit_items
                if a.kind == AuditKind.REPLACEMENT_SUGGESTION
                and a.status == AuditStatus.PENDING
                and a.suggested_entry.service_code == ServiceCode.ESCORT)
    # craft an edit that violates skill rules: give the task to a worker
    # without the needed skill
    bad_worker = next(w for w in st.dataset.employees
                      if ServiceCode.ESCORT not in w.skills)
    edited = item.suggested_entry.model_copy(
        update={"worker_id": bad_worker.id, "worker_name": bad_worker.display_name,
                "id": "manual-0001"})
    with pytest.raises(ValueError, match="hard constraints"):
        st.decide(item.id, AuditDecision(status=AuditStatus.EDITED,
                                         edited_entry=edited))
    # with a note, the human override is accepted but recorded
    st.decide(item.id, AuditDecision(status=AuditStatus.EDITED,
                                     edited_entry=edited,
                                     human_note="中心主任特批"))
    assert st.current.entry_by_id("manual-0001").status == EntryStatus.SCHEDULED


def test_double_decision_rejected():
    st = _applied_state()
    item = next(a for a in st.current.audit_items
                if a.status == AuditStatus.PENDING)
    st.decide(item.id, AuditDecision(status=AuditStatus.APPROVED))
    with pytest.raises(ValueError, match="already decided"):
        st.decide(item.id, AuditDecision(status=AuditStatus.APPROVED))


def test_regenerate_with_seed_is_reproducible():
    a, b = AppState(seed=99), AppState(seed=99)
    assert a.dataset.model_dump() == b.dataset.model_dump()
    key = lambda st: [(e.worker_id, e.service_code.value, str(e.schedule_date))
                      for e in st.baseline.entries]
    assert key(a) == key(b)
