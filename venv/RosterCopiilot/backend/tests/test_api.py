"""API smoke tests via FastAPI TestClient."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.scheduler import representative_snapshot
from app.services import state as state_module


@pytest.fixture()
def client():
    state_module.reset_state()  # isolate API state per test
    return TestClient(app)


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["current_version"]


def test_mock_data_shape_for_frontend(client):
    """Fields the existing frontend reads must stay present."""
    d = client.get("/api/schedule/mock-data").json()
    assert {"employees", "elders", "fixed_services"} <= d.keys()
    assert d["employees"][0]["display_name"]
    assert "gender_requirement" in d["elders"][0]
    assert "exclusive_worker_id" in d["elders"][0]


def test_generate_and_current(client):
    v = client.post("/api/schedule/generate", json={"changes": []}).json()
    assert v["entries"] and v["summary"]["hard_constraint_violations"] == 0
    e = v["entries"][0]
    assert {"schedule_date", "period", "service_code", "worker_name"} <= e.keys()
    cur = client.get("/api/schedule/current").json()
    assert cur["id"] == v["id"]


def test_solve_accepts_scheduler_snapshot_without_importing_workbooks(client):
    snapshot = representative_snapshot()
    r = client.post("/api/schedule/solve", json=snapshot.model_dump(mode="json"))
    assert r.status_code == 200
    body = r.json()
    assert body["version"]["entries"]
    assert body["hard_constraint_violations"] == 0
    assert body["generated_counts"]["escort"] >= 3
    assert body["data_gap_count"] >= 1


def test_simulate_does_not_mutate_current(client):
    before = client.get("/api/schedule/current").json()["id"]
    evs = client.get("/api/changes/examples").json()
    r = client.post("/api/changes/simulate", json={"changes": evs})
    assert r.status_code == 200
    body = r.json()
    assert body["impact_reports"] and body["summary"]["requires_review"] is True
    assert client.get("/api/schedule/current").json()["id"] == before


def test_apply_creates_new_current_version(client):
    evs = client.get("/api/changes/examples").json()
    body = client.post("/api/changes/apply", json={"changes": evs}).json()
    assert client.get("/api/schedule/current").json()["id"] == body["version"]["id"]
    versions = client.get("/api/schedule/versions").json()
    assert len(versions) == 2
    assert any(v["kind"] == "repair" and v["is_current"] for v in versions)


def test_audit_decision_flow(client):
    evs = client.get("/api/changes/examples").json()
    client.post("/api/changes/apply", json={"changes": evs})
    queue = client.get("/api/schedule/audit").json()
    item = next(a for a in queue if a["kind"] == "replacement_suggestion"
                and a["status"] == "pending")
    ok = client.post(f"/api/schedule/audit/{item['id']}/decision",
                     json={"status": "approved"})
    assert ok.status_code == 200
    missing = client.post("/api/schedule/audit/nope/decision",
                          json={"status": "approved"})
    assert missing.status_code == 404
    reject_no_note = next(a for a in client.get("/api/schedule/audit").json()
                          if a["status"] == "pending" and a["suggested_entry"])
    r = client.post(f"/api/schedule/audit/{reject_no_note['id']}/decision",
                    json={"status": "rejected"})
    assert r.status_code == 422


def test_regenerate_with_seed(client):
    a = client.post("/api/dataset/regenerate", json={"seed": 42}).json()
    b = client.post("/api/dataset/regenerate", json={"seed": 42}).json()
    assert a["employees"] == b["employees"] == 52
    am, bm = a["baseline_metrics"], b["baseline_metrics"]
    am.pop("runtime_ms"), bm.pop("runtime_ms")  # wall-clock is not deterministic
    assert am == bm


def test_export_endpoints(client):
    r = client.get("/api/export/current")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
    r2 = client.post("/api/export/excel", json={})
    assert r2.status_code == 200
    r3 = client.post("/api/export/excel", json={"version_id": "missing"})
    assert r3.status_code == 404
    r4 = client.post("/api/export/assignment-grid")
    assert r4.status_code == 200
    assert r4.headers["content-type"].startswith("application/vnd.openxmlformats")
