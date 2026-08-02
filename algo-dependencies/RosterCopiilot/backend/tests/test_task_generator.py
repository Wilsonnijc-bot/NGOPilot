"""Task generation layer tests (docs/spec/ENGINEERING_SPEC.md §10.1)."""
from datetime import date

from app.domain import (
    ChangeEvent,
    ChangeType,
    DataGap,
    Elder,
    Employee,
    GenderRequirement,
    Period,
    SchedulerConfig,
    SchedulerSnapshot,
    ServiceCode,
    TaskDemand,
    TaskKind,
    WeekPattern,
    WorkerAvailability,
)
from app.scheduler import duty_requirements, generate_demands, representative_snapshot

# Week of Mon 2026-01-05: Mon–Thu are the 1st weekday-occurrence of the month,
# Fri–Sat the 2nd. That is what separates the "1,3" and "2,4" HC patterns.
WEEK_START = date(2026, 1, 5)


def _snapshot(demands, **kw) -> SchedulerSnapshot:
    return SchedulerSnapshot(
        week_start=WEEK_START,
        config=SchedulerConfig(centre_duty_placeholders=[]),
        demands=demands,
        **kw,
    )


def test_representative_fixture_has_required_shape():
    gen = generate_demands(representative_snapshot())
    counts = gen.counts_by_kind
    fixed_and_hc = counts.get("fixed_service", 0) + counts.get("hc_pattern", 0)
    assert fixed_and_hc >= 10
    assert counts["escort"] >= 3
    assert len(gen.duty_requirements) >= 2
    assert len(gen.leave_events) >= 1
    assert len(gen.data_gaps) >= 1


def test_task_generation_counts_and_types():
    gen = generate_demands(representative_snapshot())
    assert set(gen.counts_by_kind) == {
        "fixed_service", "hc_pattern", "meal_logistics", "escort", "centre_duty",
    }
    # every generated task is concretely dated inside the target week
    assert all(t.task_date is not None for t in gen.tasks)
    assert all(WEEK_START <= t.task_date <= date(2026, 1, 10) for t in gen.tasks)


def test_hc_week_pattern_expansion():
    demands = [
        TaskDemand(id="w", kind=TaskKind.HC_PATTERN, service_code=ServiceCode.HOME_CLEAN,
                   weekday=1, period=Period.PM, session_index=1, elder_id="e1",
                   week_pattern=WeekPattern.parse("weekly")),
        TaskDemand(id="occ1", kind=TaskKind.HC_PATTERN, service_code=ServiceCode.HOME_CLEAN,
                   weekday=1, period=Period.PM, session_index=2, elder_id="e2",
                   week_pattern=WeekPattern.parse("1,3")),   # Mon = occurrence 1 -> fires
        TaskDemand(id="occ2", kind=TaskKind.HC_PATTERN, service_code=ServiceCode.HOME_CLEAN,
                   weekday=1, period=Period.AM, session_index=1, elder_id="e3",
                   week_pattern=WeekPattern.parse("2,4")),   # Mon = occurrence 1 -> gated out
    ]
    gen = generate_demands(_snapshot(demands))
    fired = {t.id for t in gen.tasks}
    assert fired == {"w", "occ1"}
    # the gated-out task is represented, not silently dropped (RB-DATA-01)
    assert any(t.id == "occ2" and "week_pattern_not_matched" in (t.notes or "")
               for t in gen.suppressed)
    # dated to the actual Monday of the target week
    assert next(t for t in gen.tasks if t.id == "occ1").task_date == date(2026, 1, 5)


def test_escort_half_day_occupancy():
    demands = [TaskDemand(
        id="esc", kind=TaskKind.ESCORT, service_code=ServiceCode.ESCORT,
        task_date=date(2026, 1, 8), period=Period.AM, session_index=None,
        occupies_full_period=True, elder_id="e1", destination="RH")]
    gen = generate_demands(_snapshot(demands))
    escort = gen.tasks_of(TaskKind.ESCORT)[0]
    assert escort.session_index is None
    assert escort.occupies_full_period is True
    assert escort.weekday == 4  # Thursday


