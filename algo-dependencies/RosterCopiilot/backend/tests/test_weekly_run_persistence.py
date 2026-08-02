"""Phase 1B package B: durable weekly runs and review-state storage."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlmodel import Session
import pytest

from app.api import demo as demo_api
from app.domain import (
    ManualOverride,
    ManualOverridePin,
    ReviewDecisionRecord,
    VersionKind,
    canonical_json,
)
from app.exporter import prepare_generated_division_roster_export
from app.main import app
from app.scheduler import run_scheduler, version_content_hash
from app.services import state as state_service
from app.services.state import AppState
from app.services.weekly_demo import WeeklyRosterDemoBuilder
from app.store import RosterStore, WeeklyRunStoreError
from app.store.sqlite import WeeklyRunDocument, WeeklyRunScheduleVersion

from fixtures.paths import ESCORT_WORKBOOK_PATH, HC_TIMETABLE_WORKBOOK_PATH


@pytest.fixture(scope="module")
def durable_demo_run():
    build = WeeklyRosterDemoBuilder().build(
        hc_workbook_path=HC_TIMETABLE_WORKBOOK_PATH,
        escort_workbook_path=ESCORT_WORKBOOK_PATH,
        week_start=date(2026, 1, 5),
        changes_json="[]",
    )
    result = run_scheduler(build.snapshot)
    plan = prepare_generated_division_roster_export(
        division_layout=build.division,
        dataset=result.dataset,
        version=result.version,
        generated=result.generated,
    )
    return demo_api.DemoRun(
        run_id="phase1b-durable-run",
        build=build,
        result=result,
        review_version=plan.review_version,
        export_report=plan.report,
        export_plan=plan,
        upload_names={"hc_workbook": "hc.xlsx", "escort_workbook": "escort.xlsx"},
        master_data_version=7,
    )


def test_b01_weekly_run_survives_store_restart(tmp_path, durable_demo_run):
    db_path = tmp_path / "weekly.db"
    store = RosterStore(db_path)
    created = store.create_weekly_run(
        demo_api._weekly_run_record(deepcopy(durable_demo_run))
    )

    restarted = RosterStore(db_path)
    loaded = restarted.get_weekly_run(created.run_id)

    assert loaded is not None
    assert loaded.week_start == date(2026, 1, 5)
    assert loaded.master_data_version == 7
    assert loaded.current_version_id == created.current_version_id
    assert canonical_json(loaded.snapshot) == canonical_json(created.snapshot)
    assert canonical_json(loaded.dataset) == canonical_json(created.dataset)
    assert loaded.generated_payload == created.generated_payload
    assert loaded.latest_export_report == created.latest_export_report
    assert loaded.latest_content_hash == version_content_hash(loaded.versions[-1])


def test_b02_b03_versions_are_append_only_and_decisions_are_idempotent(
    tmp_path,
    durable_demo_run,
):
    store = RosterStore(tmp_path / "decisions.db")
    run = store.create_weekly_run(
        demo_api._weekly_run_record(deepcopy(durable_demo_run))
    )
    parent = next(v for v in run.versions if v.id == run.current_version_id)
    with Session(store.engine) as session:
        parent_before = session.get(WeeklyRunScheduleVersion, parent.id).payload_json

    child, report, plan = _manual_child(durable_demo_run, parent, suffix="approve")
    decision = ReviewDecisionRecord(
        run_id=run.run_id,
        source_version_id=parent.id,
        resulting_version_id=child.id,
        audit_id=parent.audit_items[0].id,
        action="approve",
        actor="reviewer@example.org",
        timestamp=datetime.now(timezone.utc),
        note="checked against source workbook",
        validator_result=report.validator_violations,
        content_hash=version_content_hash(child),
        idempotency_key="approve-audit-1",
    )

    first = store.save_weekly_run_decision(
        decision,
        result_version=child,
        latest_export_report=report.model_dump(mode="json"),
        latest_export_plan=demo_api._serialize_export_plan(plan),
    )
    duplicate = store.save_weekly_run_decision(
        decision.model_copy(update={"timestamp": decision.timestamp + timedelta(seconds=1)}),
        result_version=child,
        latest_export_report=report.model_dump(mode="json"),
        latest_export_plan=demo_api._serialize_export_plan(plan),
    )

    restarted = RosterStore(store.db_path)
    loaded = restarted.get_weekly_run(run.run_id)
    assert loaded is not None
    assert loaded.current_version_id == child.id
    assert len(loaded.versions) == len(run.versions) + 1
    assert len(loaded.decisions) == 1
    assert loaded.decisions[0].actor == "reviewer@example.org"
    assert loaded.decisions[0].note == "checked against source workbook"
    assert loaded.decisions[0].action == "approve"
    assert loaded.decisions[0].source_version_id == parent.id
    assert loaded.decisions[0].resulting_version_id == child.id
    assert loaded.decisions[0].validator_result == report.validator_violations
    assert duplicate.decision_id == first.decision_id
    with Session(store.engine) as session:
        parent_after = session.get(WeeklyRunScheduleVersion, parent.id).payload_json
    assert parent_after == parent_before

    with pytest.raises(ValueError, match="different review request"):
        store.save_weekly_run_decision(
            decision.model_copy(update={"note": "different request"}),
            result_version=child,
            latest_export_report=report.model_dump(mode="json"),
            latest_export_plan=demo_api._serialize_export_plan(plan),
        )


def test_b04_edited_decision_round_trips_linked_manual_override(
    tmp_path,
    durable_demo_run,
):
    store = RosterStore(tmp_path / "override.db")
    run = store.create_weekly_run(
        demo_api._weekly_run_record(deepcopy(durable_demo_run))
    )
    parent = next(v for v in run.versions if v.id == run.current_version_id)
    child, report, plan = _manual_child(durable_demo_run, parent, suffix="edit")
    edited_entry = child.entries[0]
    decision = ReviewDecisionRecord(
        run_id=run.run_id,
        source_version_id=parent.id,
        resulting_version_id=child.id,
        audit_id=parent.audit_items[0].id,
        action="edit",
        actor="supervisor@example.org",
        timestamp=datetime.now(timezone.utc),
        note="manual worker pin approved for this week",
        edited_entry_payload=edited_entry,
        validator_result=report.validator_violations,
        content_hash=version_content_hash(child),
        idempotency_key="edit-audit-1",
    )
    override = ManualOverride(
        id="ovr-phase1b-edit-1",
        scope="entry",
        pin=ManualOverridePin(
            worker_id=edited_entry.worker_id,
            date=edited_entry.schedule_date,
            period=edited_entry.period,
            service_code=edited_entry.service_code,
        ),
        action="pin_assignment",
        reason=decision.note,
        origin_audit_item_id=decision.audit_id,
        decision_id=decision.decision_id,
        run_id=run.run_id,
        source_version_id=parent.id,
        resulting_version_id=child.id,
        actor=decision.actor,
        created_at=decision.timestamp,
    )

    store.save_weekly_run_decision(
        decision,
        result_version=child,
        latest_export_report=report.model_dump(mode="json"),
        latest_export_plan=demo_api._serialize_export_plan(plan),
        manual_override=override,
    )

    restarted = RosterStore(store.db_path)
    loaded = restarted.get_weekly_run(run.run_id)
    assert loaded is not None
    assert loaded.decisions[0].edited_entry_payload == edited_entry
    assert loaded.manual_overrides == [override]
    assert loaded.manual_overrides[0].decision_id == decision.decision_id
    assert loaded.manual_overrides[0].origin_audit_item_id == decision.audit_id
    assert loaded.manual_overrides[0].run_id == run.run_id
    assert loaded.manual_overrides[0].resulting_version_id == child.id


def test_b03_rejects_stale_export_artifacts(tmp_path, durable_demo_run):
    store = RosterStore(tmp_path / "stale-artifacts.db")
    run = store.create_weekly_run(
        demo_api._weekly_run_record(deepcopy(durable_demo_run))
    )
    parent = next(v for v in run.versions if v.id == run.current_version_id)
    child, report, plan = _manual_child(durable_demo_run, parent, suffix="stale")
    decision = ReviewDecisionRecord(
        run_id=run.run_id,
        source_version_id=parent.id,
        resulting_version_id=child.id,
        audit_id=parent.audit_items[0].id,
        action="approve",
        actor="reviewer@example.org",
        timestamp=datetime.now(timezone.utc),
        content_hash=version_content_hash(child),
        idempotency_key="stale-export-report",
    )
    stale_report = report.model_dump(mode="json")
    stale_report["reconciliation"]["content_hash"] = "0" * 64

    with pytest.raises(ValueError, match="content hash is stale"):
        store.save_weekly_run_decision(
            decision,
            result_version=child,
            latest_export_report=stale_report,
            latest_export_plan=demo_api._serialize_export_plan(plan),
        )


def test_b05_post_and_restart_export_keep_existing_contract(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "api-restart.db"
    previous_state = state_service.get_state()
    monkeypatch.setenv("ROSTER_EXPORT_DIR", str(tmp_path / "exports"))
    state_service._STATE = AppState(db_path=db_path)
    client = TestClient(app)
    try:
        response = _post_weekly_run(client)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["export_url"] == (
            f"/api/demo/weekly-roster/{body['run_id']}/export"
        )
        assert body["export_token"] == body["run_id"]
        assert body["version"]["id"] == body["reconciliation"]["version_id"]
        assert body["parse_summary"]["hc_uploaded_file"] == "hc.xlsx"
        assert body["parse_summary"]["escort_uploaded_file"] == "escort.xlsx"

        state_service._STATE = AppState(db_path=db_path, load_existing=True)
        restarted_client = TestClient(app)
        exported = restarted_client.get(body["export_url"])
        assert exported.status_code == 200, exported.text
        assert exported.content.startswith(b"PK")
        assert "%E5%AF%A9%E6%A0%B8%E8%8D%89%E7%A8%BF" in exported.headers[
            "content-disposition"
        ]
    finally:
        state_service._STATE = previous_state


def test_b06_missing_and_corrupt_runs_fail_closed(tmp_path):
    db_path = tmp_path / "api-corrupt.db"
    previous_state = state_service.get_state()
    state_service._STATE = AppState(db_path=db_path)
    client = TestClient(app)
    try:
        missing = client.get("/api/demo/weekly-roster/not-a-run/export")
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "WEEKLY_RUN_NOT_FOUND"

        response = _post_weekly_run(client)
        assert response.status_code == 200, response.text
        run_id = response.json()["run_id"]
        store = state_service.get_state().store
        assert store is not None
        with Session(store.engine) as session:
            row = session.get(WeeklyRunDocument, run_id)
            assert row is not None
            row.snapshot_json = "{not valid json"
            session.add(row)
            session.commit()

        corrupt = client.get(f"/api/demo/weekly-roster/{run_id}/export")
        assert corrupt.status_code == 409
        assert corrupt.json()["detail"]["code"] == "WEEKLY_RUN_DATA_CORRUPT"
        assert corrupt.json()["detail"]["field"] == "snapshot"
        with pytest.raises(WeeklyRunStoreError):
            store.get_weekly_run(run_id)
    finally:
        state_service._STATE = previous_state


def _manual_child(demo_run, parent, *, suffix: str):
    child = parent.model_copy(deep=True, update={
        "id": f"v-manual-{suffix}",
        "kind": VersionKind.MANUAL_EDIT,
        "parent_version_id": parent.id,
        "created_at": parent.created_at + timedelta(seconds=1),
        "reconciliation": None,
    })
    plan = prepare_generated_division_roster_export(
        division_layout=demo_run.build.division,
        dataset=demo_run.result.dataset,
        version=child,
        generated=demo_run.result.generated,
    )
    return plan.review_version, plan.report, plan


def _post_weekly_run(client: TestClient):
    with (
        HC_TIMETABLE_WORKBOOK_PATH.open("rb") as hc,
        ESCORT_WORKBOOK_PATH.open("rb") as escort,
    ):
        return client.post(
            "/api/demo/weekly-roster",
            data={"week_start": "2026-01-05", "changes_json": "[]"},
            files={
                "hc_workbook": (
                    "../../unsafe/hc.xlsx",
                    hc,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
                "escort_workbook": (
                    "..\\unsafe\\escort.xlsx",
                    escort,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
            },
        )
