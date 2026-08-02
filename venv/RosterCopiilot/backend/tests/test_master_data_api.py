from __future__ import annotations

from fastapi.testclient import TestClient

from app.domain import (
    MasterDataSet,
    MasterElder,
    MasterWorker,
    ServiceCode,
    WorkerSkillFact,
    validate_master_data,
)
from app.main import app
from app.services import state as state_module
from app.services.state import AppState
from app.store import RosterStore


def _client_with_db(db_path):
    state_module.reset_state(db_path=db_path)
    return TestClient(app)


def _confirmed_worker(worker_id: str = "W900") -> dict:
    return {
        "id": worker_id,
        "display_name": "Test Worker",
        "gender": "F",
        "home_team": "EH",
        "skill_facts": [
            {
                "service_code": "HC",
                "level": "qualified",
                "source": "ngo_confirmed",
            }
        ],
        "saturday_team": "A",
        "employment_type": "full",
        "active": True,
        "work_start": "08:30:00",
        "work_end": "17:30:00",
    }


def _confirmed_elder(elder_id: str = "E9000") -> dict:
    return {
        "id": elder_id,
        "display_name": "Y珍",
        "gender": "F",
        "gender_requirement": "ANY",
        "district": "Wan Chai",
        "owning_unit": "EH",
        "status": "active",
    }


def test_store_persists_master_data_versions_after_restart(tmp_path):
    db_path = tmp_path / "roster.db"
    store = RosterStore(db_path)
    payload = MasterDataSet(
        workers=[
            MasterWorker(
                id="W900",
                display_name="Test Worker",
                gender="F",
                skill_facts=[
                    WorkerSkillFact(
                        service_code=ServiceCode.HOME_CLEAN,
                        level="qualified",
                        source="ngo_confirmed",
                    )
                ],
                saturday_team="A",
            )
        ],
        elders=[
            MasterElder(
                id="E9000",
                display_name="Y珍",
                gender="F",
                district="Wan Chai",
            )
        ],
    )

    first = store.save_master_data(
        payload, origin="test", issues=validate_master_data(payload))
    second_payload = payload.model_copy(
        update={"workers": [
            payload.workers[0].model_copy(update={"display_name": "Updated Worker"})
        ]}
    )
    second = store.save_master_data(
        second_payload,
        origin="test_update",
        issues=validate_master_data(second_payload),
    )

    restarted = RosterStore(db_path)
    current = restarted.get_master_data()

    assert first["version"] == 1
    assert second["version"] == 2
    assert current["version"] == 2
    assert current["payload"]["workers"][0]["display_name"] == "Updated Worker"
    assert restarted.list_master_data_versions()[0]["origin"] == "test"


def test_master_data_worker_and_elder_crud_survives_app_restart(tmp_path):
    db_path = tmp_path / "api.db"
    client = _client_with_db(db_path)

    bootstrapped = client.get("/api/master-data")
    assert bootstrapped.status_code == 200
    assert bootstrapped.json()["version"] == 1

    worker = _confirmed_worker()
    created_worker = client.post("/api/master-data/workers", json=worker)
    assert created_worker.status_code == 201
    worker["display_name"] = "Updated Worker"
    updated_worker = client.put("/api/master-data/workers/W900", json=worker)
    assert updated_worker.status_code == 200

    elder = _confirmed_elder()
    created_elder = client.post("/api/master-data/elders", json=elder)
    assert created_elder.status_code == 201
    elder["status"] = "paused"
    updated_elder = client.put("/api/master-data/elders/E9000", json=elder)
    assert updated_elder.status_code == 200

    leave = {
        "worker_id": "W900",
        "date": "2026-01-05",
        "scope": "AM",
        "reason": "approved leave",
    }
    assert client.post("/api/master-data/leave-events", json=leave).status_code == 201
    override = {
        "id": "MO9000",
        "scope": "recurring",
        "pin": {"worker_id": "W900", "period": "AM"},
        "action": "forbid_assignment",
        "reason": "不可加Case",
    }
    assert client.post("/api/master-data/manual-overrides", json=override).status_code == 201

    with state_module._STATE_LOCK:
        state_module._STATE = AppState(db_path=db_path, load_existing=True)
    restarted_client = TestClient(app)

    workers = restarted_client.get("/api/master-data/workers").json()
    elders = restarted_client.get("/api/master-data/elders").json()
    leave_events = restarted_client.get("/api/master-data/leave-events").json()
    overrides = restarted_client.get("/api/master-data/manual-overrides").json()

    assert next(row for row in workers if row["id"] == "W900")["display_name"] == "Updated Worker"
    assert next(row for row in elders if row["id"] == "E9000")["status"] == "paused"
    assert leave_events == [leave]
    assert overrides[0]["id"] == "MO9000"


def test_alias_collision_with_inactive_worker_is_not_an_error():
    """Only two ACTIVE workers sharing an alias is an error (spec §3.1)."""
    active = MasterWorker(
        id="W900", display_name="Active", aliases=["娥"], gender="F",
        skill_facts=[WorkerSkillFact(service_code=ServiceCode.HOME_CLEAN,
                                     level="qualified", source="ngo_confirmed")],
        saturday_team="A",
    )
    departed = MasterWorker(
        id="W901", display_name="Departed", aliases=["娥"], active=False,
    )
    issues = validate_master_data(MasterDataSet(workers=[active, departed]))
    assert not any(issue.code == "duplicate_worker_alias" for issue in issues)

    second_active = departed.model_copy(update={"active": True, "id": "W902"})
    issues = validate_master_data(
        MasterDataSet(workers=[active, second_active]))
    assert any(issue.code == "duplicate_worker_alias" and issue.level == "error"
               for issue in issues)


def test_master_data_put_rejects_broken_fk_without_advancing_version(tmp_path):
    client = _client_with_db(tmp_path / "api.db")
    current = client.get("/api/master-data").json()
    payload = current["payload"]
    payload["fixed_services"].append({
        "id": "FS9000",
        "elder_id": "E_DOES_NOT_EXIST",
        "service_code": "HC",
        "weekday": 1,
        "period": "AM",
        "session_index": 1,
        "week_pattern": {"kind": "weekly", "weeks": [], "raw": "weekly"},
        "active": True,
        "source_ref": "test",
        "source_confidence": "high",
    })

    rejected = client.put("/api/master-data", json=payload)
    still_current = client.get("/api/master-data").json()

    assert rejected.status_code == 422
    assert any(
        issue["code"] == "broken_fk"
        for issue in rejected.json()["detail"]["issues"]
    )
    assert still_current["version"] == current["version"]
