"""Phase 1B package C: durable weekly review and revalidation API."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date

from fastapi.testclient import TestClient
import pytest

from app.api import demo as demo_api
from app.services.weekly_review import WeeklyReviewCommand, apply_weekly_review
from app.store import WeeklyRunVersionConflictError
from app.domain import (
    AuditItem,
    AuditKind,
    AuditStatus,
    EntryStatus,
    GENDER_SENSITIVE,
    Gender,
    GenderRequirement,
    ReviewReasonCode,
    SKILL_GATED,
    ServiceCode,
    Severity,
    canonical_json,
)
from app.exporter import prepare_generated_division_roster_export
from app.main import app
from app.scheduler import run_scheduler
from app.services import state as state_service
from app.services.state import AppState
from app.services.weekly_demo import WeeklyRosterDemoBuilder

from fixtures.paths import ESCORT_WORKBOOK_PATH, HC_TIMETABLE_WORKBOOK_PATH


@pytest.fixture(scope="module")
def review_demo_run():
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
        run_id="phase1b-review-api",
        build=build,
        result=result,
        review_version=plan.review_version,
        export_report=plan.report,
        export_plan=plan,
        upload_names={"hc_workbook": "hc.xlsx", "escort_workbook": "escort.xlsx"},
        master_data_version=9,
    )


@pytest.fixture()
def review_api(tmp_path, review_demo_run):
    previous = state_service.get_state()
    state_service._STATE = AppState(db_path=tmp_path / "review.db")
    record = state_service.get_state().store.create_weekly_run(
        demo_api._weekly_run_record(deepcopy(review_demo_run))
    )
    client = TestClient(app)
    try:
        yield client, record
    finally:
        state_service._STATE = previous


@pytest.fixture()
def c04_api(tmp_path, review_demo_run):
    """Explicit audit-linked entries and workers for the three hard-rule cases."""

    run = deepcopy(review_demo_run)
    dataset = run.result.dataset
    current = run.review_version
    skill_entry = next(
        item for item in current.entries
        if item.status in {EntryStatus.SCHEDULED, EntryStatus.NEEDS_REVIEW}
        and item.service_code in SKILL_GATED
    )
    gender_source = next(
        item for item in current.entries
        if item.status == EntryStatus.SCHEDULED
        and item.worker_id in dataset.employee_map()
        and not item.data_gap_ids
    )
    gender_entry = gender_source.model_copy(deep=True, update={
        "revision": max(
            item.revision for item in current.entries
            if item.demand_id == gender_source.demand_id
        ) + 1,
        "service_code": ServiceCode.PERSONAL_CARE,
        "elder_id": dataset.elders[0].id,
        "elder_name": dataset.elders[0].display_name,
    })
    current.entries = [
        item for item in current.entries if item.demand_id != gender_source.demand_id
    ] + [gender_entry]
    gender_worker = dataset.employee_map()[gender_entry.worker_id]
    gender_worker.gender = Gender.MALE
    gender_worker.skills = sorted(
        {*gender_worker.skills, ServiceCode.PERSONAL_CARE},
        key=lambda item: item.value,
    )
    elder = dataset.elder_map()[gender_entry.elder_id]
    elder.gender_requirement = GenderRequirement.MALE

    no_skill = dataset.employees[0].model_copy(deep=True, update={
        "id": "C04-NO-SKILL",
        "display_name": "C04 無技能同工",
        "skills": [],
        "seed_skills": [],
        "gender": gender_worker.gender,
    })
    wrong_gender = dataset.employees[0].model_copy(deep=True, update={
        "id": "C04-WRONG-GENDER",
        "display_name": "C04 性別不符同工",
        "skills": list(ServiceCode),
        "seed_skills": [],
        "gender": Gender.FEMALE,
    })
    dataset.employees.extend([no_skill, wrong_gender])

    time_entry = next(
        item for item in current.entries
        if item.status in {EntryStatus.SCHEDULED, EntryStatus.NEEDS_REVIEW}
        and any(
            other.id != item.id
            and other.worker_id
            and other.schedule_date == item.schedule_date
            and other.period == item.period
            and (
                other.session_index is None
                or item.session_index is None
                or other.session_index == item.session_index
            )
            for other in current.entries
        )
    )
    for label, entry in (
        ("skill", skill_entry),
        ("gender", gender_entry),
        ("time", time_entry),
    ):
        current.audit_items.append(AuditItem(
            id=f"pending-c04-{label}",
            kind=AuditKind.TEMPLATE_ISSUE,
            severity=Severity.WARNING,
            blocking=False,
            reason=f"C04-{label}",
            demand_ids=[entry.demand_id],
            entry_ids=[entry.id],
            evidence_refs=[item.id for item in entry.source_evidence],
        ))
    plan = prepare_generated_division_roster_export(
        division_layout=run.build.division,
        dataset=dataset,
        version=current,
        generated=run.result.generated,
    )
    run.review_version = plan.review_version
    run.export_report = plan.report
    run.export_plan = plan

    previous = state_service.get_state()
    state_service._STATE = AppState(db_path=tmp_path / "c04.db")
    record = state_service.get_state().store.create_weekly_run(
        demo_api._weekly_run_record(run)
    )
    try:
        yield TestClient(app), record
    finally:
        state_service._STATE = previous


def _suggestion(record):
    current = next(item for item in record.versions if item.id == record.current_version_id)
    return next(
        item for item in current.audit_items
        if item.status == AuditStatus.PENDING and item.suggested_entry is not None
    )


def _command(record, audit, *, action="approve", key="review-1", **extra):
    return {
        "source_version_id": record.current_version_id,
        "content_hash": record.latest_content_hash,
        "idempotency_key": key,
        "actor": "supervisor@example.org",
        "action": action,
        "audit_id": audit.id,
        **extra,
    }


def test_c01_get_run_survives_restart(review_api):
    client, record = review_api
    first = client.get(f"/api/demo/weekly-roster/{record.run_id}")
    assert first.status_code == 200, first.text
    first_body = first.json()

    db_path = state_service.get_state().store.db_path
    state_service._STATE = AppState(db_path=db_path, load_existing=True)
    restarted = TestClient(app).get(f"/api/demo/weekly-roster/{record.run_id}")

    assert restarted.status_code == 200, restarted.text
    body = restarted.json()
    assert body["version"]["id"] == record.current_version_id
    assert body["version"] == first_body["version"]
    assert body["reconciliation"] == body["export_report"]["reconciliation"]
    assert body["reconciliation"]["content_hash"] == record.latest_content_hash


def test_workspace_pointer_and_immutable_archive_survive_restart(review_api):
    client, record = review_api

    empty = client.get("/api/demo/workspace")
    assert empty.status_code == 200
    assert empty.json()["current_run_id"] is None

    saved = client.put(
        "/api/demo/workspace",
        json={"run_id": record.run_id},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["current_run_id"] == record.run_id

    created = client.post(
        "/api/demo/archives",
        json={"run_id": record.run_id, "title": "主管覆核前"},
    )
    assert created.status_code == 200, created.text
    archive = created.json()
    assert archive["title"] == "主管覆核前"
    assert archive["source_version_id"] == record.current_version_id
    assert archive["content_hash"] == record.latest_content_hash

    audit = _suggestion(record)
    decision = client.post(
        f"/api/demo/weekly-roster/{record.run_id}/review-decisions",
        json=_command(record, audit, key="archive-proof"),
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["version"]["id"] != archive["source_version_id"]

    db_path = state_service.get_state().store.db_path
    state_service._STATE = AppState(db_path=db_path, load_existing=True)
    restarted = TestClient(app)
    workspace = restarted.get("/api/demo/workspace")
    listing = restarted.get("/api/demo/archives")
    frozen = restarted.get(f"/api/demo/archives/{archive['archive_id']}")

    assert workspace.status_code == 200
    assert workspace.json()["current_run_id"] == record.run_id
    assert listing.status_code == 200
    assert listing.json()["archives"][0]["archive_id"] == archive["archive_id"]
    assert frozen.status_code == 200
    assert frozen.json()["snapshot"]["version"]["id"] == archive["source_version_id"]
    assert frozen.json()["snapshot"]["reconciliation"]["content_hash"] == archive["content_hash"]


def test_archive_creates_independent_editable_copy(review_api):
    client, record = review_api
    source_audit = _suggestion(record)
    created = client.post(
        "/api/demo/archives",
        json={"run_id": record.run_id, "title": "待續工作"},
    )
    assert created.status_code == 200, created.text
    archive = created.json()
    frozen_before = client.get(f"/api/demo/archives/{archive['archive_id']}").json()

    original_decision = client.post(
        f"/api/demo/weekly-roster/{record.run_id}/review-decisions",
        json=_command(record, source_audit, key="original-after-archive"),
    )
    assert original_decision.status_code == 200, original_decision.text
    assert original_decision.json()["version"]["id"] != archive["source_version_id"]

    forked = client.post(
        f"/api/demo/archives/{archive['archive_id']}/editable-copy"
    )
    assert forked.status_code == 200, forked.text
    body = forked.json()
    assert body["run_id"] != record.run_id
    assert body["version"]["id"] != archive["source_version_id"]
    assert body["editable_copy"] == {
        "archive_id": archive["archive_id"],
        "source_run_id": record.run_id,
        "source_version_id": archive["source_version_id"],
        "created_run_id": body["run_id"],
        "workspace_saved_at": body["editable_copy"]["workspace_saved_at"],
    }
    copied_audit = next(
        item for item in body["audit_items"]
        if item["status"] == "pending"
        and item["suggested_entry"] is not None
        and item["demand_ids"] == source_audit.demand_ids
    )
    workspace = client.get("/api/demo/workspace")
    assert workspace.status_code == 200
    assert workspace.json()["current_run_id"] == body["run_id"]

    continued = client.post(
        f"/api/demo/weekly-roster/{body['run_id']}/review-decisions",
        json={
            "source_version_id": body["version"]["id"],
            "content_hash": body["reconciliation"]["content_hash"],
            "idempotency_key": "continue-from-archive-copy",
            "actor": "supervisor@example.org",
            "action": "approve",
            "audit_id": copied_audit["id"],
        },
    )
    assert continued.status_code == 200, continued.text
    assert continued.json()["version"]["id"] != body["version"]["id"]

    frozen_after = client.get(f"/api/demo/archives/{archive['archive_id']}")
    assert frozen_after.status_code == 200
    assert frozen_after.json() == frozen_before


def test_c02_approve_creates_child_and_keeps_parent_immutable(review_api):
    client, record = review_api
    audit = _suggestion(record)
    parent_before = canonical_json(
        next(item for item in record.versions if item.id == record.current_version_id)
    )

    response = client.post(
        f"/api/demo/weekly-roster/{record.run_id}/review-decisions",
        json=_command(record, audit),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version"]["kind"] == "manual_edit"
    assert body["version"]["parent_version_id"] == record.current_version_id
    assert body["decision"]["source_version_id"] == record.current_version_id
    stored = state_service.get_state().store.get_weekly_run(record.run_id)
    assert stored is not None
    parent_after = next(item for item in stored.versions if item.id == record.current_version_id)
    assert canonical_json(parent_after) == parent_before

    replay = client.post(
        f"/api/demo/weekly-roster/{record.run_id}/review-decisions",
        json=_command(record, audit),
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["decision"]["decision_id"] == body["decision"]["decision_id"]


def test_approved_suggestion_exports_as_clean_scheduled_entry(review_api):
    client, record = review_api
    current = next(
        item for item in record.versions if item.id == record.current_version_id
    )
    dependents = {
        dependency
        for item in current.audit_items
        for dependency in item.depends_on
    }
    audit = next(
        item for item in current.audit_items
        if item.status == AuditStatus.PENDING
        and item.suggested_entry is not None
        and item.suggested_entry.demand_id
        and item.suggested_entry.review_reasons
        and not item.suggested_entry.data_gap_ids
        and not item.suggested_entry.constraint_flags
        and not item.depends_on
        and item.id not in dependents
    )

    response = client.post(
        f"/api/demo/weekly-roster/{record.run_id}/review-decisions",
        json=_command(record, audit, key="approve-clears-review-state"),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    entry = next(
        item for item in body["version"]["entries"]
        if item["demand_id"] == audit.suggested_entry.demand_id
        and item["entry_role"] == "current"
    )
    assert entry["status"] == "scheduled"
    assert entry["review_reasons"] == []
    assert body["decision"]["action"] == "approve"
    assert audit.id in body["decision"]["audit_ids"]
    failures = [
        item for item in body["export_report"]["unassigned_items"]
        if item.get("is_export_failure")
    ]
    assert failures == []
    assert body["reconciliation"]["errors"] == []


def _race_two_review_requests(record, monkeypatch, *, keys):
    """Send two review decisions that both compute against the same version.

    A barrier after apply_weekly_review guarantees neither request commits
    before the other has finished computing, which is exactly the window the
    double-click race exploits.
    """

    audit = _suggestion(record)
    barrier = threading.Barrier(2, timeout=180)
    original_apply = demo_api.apply_weekly_review

    def synced_apply(*args, **kwargs):
        outcome = original_apply(*args, **kwargs)
        barrier.wait()
        return outcome

    monkeypatch.setattr(demo_api, "apply_weekly_review", synced_apply)

    def attempt(key):
        return TestClient(app).post(
            f"/api/demo/weekly-roster/{record.run_id}/review-decisions",
            json=_command(record, audit, key=key),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(attempt, keys))
    monkeypatch.setattr(demo_api, "apply_weekly_review", original_apply)
    return responses


def test_concurrent_reviews_with_different_keys_commit_exactly_once(
    review_api,
    monkeypatch,
):
    client, record = review_api
    responses = _race_two_review_requests(
        record, monkeypatch, keys=["race-key-a", "race-key-b"]
    )

    statuses = sorted(item.status_code for item in responses)
    assert statuses == [200, 409], [item.text for item in responses]
    winner = next(item for item in responses if item.status_code == 200)
    loser = next(item for item in responses if item.status_code == 409)
    assert loser.json()["detail"]["code"] == "STALE_SCHEDULE_VERSION"

    stored = state_service.get_state().store.get_weekly_run(record.run_id)
    children = [
        item for item in stored.versions
        if item.parent_version_id == record.current_version_id
    ]
    assert len(children) == 1
    assert len(stored.decisions) == 1
    assert stored.current_version_id == children[0].id
    assert stored.current_version_id == winner.json()["version"]["id"]
    assert stored.decisions[0].decision_id == winner.json()["decision"]["decision_id"]
    assert stored.manual_overrides == []

    fresh = client.get(f"/api/demo/weekly-roster/{record.run_id}")
    assert fresh.status_code == 200, fresh.text
    assert fresh.json()["version"]["id"] == stored.current_version_id


def test_concurrent_retries_with_same_key_resolve_to_one_decision(
    review_api,
    monkeypatch,
):
    _, record = review_api
    responses = _race_two_review_requests(
        record, monkeypatch, keys=["same-key-retry", "same-key-retry"]
    )

    assert [item.status_code for item in responses] == [200, 200], [
        item.text for item in responses
    ]
    decision_ids = {item.json()["decision"]["decision_id"] for item in responses}
    assert len(decision_ids) == 1
    assert False in {item.json()["idempotent_replay"] for item in responses}

    stored = state_service.get_state().store.get_weekly_run(record.run_id)
    children = [
        item for item in stored.versions
        if item.parent_version_id == record.current_version_id
    ]
    assert len(children) == 1
    assert len(stored.decisions) == 1
    assert stored.decisions[0].decision_id == decision_ids.pop()
    assert stored.current_version_id == children[0].id
    for item in responses:
        assert item.json()["version"]["id"] == stored.current_version_id


def test_review_request_on_stale_version_is_rejected(review_api):
    client, record = review_api
    audit = _suggestion(record)
    first = client.post(
        f"/api/demo/weekly-roster/{record.run_id}/review-decisions",
        json=_command(record, audit, key="stale-check-first"),
    )
    assert first.status_code == 200, first.text

    stale = client.post(
        f"/api/demo/weekly-roster/{record.run_id}/review-decisions",
        json=_command(record, audit, key="stale-check-second"),
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"]["code"] == "STALE_SCHEDULE_VERSION"

    stored = state_service.get_state().store.get_weekly_run(record.run_id)
    assert len(stored.decisions) == 1
    assert len([
        item for item in stored.versions
        if item.parent_version_id == record.current_version_id
    ]) == 1


def test_lost_cas_rolls_back_without_partial_state(review_api):
    _, record = review_api
    audit = _suggestion(record)
    store = state_service.get_state().store
    restored = demo_api._reconstitute_demo_run(record, rebuild_preflight=False)
    outcome_a = apply_weekly_review(
        record,
        restored.build.division,
        WeeklyReviewCommand(**_command(record, audit, key="cas-winner")),
    )
    outcome_b = apply_weekly_review(
        record,
        restored.build.division,
        WeeklyReviewCommand(**_command(record, audit, key="cas-loser")),
    )

    store.save_weekly_run_decision(
        outcome_a.decision,
        result_version=outcome_a.version,
        latest_export_report=outcome_a.report.model_dump(mode="json"),
        latest_export_plan=demo_api._serialize_export_plan(outcome_a.plan),
    )
    with pytest.raises(WeeklyRunVersionConflictError) as conflict:
        store.save_weekly_run_decision(
            outcome_b.decision,
            result_version=outcome_b.version,
            latest_export_report=outcome_b.report.model_dump(mode="json"),
            latest_export_plan=demo_api._serialize_export_plan(outcome_b.plan),
        )
    assert conflict.value.code == "STALE_SCHEDULE_VERSION"
    assert conflict.value.as_detail()["current_version_id"] == outcome_a.version.id

    stored = store.get_weekly_run(record.run_id)
    stored_ids = {item.id for item in stored.versions}
    assert outcome_a.version.id in stored_ids
    assert outcome_b.version.id not in stored_ids
    assert [item.decision_id for item in stored.decisions] == [
        outcome_a.decision.decision_id
    ]
    assert stored.manual_overrides == []
    assert stored.current_version_id == outcome_a.version.id
    assert stored.latest_content_hash == outcome_a.decision.content_hash


def test_review_response_does_not_rebuild_after_successful_commit(
    review_api,
    monkeypatch,
):
    client, record = review_api
    audit = _suggestion(record)

    def unexpected_reload(_run_id):
        raise AssertionError("review response reloaded the committed run")

    original_preflight = demo_api.prepare_generated_division_roster_export

    def unexpected_parent_preflight(**_kwargs):
        raise AssertionError("review request rebuilt the unchanged parent preflight")

    monkeypatch.setattr(demo_api, "_load_demo_run_for_api", unexpected_reload)
    monkeypatch.setattr(
        demo_api,
        "prepare_generated_division_roster_export",
        unexpected_parent_preflight,
    )
    command = _command(record, audit, key="no-post-commit-rebuild")
    response = client.post(
        f"/api/demo/weekly-roster/{record.run_id}/review-decisions",
        json=command,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version"]["id"] == body["decision"]["resulting_version_id"]
    assert body["reconciliation"]["content_hash"] == body["decision"]["content_hash"]

    monkeypatch.setattr(
        demo_api,
        "prepare_generated_division_roster_export",
        original_preflight,
    )
    replay = client.post(
        f"/api/demo/weekly-roster/{record.run_id}/review-decisions",
        json=command,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["idempotent_replay"] is True


def test_c03_reject_requires_note_and_records_hard_bypass(review_api):
    client, record = review_api
    audit = _suggestion(record)
    missing_note = client.post(
        f"/api/demo/weekly-roster/{record.run_id}/review-decisions",
        json=_command(record, audit, action="reject"),
    )
    assert missing_note.status_code == 422

    response = client.post(
        f"/api/demo/weekly-roster/{record.run_id}/review-decisions",
        json=_command(
            record,
            audit,
            action="reject",
            note="來源資料未足以接受此替補",
        ),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"]["hard_bypass"] is True
    decided = [
        item
        for item in body["audit_items"]
        if item.get("decision_id") == body["decision"]["decision_id"]
    ]
    assert decided
    assert all(item["status"] == "rejected" for item in decided)
    disposition = next(
        item for item in body["reconciliation"]["dispositions"]
        if item["demand_id"] == audit.demand_ids[0]
    )
    assert disposition["disposition"] in {"scheduled", "suppressed_with_audit"}
    entry = next(
        item for item in body["version"]["entries"]
        if item["id"] == disposition["entry_id"]
    )
    assert "supervisor_hard_bypass" in entry["constraint_flags"]
    assert body["reconciliation"]["errors"] == []


def test_unassigned_blocker_can_be_hard_bypassed(review_api):
    client, record = review_api
    current = next(item for item in record.versions if item.id == record.current_version_id)
    audit = next(
        item for item in current.audit_items
        if item.kind == AuditKind.UNASSIGNED_TASK
        and item.status == AuditStatus.PENDING
        and any(
            entry.demand_id in item.demand_ids
            and entry.status == EntryStatus.UNASSIGNED
            for entry in current.entries
        )
    )

    response = client.post(
        f"/api/demo/weekly-roster/{record.run_id}/review-decisions",
        json=_command(
            record,
            audit,
            action="reject",
            key="reject-unassigned-blocker",
            note="暫不處理",
        ),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"]["hard_bypass"] is True
    decided = [
        item
        for item in body["audit_items"]
        if item.get("decision_id") == body["decision"]["decision_id"]
    ]
    assert decided
    assert all(item["status"] == "rejected" for item in decided)
    disposition = next(
        item for item in body["reconciliation"]["dispositions"]
        if item["demand_id"] in audit.demand_ids
    )
    assert disposition["disposition"] == "suppressed_with_audit"
    entry = next(
        item for item in body["version"]["entries"]
        if item["id"] == disposition["entry_id"]
    )
    assert entry["status"] == "cancelled"
    assert "supervisor_hard_bypass" in entry["constraint_flags"]
    assert body["reconciliation"]["errors"] == []


def test_current_category_can_be_hard_bypassed_in_one_decision(review_api):
    client, record = review_api
    current = next(item for item in record.versions if item.id == record.current_version_id)
    pending = [item for item in current.audit_items if item.status == AuditStatus.PENDING]
    category = max(
        {item.kind for item in pending},
        key=lambda kind: sum(item.kind == kind for item in pending),
    )
    selected = [item for item in pending if item.kind == category]
    assert len(selected) >= 2

    required_ids = {item.id for item in selected}
    changed = True
    while changed:
        changed = False
        for item in current.audit_items:
            dependencies = set(item.depends_on)
            if item.id in required_ids:
                additions = dependencies - required_ids
            elif dependencies & required_ids:
                additions = {item.id}
            else:
                additions = set()
            if additions:
                required_ids.update(additions)
                changed = True

    command = _command(
        record,
        selected[0],
        action="reject",
        key="bulk-hard-bypass-category",
        audit_ids=sorted(required_ids),
        note="主管批量接受目前分類的風險",
    )
    response = client.post(
        f"/api/demo/weekly-roster/{record.run_id}/review-decisions",
        json=command,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"]["hard_bypass"] is True
    assert set(body["decision"]["audit_ids"]) == required_ids
    decided = [
        item for item in body["audit_items"]
        if item.get("decision_id") == body["decision"]["decision_id"]
    ]
    assert len(decided) == len(required_ids)
    assert all(item["status"] == "rejected" for item in decided)
    assert body["reconciliation"]["errors"] == []

    replay = client.post(
        f"/api/demo/weekly-roster/{record.run_id}/review-decisions",
        json=command,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["decision"]["audit_ids"] == sorted(required_ids)


def test_unassigned_and_data_gap_cannot_be_fake_approved(review_api):
    client, record = review_api
    current = next(item for item in record.versions if item.id == record.current_version_id)
    audit = next(
        item for item in current.audit_items
        if item.kind in {AuditKind.UNASSIGNED_TASK, AuditKind.DATA_GAP}
        and item.suggested_entry is None
        and not item.chain
    )
    response = client.post(
        f"/api/demo/weekly-roster/{record.run_id}/review-decisions",
        json=_command(record, audit),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "AUDIT_HAS_NO_APPROVABLE_SUGGESTION"
    unchanged = state_service.get_state().store.get_weekly_run(record.run_id)
    assert unchanged is not None
    assert unchanged.current_version_id == record.current_version_id


@pytest.mark.parametrize("violation_kind", ["skill", "time", "gender"])
def test_c04_violating_edit_without_override_is_422(
    c04_api,
    violation_kind,
):
    client, record = c04_api
    audit, patch, expected_code = _violating_patch(record, violation_kind)
    response = client.post(
        f"/api/demo/weekly-roster/{record.run_id}/review-decisions",
        json=_command(
            record,
            audit,
            action="edit",
            key=f"invalid-{violation_kind}",
            note="主管測試修改",
            edited_entry=patch,
        ),
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "HARD_CONSTRAINT_OVERRIDE_REQUIRED"
    assert expected_code in {item["code"] for item in detail["violations"]}


def test_c05_violating_override_persists_but_stays_blocked(review_api):
    client, record = review_api
    audit = _suggestion(record)
    response = client.post(
        f"/api/demo/weekly-roster/{record.run_id}/review-decisions",
        json=_command(
            record,
            audit,
            action="edit",
            key="override-unknown-worker",
            note="主管要求保留此修改",
            override_note="同工身份待排班前再次核實",
            edited_entry={
                "entry_id": audit.suggested_entry.id,
                "worker_id": "unknown-worker-for-review",
            },
        ),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["publication_state"] == "blocked"
    assert body["reconciliation"]["publication_state"] == "blocked"
    assert body["decision"]["validator_result"]
    assert body["decision"]["override_note"]
    assert len(body["manual_overrides"]) == 1
    override = body["manual_overrides"][0]
    assert override["decision_id"] == body["decision"]["decision_id"]
    assert override["origin_audit_item_id"] == audit.id


def test_c06_dependency_group_rejects_partial_request(tmp_path, review_demo_run):
    run = deepcopy(review_demo_run)
    suggestions = [
        item for item in run.review_version.audit_items
        if item.suggested_entry is not None and item.status == AuditStatus.PENDING
    ][:2]
    suggestions[0].depends_on = [suggestions[1].id]
    plan = prepare_generated_division_roster_export(
        division_layout=run.build.division,
        dataset=run.result.dataset,
        version=run.review_version,
        generated=run.result.generated,
    )
    run.review_version = plan.review_version
    run.export_report = plan.report
    run.export_plan = plan
    previous = state_service.get_state()
    state_service._STATE = AppState(db_path=tmp_path / "atomic.db")
    try:
        record = state_service.get_state().store.create_weekly_run(
            demo_api._weekly_run_record(run)
        )
        current = next(item for item in record.versions if item.id == record.current_version_id)
        grouped = next(item for item in current.audit_items if item.depends_on)
        client = TestClient(app)
        response = client.post(
            f"/api/demo/weekly-roster/{record.run_id}/review-decisions",
            json=_command(record, grouped),
        )
        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "ATOMIC_REVIEW_GROUP_REQUIRED"
        assert len(detail["required_audit_ids"]) == 2
        unchanged = state_service.get_state().store.get_weekly_run(record.run_id)
        assert unchanged is not None
        assert unchanged.current_version_id == record.current_version_id
    finally:
        state_service._STATE = previous


def test_c07_revalidate_twice_keeps_ids_counts_and_version(review_api):
    client, record = review_api
    payload = {
        "source_version_id": record.current_version_id,
        "content_hash": record.latest_content_hash,
    }
    first = client.post(
        f"/api/demo/weekly-roster/{record.run_id}/revalidate",
        json=payload,
    )
    second = client.post(
        f"/api/demo/weekly-roster/{record.run_id}/revalidate",
        json=payload,
    )
    assert first.status_code == second.status_code == 200
    one, two = first.json(), second.json()
    assert one["version"]["id"] == two["version"]["id"] == record.current_version_id
    assert [item["id"] for item in one["audit_items"]] == [
        item["id"] for item in two["audit_items"]
    ]
    assert one["reconciliation"] == two["reconciliation"]
    stored = state_service.get_state().store.get_weekly_run(record.run_id)
    assert stored is not None
    assert len(stored.versions) == len(record.versions)
    assert not stored.decisions


def _violating_patch(record, kind):
    current = next(item for item in record.versions if item.id == record.current_version_id)
    entries = {item.id: item for item in current.entries}
    linked = [
        (audit, entries[entry_id])
        for audit in current.audit_items
        if audit.status == AuditStatus.PENDING
        for entry_id in audit.entry_ids
        if entry_id in entries
    ]
    if kind == "skill":
        audit, entry = next(
            (audit, entry) for audit, entry in linked if "C04-skill" in audit.reason
        )
        worker = record.dataset.employee_map()["C04-NO-SKILL"]
        return audit, {"entry_id": entry.id, "worker_id": worker.id}, \
            ReviewReasonCode.SKILL_MISMATCH.value
    if kind == "gender":
        audit, entry = next(
            (audit, entry) for audit, entry in linked if "C04-gender" in audit.reason
        )
        worker = record.dataset.employee_map()["C04-WRONG-GENDER"]
        return audit, {"entry_id": entry.id, "worker_id": worker.id}, \
            ReviewReasonCode.GENDER_MISMATCH.value

    for audit, entry in linked:
        if "C04-time" not in audit.reason:
            continue
        occupied = next(
            (
                item for item in current.entries
                if item.demand_id != entry.demand_id
                and item.worker_id
                and item.schedule_date == entry.schedule_date
                and item.period == entry.period
                and (
                    item.session_index is None
                    or entry.session_index is None
                    or item.session_index == entry.session_index
                )
            ),
            None,
        )
        if occupied is not None:
            return audit, {"entry_id": entry.id, "worker_id": occupied.worker_id}, \
                ReviewReasonCode.TIME_CONFLICT.value
    raise AssertionError("fixture has no colliding suggestion")
