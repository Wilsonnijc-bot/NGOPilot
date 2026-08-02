"""Master-data-driven SchedulerSnapshot integration tests."""
from __future__ import annotations

from datetime import date

from app.domain import (
    ManualOverride,
    ManualOverridePin,
    MasterDataSet,
    MasterElder,
    MasterFixedService,
    MasterWorker,
    Period,
    ServiceCode,
    WorkerSkillFact,
)
from app.scheduler import run_scheduler
from app.services.master_data_bridge import build_scheduler_snapshot_from_master_data

WEEK_START = date(2026, 1, 5)


def _worker(worker_id: str, *, skills: list[ServiceCode]) -> MasterWorker:
    return MasterWorker(
        id=worker_id,
        display_name=worker_id,
        gender="F",
        skill_facts=[
            WorkerSkillFact(
                service_code=skill,
                level="qualified",
                source="ngo_confirmed",
            )
            for skill in skills
        ],
        saturday_team="A",
    )


def _elder() -> MasterElder:
    return MasterElder(
        id="E1",
        display_name="Y珍",
        gender="F",
        district="Wan Chai",
    )


def test_master_data_skill_edit_changes_snapshot_scheduling():
    master_data = MasterDataSet(
        workers=[
            _worker("W1", skills=[]),
            _worker("W2", skills=[ServiceCode.HOME_CLEAN]),
        ],
        elders=[_elder()],
        fixed_services=[
            MasterFixedService(
                id="FS1",
                elder_id="E1",
                service_code=ServiceCode.HOME_CLEAN,
                weekday=1,
                period=Period.AM,
                session_index=1,
                assigned_worker_id="W1",
                source_ref="test",
            )
        ],
    )

    result = run_scheduler(build_scheduler_snapshot_from_master_data(
        master_data,
        week_start=WEEK_START,
    ))

    active = [
        entry for entry in result.version.entries
        if entry.origin_fixed_service_id == "FS1"
        and entry.status.value in {"scheduled", "needs_review"}
    ]
    assert active
    assert all(entry.worker_id != "W1" for entry in active)
    assert active[0].worker_id == "W2"
    assert not result.violations


def test_master_data_forbid_override_removes_worker_capacity():
    master_data = MasterDataSet(
        workers=[
            _worker("W1", skills=[ServiceCode.HOME_CLEAN]),
            _worker("W2", skills=[ServiceCode.HOME_CLEAN]),
        ],
        elders=[_elder()],
        fixed_services=[
            MasterFixedService(
                id="FS1",
                elder_id="E1",
                service_code=ServiceCode.HOME_CLEAN,
                weekday=1,
                period=Period.AM,
                session_index=1,
                assigned_worker_id="W1",
                source_ref="test",
            )
        ],
        manual_overrides=[
            ManualOverride(
                id="MO1",
                scope="recurring",
                pin=ManualOverridePin(
                    worker_id="W1",
                    weekday=1,
                    period=Period.AM,
                ),
                action="forbid_assignment",
                reason="不可加Case",
            )
        ],
    )

    result = run_scheduler(build_scheduler_snapshot_from_master_data(
        master_data,
        week_start=WEEK_START,
    ))

    active = [
        entry for entry in result.version.entries
        if entry.status.value in {"scheduled", "needs_review"}
    ]
    assert active
    assert all(
        not (
            entry.worker_id == "W1"
            and entry.schedule_date == WEEK_START
            and entry.period == Period.AM
        )
        for entry in active
    )
    assert any(entry.worker_id == "W2" for entry in active)
    assert not result.violations
