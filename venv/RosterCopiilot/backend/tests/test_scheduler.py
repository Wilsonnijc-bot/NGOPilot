"""Baseline scheduler tests: hard constraints, coverage, explainability."""
from app.domain import (
    EntryStatus,
    GENDER_SENSITIVE,
    ReviewReasonCode,
    ServiceCode,
    SKILL_GATED,
)
from app.engine import build_baseline, validate_entries, week_dates


ACTIVE = {EntryStatus.SCHEDULED, EntryStatus.NEEDS_REVIEW}


def test_no_hard_constraint_violations(dataset, baseline):
    violations = validate_entries(dataset, baseline.entries, leaves=set())
    assert violations == []
    assert baseline.summary["hard_constraint_violations"] == 0


def test_skill_gate_respected(dataset, baseline):
    workers = dataset.employee_map()
    for e in baseline.entries:
        if e.status in ACTIVE and e.worker_id and e.service_code in SKILL_GATED:
            assert e.service_code in workers[e.worker_id].skills, e.id


def test_gender_requirements_respected(dataset, baseline):
    workers = dataset.employee_map()
    elders = dataset.elder_map()
    for e in baseline.entries:
        if e.status not in ACTIVE or not e.worker_id:
            continue
        if e.service_code in GENDER_SENSITIVE and e.service_code != ServiceCode.ESCORT:
            elder = elders.get(e.elder_id or "")
            if elder is None:
                continue
            req = elder.gender_requirement.value if elder.gender_requirement.value in "MF" \
                else (elder.gender.value if elder.gender else None)
            if req in ("M", "F"):
                assert workers[e.worker_id].gender is not None
                assert workers[e.worker_id].gender.value == req


def test_exclusive_services_only_by_bound_worker(dataset, baseline):
    fixed = {fs.id: fs for fs in dataset.fixed_services}
    for e in baseline.entries:
        fs = fixed.get(e.origin_fixed_service_id or "")
        if fs and fs.is_exclusive and e.status in ACTIVE:
            assert e.worker_id == fs.assigned_worker_id


def test_no_double_booking(baseline):
    slots: dict[tuple, set] = {}
    for e in baseline.entries:
        if e.status not in ACTIVE or not e.worker_id:
            continue
        key = (e.worker_id, e.schedule_date, e.period)
        used = slots.setdefault(key, set())
        needed = {1, 2} if e.session_index is None else {e.session_index}
        assert not (used & needed), f"double booking at {key}"
        used |= needed


def test_center_duty_fully_covered(dataset, baseline):
    dates = week_dates(baseline.week_start)
    for req in dataset.duty_requirements:
        on = dates[req.weekday - 1]
        got = sum(1 for e in baseline.entries
                  if e.service_code == req.service_code and e.schedule_date == on
                  and e.period == req.period and e.status in ACTIVE)
        assert got >= req.required_count, f"{req.center} {on} {req.period}"
    assert baseline.summary["center_duty_slots_below_required"] == 0


def test_unassigned_tasks_have_structured_reasons_and_audits(baseline):
    unassigned = [e for e in baseline.entries if e.status == EntryStatus.UNASSIGNED]
    assert unassigned, "mock data intentionally contains unassignable demand"
    audit_originals = {a.original_entry.id for a in baseline.audit_items
                       if a.original_entry}
    for e in unassigned:
        assert e.review_reasons, f"{e.id} missing structured reasons"
        assert all(r.code in ReviewReasonCode for r in e.review_reasons)
        assert e.id in audit_originals, f"{e.id} has no audit item"


def test_every_active_entry_has_explanation(baseline):
    for e in baseline.entries:
        if e.status in ACTIVE:
            assert e.explanation, f"{e.id} lacks explanation"


def test_baseline_is_deterministic(dataset, baseline):
    again = build_baseline(dataset)
    key = lambda v: [(e.worker_id, e.service_code.value, str(e.schedule_date),
                      e.period.value, e.session_index, e.status.value)
                     for e in v.entries]
    assert key(again) == key(baseline)


def test_data_gap_escort_is_blocked_not_guessed(dataset, baseline):
    """UNKNOWN gender requirement must never be silently assigned."""
    gap_requests = {r.id for r in dataset.escort_requests
                    if r.gender_requirement.value == "UNKNOWN"}
    assert gap_requests
    for e in baseline.entries:
        if e.origin_escort_request_id in gap_requests:
            assert e.status == EntryStatus.UNASSIGNED
            assert any(r.code == ReviewReasonCode.GENDER_UNKNOWN
                       for r in e.review_reasons)
