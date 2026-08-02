"""Negative-path hard-rule validator tests from the Phase 1A matrix."""
from __future__ import annotations

from datetime import date, timedelta

from app.domain import (
    CenterDutyRequirement,
    Elder,
    Employee,
    EntrySource,
    EntryStatus,
    EscortRequest,
    FixedService,
    Gender,
    GenderRequirement,
    MockDataset,
    Period,
    ReviewReasonCode,
    ScheduleEntry,
    ScheduleParams,
    ServiceCode,
    WorkerAvailability,
)
from app.engine import build_baseline, validate_entries
from app.engine.context import ScheduleContext, saturday_team_for
from app.engine.eligibility import check_assignment
from app.engine.tasks import Task

WEEK_START = date(2026, 1, 5)
MONDAY = WEEK_START
SATURDAY = WEEK_START + timedelta(days=5)
SUNDAY = WEEK_START + timedelta(days=6)


def _worker(
    worker_id: str = "W1",
    *,
    gender: Gender | None = Gender.FEMALE,
    skills: list[ServiceCode] | None = None,
    saturday_team: str | None = "A",
) -> Employee:
    return Employee(
        id=worker_id,
        display_name=worker_id,
        gender=gender,
        skills=skills if skills is not None else [ServiceCode.HOME_CLEAN],
        saturday_team=saturday_team,  # type: ignore[arg-type]
    )


def _elder(
    elder_id: str = "E1",
    *,
    gender: Gender | None = Gender.FEMALE,
    requirement: GenderRequirement = GenderRequirement.ANY,
) -> Elder:
    return Elder(
        id=elder_id,
        display_name=elder_id,
        gender=gender,
        district="Wan Chai",
        gender_requirement=requirement,
    )


def _dataset(
    *,
    workers: list[Employee] | None = None,
    elders: list[Elder] | None = None,
    fixed_services: list[FixedService] | None = None,
    escorts: list[EscortRequest] | None = None,
    duty_requirements: list[CenterDutyRequirement] | None = None,
    unavailable_slots: list[WorkerAvailability] | None = None,
) -> MockDataset:
    return MockDataset(
        employees=workers if workers is not None else [_worker()],
        elders=elders if elders is not None else [_elder()],
        fixed_services=fixed_services or [],
        escort_requests=escorts or [],
        duty_requirements=duty_requirements or [],
        unavailable_slots=unavailable_slots or [],
        params=ScheduleParams(week_start=WEEK_START),
    )


def _entry(
    entry_id: str,
    *,
    worker_id: str = "W1",
    service: ServiceCode = ServiceCode.HOME_CLEAN,
    on: date = MONDAY,
    period: Period = Period.AM,
    session: int | None = 1,
    elder_id: str | None = "E1",
    status: EntryStatus = EntryStatus.SCHEDULED,
    fixed_id: str | None = None,
    escort_id: str | None = None,
    flags: list[str] | None = None,
) -> ScheduleEntry:
    return ScheduleEntry(
        id=entry_id,
        schedule_date=on,
        weekday=on.isoweekday() if on.isoweekday() <= 6 else 6,  # type: ignore[arg-type]
        period=period,
        session_index=session,  # type: ignore[arg-type]
        worker_id=worker_id,
        worker_name=worker_id,
        service_code=service,
        elder_id=elder_id,
        elder_name=elder_id,
        source=EntrySource.MANUAL,
        status=status,
        origin_fixed_service_id=fixed_id,
        origin_escort_request_id=escort_id,
        constraint_flags=flags or [],
    )


def _codes(dataset: MockDataset, entries: list[ScheduleEntry], leaves=None):
    return [v.code for v in validate_entries(dataset, entries, leaves or set())]


def test_validator_reports_session_double_booking():
    dataset = _dataset()
    codes = _codes(dataset, [_entry("a"), _entry("b")])
    assert codes.count(ReviewReasonCode.TIME_CONFLICT) == 2


def test_validator_reports_full_period_overlap_for_every_entry():
    dataset = _dataset(workers=[_worker(skills=[ServiceCode.HOME_CLEAN, ServiceCode.ESCORT])])
    codes = _codes(dataset, [
        _entry("escort", service=ServiceCode.ESCORT, session=None, escort_id="ER1"),
        _entry("hc", service=ServiceCode.HOME_CLEAN, session=1),
    ])
    assert codes.count(ReviewReasonCode.TIME_CONFLICT) == 2


def test_validator_reports_skill_mismatch_but_never_for_meal():
    dataset = _dataset(workers=[_worker(skills=[])])

    assert ReviewReasonCode.SKILL_MISMATCH in _codes(dataset, [
        _entry("hc", service=ServiceCode.HOME_CLEAN)
    ])
    assert _codes(dataset, [_entry("meal", service=ServiceCode.MEAL)]) == []


