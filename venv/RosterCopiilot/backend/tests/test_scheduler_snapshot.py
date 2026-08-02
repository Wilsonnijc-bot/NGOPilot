from datetime import date

import pytest

from app.config.default_rules import DEFAULT_SCHEDULER_CONFIG
from app.domain import (
    ChangeEvent,
    ChangeType,
    DataGap,
    Elder,
    Employee,
    GenderRequirement,
    Period,
    SchedulerSnapshot,
    ServiceCode,
    TaskDemand,
    TaskKind,
    TaskSource,
    WeekPattern,
    WorkerAvailability,
)


WEEK_START = date(2026, 1, 5)


def test_scheduler_snapshot_can_be_constructed_without_excel():
    worker = Employee(
        id="w-1",
        display_name="Worker One",
        gender=None,
        skills=[ServiceCode.HOME_CLEAN, ServiceCode.ESCORT],
    )
    elder = Elder(
        id="e-1",
        display_name="Elder One",
        gender=None,
        district="Wan Chai",
        gender_requirement=GenderRequirement.UNKNOWN,
    )
    snapshot = SchedulerSnapshot(
        week_start=WEEK_START,
        config=DEFAULT_SCHEDULER_CONFIG,
        workers=[worker],
        elders=[elder],
        availability=[
            WorkerAvailability(
                worker_id=worker.id,
                available_date=WEEK_START,
                period=Period.AM,
                session_index=1,
            )
        ],
        demands=[
            TaskDemand(
                id="fixed-1",
                kind=TaskKind.FIXED_SERVICE,
                source=TaskSource.OPERATOR_INPUT,
                service_code=ServiceCode.EXERCISE,
                task_date=WEEK_START,
                weekday=1,
                period=Period.AM,
                session_index=1,
                elder_id=elder.id,
                pinned_worker_id=worker.id,
            )
        ],
        data_gaps=[
            DataGap(
                kind="gender",
                entity_id=worker.id,
                message="Worker gender is not known yet.",
            )
        ],
    )

    assert snapshot.week_start == WEEK_START
    assert snapshot.workers[0].gender is None
    assert snapshot.demands[0].service_code == ServiceCode.EXERCISE


def test_task_demand_represents_phase1_service_shapes():
    demands = [
        TaskDemand(
            id="fixed-service",
            kind=TaskKind.FIXED_SERVICE,
            service_code=ServiceCode.PERSONAL_CARE,
            task_date=WEEK_START,
            weekday=1,
            period=Period.AM,
            session_index=1,
            elder_id="e-1",
            exclusive_worker_id="w-1",
            gender_requirement=GenderRequirement.FEMALE,
        ),
        TaskDemand(
            id="hc-pattern",
            kind=TaskKind.HC_PATTERN,
            service_code=ServiceCode.HOME_CLEAN,
            weekday=2,
            period=Period.PM,
            session_index=2,
            week_pattern=WeekPattern.parse("1,3"),
            elder_id="e-2",
        ),
        TaskDemand(
            id="escort",
            kind=TaskKind.ESCORT,
            service_code=ServiceCode.ESCORT,
            task_date=WEEK_START,
            period=Period.AM,
            session_index=None,
            occupies_full_period=True,
            elder_id="e-3",
            destination="Hospital",
            preferred_worker_id="w-2",
            preference_strength="prefer",
        ),
        TaskDemand(
            id="duty",
            kind=TaskKind.CENTRE_DUTY,
            service_code=ServiceCode.DUTY_AMC,
            task_date=WEEK_START,
            weekday=1,
            period=Period.PM,
            required_count=1,
            centre="AMC",
        ),
        TaskDemand(
            id="meal",
            kind=TaskKind.MEAL_LOGISTICS,
            service_code=ServiceCode.MEAL,
            task_date=WEEK_START,
            weekday=1,
            period=Period.AM,
            route="meal-route-1",
            district="Wan Chai",
        ),
    ]

    assert {d.kind for d in demands} == {
        TaskKind.FIXED_SERVICE,
        TaskKind.HC_PATTERN,
        TaskKind.ESCORT,
        TaskKind.CENTRE_DUTY,
        TaskKind.MEAL_LOGISTICS,
    }
    assert demands[1].week_pattern is not None
    assert demands[2].occupies_full_period is True
    assert demands[2].session_index is None
    assert demands[3].centre == "AMC"
    assert demands[4].route == "meal-route-1"


def test_unknown_gender_and_skill_are_explicit_data_gaps():
    task = TaskDemand(
        id="escort-gap",
        kind=TaskKind.ESCORT,
        service_code=ServiceCode.ESCORT,
        task_date=WEEK_START,
        period=Period.AM,
        session_index=None,
        occupies_full_period=True,
        gender_requirement=GenderRequirement.UNKNOWN,
        data_gaps=[
            DataGap(
                kind="gender",
                entity_id="e-1",
                message="Elder gender is not available in current source data.",
            ),
            DataGap(
                kind="skill",
                entity_id="w-1",
                message="Escort qualification is not confirmed.",
            ),
        ],
    )

    assert task.gender_requirement == GenderRequirement.UNKNOWN
    assert {gap.kind for gap in task.data_gaps} == {"gender", "skill"}
    assert all(gap.blocking for gap in task.data_gaps)


def test_snapshot_can_carry_leave_and_cancellation_events():
    snapshot = SchedulerSnapshot(
        week_start=WEEK_START,
        change_events=[
            ChangeEvent(
                type=ChangeType.LEAVE,
                change_date=WEEK_START,
                period=Period.AM,
                worker_id="w-1",
                reason="sick leave",
            ),
            ChangeEvent(
                type=ChangeType.ELDER_CANCELLATION,
                change_date=WEEK_START,
                period=Period.PM,
                elder_id="e-1",
                reason="service cancelled",
            ),
        ],
    )

    assert [event.type for event in snapshot.change_events] == [
        ChangeType.LEAVE,
        ChangeType.ELDER_CANCELLATION,
    ]


def test_full_period_task_cannot_target_one_session():
    with pytest.raises(ValueError, match="full-period demand"):
        TaskDemand(
            id="invalid-escort",
            kind=TaskKind.ESCORT,
            service_code=ServiceCode.ESCORT,
            task_date=WEEK_START,
            period=Period.AM,
            session_index=1,
            occupies_full_period=True,
        )
