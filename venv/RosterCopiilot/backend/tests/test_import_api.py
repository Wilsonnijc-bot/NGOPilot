from __future__ import annotations

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from app.services import state as state_module
from fixtures.paths import (
    DIVISION_WORKBOOK_PATH,
    ESCORT_WORKBOOK_PATH,
    HC_TIMETABLE_WORKBOOK_PATH,
)


def test_multipart_import_api_persists_batch_and_resolutions(tmp_path):
    state_module.reset_state(db_path=tmp_path / "api.db")
    client = TestClient(app)
    with (
        DIVISION_WORKBOOK_PATH.open("rb") as division,
        HC_TIMETABLE_WORKBOOK_PATH.open("rb") as hc,
        ESCORT_WORKBOOK_PATH.open("rb") as escort,
    ):
        response = client.post(
            "/api/import/workbooks",
            files={
                "division_workbook": (
                    DIVISION_WORKBOOK_PATH.name,
                    division,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
                "hc_workbook": (
                    HC_TIMETABLE_WORKBOOK_PATH.name,
                    hc,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
                "escort_workbook": (
                    ESCORT_WORKBOOK_PATH.name,
                    escort,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
            },
        )
    assert response.status_code == 200, response.text
    batch = response.json()
    assert batch["summary"]["silently_dropped_cells"] == 0
    assert batch["canonical_preview"]["employees"]["count"] == 46
    assert batch["canonical_preview"]["escort_requests"]["count"] == 111
    assert batch["ambiguity_count"] >= batch["blocking_ambiguity_count"] >= 1
    assert all("rostercopiilot_import_" not in name for name in batch["source_names"])

    fetched = client.get(f"/api/import/batches/{batch['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["summary"]["parsed_count"] == batch["summary"]["parsed_count"]
    assert fetched.json()["pending_ambiguity_count"] == batch["ambiguity_count"]

    ambiguities = client.get(f"/api/import/ambiguities?batch_id={batch['id']}").json()
    assert ambiguities
    resolved = client.post(
        f"/api/import/ambiguities/{ambiguities[0]['id']}/resolution",
        json={"status": "resolved", "resolution": {"answer": "confirmed"}},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"

    alias = client.post(
        "/api/import/resolutions",
        json={"entity_type": "worker", "alias": "娥", "canonical_id": "W001"},
    )
    assert alias.status_code == 200
    assert alias.json()["canonical_id"] == "W001"


def test_default_import_then_ngo_format_export_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTER_EXPORT_DIR", str(tmp_path / "exports"))
    state_module.reset_state(db_path=tmp_path / "api.db")
    client = TestClient(app)

    import_response = client.post("/api/import/workbooks?use_default_docs=true")
    assert import_response.status_code == 200, import_response.text
    batch = import_response.json()
    assert batch["canonical_preview"]["employees"]["count"] == 46

    batches = client.get("/api/import/batches").json()
    assert batches[-1]["id"] == batch["id"]
    assert batches[-1]["blocking_ambiguity_count"] >= 1

    ambiguities = client.get(
        f"/api/import/ambiguities?batch_id={batch['id']}"
    ).json()
    target = next((a for a in ambiguities if a["severity"] == "blocking"),
                  ambiguities[0])
    resolved = client.post(
        f"/api/import/ambiguities/{target['id']}/resolution",
        json={
            "status": "resolved",
            "resolution": {"demo_acknowledged": True},
            "note": "API demo acknowledgement; not semantic promotion",
        },
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"

    export_response = client.post("/api/export/ngo-format", json={})
    assert export_response.status_code == 200, export_response.text
    assert export_response.headers["content-type"].startswith(
        "application/vnd.openxmlformats"
    )
    assert list((tmp_path / "exports").glob("ngo_division_*.xlsx"))


def test_import_api_returns_structured_error_for_bad_division_workbook(tmp_path):
    state_module.reset_state(db_path=tmp_path / "api.db")
    client = TestClient(app)
    bad_workbook = tmp_path / "bad.xlsx"
    Workbook().save(bad_workbook)

    with bad_workbook.open("rb") as upload:
        response = client.post(
            "/api/import/workbooks",
            files={
                "division_workbook": (
                    bad_workbook.name,
                    upload,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
            },
        )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "MissingSheetError"
    assert "恆常服務" in detail["message"]