def test_validator_reports_gender_mismatch_and_unknown_gender():
    mismatch = _dataset(
        workers=[_worker(gender=Gender.MALE, skills=[ServiceCode.BATH])],
        elders=[_elder(requirement=GenderRequirement.FEMALE)],
    )
    assert ReviewReasonCode.GENDER_MISMATCH in _codes(mismatch, [
        _entry("bath", service=ServiceCode.BATH)
    ])

    unknown = _dataset(
        workers=[_worker(gender=Gender.FEMALE, skills=[ServiceCode.BATH])],
        elders=[_elder(gender=None)],
    )
    assert ReviewReasonCode.GENDER_UNKNOWN in _codes(unknown, [
        _entry("bath", service=ServiceCode.BATH)
    ])

    review_entry = _entry(
        "bath-review",
        service=ServiceCode.BATH,
        status=EntryStatus.NEEDS_REVIEW,
        flags=["gender_ok_unverified"],
    )
    review_entry.data_gap_ids = ["gap-gender-review"]
    assert _codes(unknown, [review_entry]) == []


def test_validator_reports_exclusive_binding_substitution():
    fixed = FixedService(
        id="FS1",
        elder_id="E1",
        service_code=ServiceCode.EXERCISE,
        weekday=1,
        period=Period.AM,
        assigned_worker_id="W1",
        is_exclusive=True,
    )
    dataset = _dataset(
        workers=[
            _worker("W1", skills=[ServiceCode.EXERCISE]),
            _worker("W2", skills=[ServiceCode.EXERCISE]),
        ],
        fixed_services=[fixed],
    )
    codes = _codes(dataset, [
        _entry("sub", worker_id="W2", service=ServiceCode.EXERCISE, fixed_id="FS1")
    ])
    assert ReviewReasonCode.EXCLUSIVE_BINDING in codes


def test_validator_reports_leave_saturday_and_sunday_violations():
    off_team = "B" if saturday_team_for(SATURDAY) == "A" else "A"
    dataset = _dataset(workers=[_worker(saturday_team=off_team)])

    leave_codes = _codes(
        dataset,
        [_entry("leave")],
        leaves={("W1", MONDAY, Period.AM.value)},
    )
    assert ReviewReasonCode.WORKER_ON_LEAVE in leave_codes

    day_codes = _codes(dataset, [
        _entry("sat", on=SATURDAY),
        _entry("sun", on=SUNDAY),
    ])
    assert day_codes.count(ReviewReasonCode.NOT_WORKING_DAY) == 2


def test_validator_reports_must_preference_substitution():
    escort = EscortRequest(
        id="ER1",
        service_date=MONDAY,
        period=Period.AM,
        elder_id="E1",
        destination="Clinic",
        preferred_worker_id="W1",
        preference_strength="must",
    )
    dataset = _dataset(
        workers=[
            _worker("W1", skills=[ServiceCode.ESCORT]),
            _worker("W2", skills=[ServiceCode.ESCORT]),
        ],
        escorts=[escort],
    )
    codes = _codes(dataset, [
        _entry("escort", worker_id="W2", service=ServiceCode.ESCORT,
               session=None, escort_id="ER1")
    ])
    assert ReviewReasonCode.PREFERENCE_UNMET in codes


def test_forbid_assignment_override_rejected_by_gate_and_validator():
    unavailable = WorkerAvailability(
        worker_id="W1",
        available_date=MONDAY,
        period=Period.AM,
        is_available=False,
        reason="manual_override",
    )
    dataset = _dataset(unavailable_slots=[unavailable])
    task = Task(
        key="t",
        service_code=ServiceCode.HOME_CLEAN,
        task_date=MONDAY,
        weekday=1,
        period=Period.AM,
        session_index=1,
        elder_id="E1",
    )
    reasons = check_assignment(dataset.employees[0], task, ScheduleContext(dataset))
    assert any(r.code == ReviewReasonCode.FORBIDDEN_ASSIGNMENT for r in reasons)

    codes = _codes(dataset, [_entry("forbidden")])
    assert ReviewReasonCode.FORBIDDEN_ASSIGNMENT in codes


def test_duty_shortfall_becomes_blocking_audit_item():
    dataset = _dataset(
        workers=[_worker(skills=[ServiceCode.DUTY_AMC])],
        fixed_services=[],
        duty_requirements=[
            CenterDutyRequirement(
                center="AMC",
                weekday=1,
                period=Period.AM,
                required_count=3,
            )
        ],
    )
    version = build_baseline(dataset)
    assert version.summary["center_duty_slots_below_required"] == 1
    assert any(
        item.kind.value == "duty_under_coverage"
        and item.blocking
        and item.reasons[0].code == ReviewReasonCode.DUTY_SHORTFALL
        for item in version.audit_items
    )