def test_escort_outside_week_is_suppressed_not_dropped():
    demands = [TaskDemand(
        id="esc", kind=TaskKind.ESCORT, service_code=ServiceCode.ESCORT,
        task_date=date(2026, 2, 2), period=Period.AM, session_index=None,
        occupies_full_period=True, elder_id="e1", destination="RH")]
    gen = generate_demands(_snapshot(demands))
    assert gen.tasks_of(TaskKind.ESCORT) == []
    assert any("escort_outside_target_week" in (t.notes or "") for t in gen.suppressed)


def test_centre_duty_expands_by_required_count():
    demands = [TaskDemand(
        id="duty", kind=TaskKind.CENTRE_DUTY, service_code=ServiceCode.DUTY_AMC,
        weekday=1, period=Period.AM, required_count=3, centre="AMC")]
    gen = generate_demands(_snapshot(demands))
    duty_tasks = gen.tasks_of(TaskKind.CENTRE_DUTY)
    assert len(duty_tasks) == 3
    assert all(t.required_count == 1 for t in duty_tasks)
    reqs = duty_requirements(_snapshot(demands))
    assert len(reqs) == 1 and reqs[0].required_count == 3


def test_cancellation_and_hospitalisation_suppress_tasks():
    demands = [
        TaskDemand(id="live", kind=TaskKind.FIXED_SERVICE, service_code=ServiceCode.EXERCISE,
                   weekday=1, period=Period.AM, session_index=1, elder_id="e1"),
        TaskDemand(id="gone", kind=TaskKind.FIXED_SERVICE, service_code=ServiceCode.EXERCISE,
                   weekday=1, period=Period.AM, session_index=2, elder_id="e2",
                   status="hospitalised"),
    ]
    gen = generate_demands(_snapshot(demands))
    assert {t.id for t in gen.tasks} == {"live"}
    assert any(t.id == "gone" for t in gen.suppressed)


def test_availability_absence_becomes_leave_event_without_duplication():
    demands = [TaskDemand(id="x", kind=TaskKind.FIXED_SERVICE,
                          service_code=ServiceCode.EXERCISE, weekday=1,
                          period=Period.AM, session_index=1, elder_id="e1")]
    snap = _snapshot(
        demands,
        availability=[
            WorkerAvailability(worker_id="W1", available_date=WEEK_START,
                               period=Period.AM, is_available=False, reason="leave"),
            # already covered by the explicit change event below -> not duplicated
            WorkerAvailability(worker_id="W2", available_date=WEEK_START,
                               period=Period.AM, is_available=False, reason="leave"),
        ],
        change_events=[ChangeEvent(type=ChangeType.LEAVE, change_date=WEEK_START,
                                   period=Period.AM, worker_id="W2")],
    )
    gen = generate_demands(snap)
    leave_for = [(e.worker_id, e.change_date, e.period.value if e.period else None)
                 for e in gen.leave_events]
    assert leave_for.count(("W2", WEEK_START, "AM")) == 1
    assert ("W1", WEEK_START, "AM") in leave_for


def test_data_gaps_are_collected_and_deduped():
    gap = DataGap(kind="gender", entity_id="e1", message="unknown")
    demands = [TaskDemand(id="x", kind=TaskKind.ESCORT, service_code=ServiceCode.ESCORT,
                          task_date=WEEK_START, period=Period.AM, session_index=None,
                          occupies_full_period=True, elder_id="e1",
                          gender_requirement=GenderRequirement.UNKNOWN,
                          data_gaps=[gap])]
    snap = _snapshot(demands, data_gaps=[gap])  # same gap declared twice
    gen = generate_demands(snap)
    assert sum(1 for g in gen.data_gaps if g.entity_id == "e1") == 1
