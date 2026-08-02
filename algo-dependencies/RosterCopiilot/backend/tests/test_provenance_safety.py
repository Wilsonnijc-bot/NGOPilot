from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.domain import (
    AuditItem,
    AuditKind,
    AuditStatus,
    ChangeEvent,
    ChangeType,
    DataGap,
    Elder,
    Employee,
    EntryStatus,
    EscortRequest,
    Gender,
    ManualReviewReason,
    MasterDataSet,
    MasterElder,
    MasterFixedService,
    MasterWorker,
    ManualOverride,
    ManualOverridePin,
    Period,
    RouteFact,
    ReviewReasonCode,
    ScheduleVersion,
    SchedulerConfig,
    SchedulerSnapshot,
    ServiceCode,
    Severity,
    SourceEvidence,
    TaskDemand,
    TaskKind,
    VersionKind,
    WorkerAvailability,
    WorkerSkillFact,
    stable_id,
)
from app.engine import apply_changes, build_baseline
from app.scheduler import (
    finalize_version_provenance,
    generate_demands,
    reconcile_weekly_demands,
    representative_snapshot,
    run_scheduler,
    version_content_hash,
)
from app.scheduler.adapter import to_dataset
from app.scheduler.generator import GeneratedDemands
from app.services.master_data_bridge import build_scheduler_snapshot_from_master_data
from app.services.weekly_demo import WeeklyRosterDemoBuilder


WEEK_START = date(2026, 7, 13)


def _snapshot(*, workers, demands, elders=None, gaps=None, changes=None):
    return SchedulerSnapshot(
        week_start=WEEK_START,
        config=SchedulerConfig(centre_duty_placeholders=[]),
        workers=workers,
        elders=elders or [],
        demands=demands,
        data_gaps=gaps or [],
        change_events=changes or [],
    )


def _worker(worker_id: str, *, skills=(), gender=Gender.FEMALE, routes=()):
    return Employee(
        id=worker_id,
        display_name=worker_id,
        gender=gender,
        skills=list(skills),
        routes=list(routes),
        saturday_team="A",
    )


def _fixed(
    source_id: str,
    service: ServiceCode,
    *,
    worker_id: str | None = None,
    session: int = 1,
    elder_id: str | None = None,
    route: str | None = None,
    gaps=(),
    assumptions=(),
):
    return TaskDemand(
        id=source_id,
        kind=(TaskKind.MEAL_LOGISTICS
              if service == ServiceCode.MEAL else TaskKind.FIXED_SERVICE),
        service_code=service,
        weekday=1,
        period=Period.AM,
        session_index=session,
        elder_id=elder_id,
        pinned_worker_id=worker_id,
        route=route,
        data_gaps=list(gaps),
        assumptions=list(assumptions),
    )


def test_data_gap_identity_ignores_display_message_and_change_position() -> None:
    first = DataGap(
        kind="skill",
        entity_id="W1",
        field="skill_facts:ESC",
        reason_code="seed_skill_unverified",
        message="Alice skill needs review",
        policy="allowed_with_review",
    )
    renamed = first.model_copy(update={"id": "", "message": "陳姑娘技能待核實"})
    renamed = DataGap.model_validate(renamed.model_dump(exclude={"id"}))
    assert first.id == renamed.id

    builder = WeeklyRosterDemoBuilder()
    changes = [
        {"type": "leave", "date": "bad", "worker": "A"},
        {"type": "escort_cancelled", "date": "bad"},
    ]
    gaps_a: list[DataGap] = []
    gaps_b: list[DataGap] = []
    builder._change_events(changes, {}, {}, {}, gaps_a)
    builder._change_events(list(reversed(changes)), {}, {}, {}, gaps_b)
    assert sorted(gap.id for gap in gaps_a) == sorted(gap.id for gap in gaps_b)


def test_unknown_elder_ids_are_masked_and_order_independent() -> None:
    builder = WeeklyRosterDemoBuilder()

    def promote(names):
        aliases = {}
        elders = {}
        for name in names:
            builder._elder_id(
                aliases, elders, name, district="D", unit="EH"
            )
        return {elder.display_name: elder.id for elder in elders.values()}

    first = promote(["Unknown A", "Unknown B"])
    second = promote(["Unknown B", "Unknown A"])
    assert first == second
    assert all(name not in elder_id for name, elder_id in first.items())
    assert all(elder_id.startswith("elder_") for elder_id in first.values())


def test_primary_evidence_stabilizes_demand_identity() -> None:
    primary = SourceEvidence(kind="fixture", source_id="row", field="weekly_demand")
    override = SourceEvidence(kind="override", source_id="override", field="pin")

    def demand(evidence):
        return TaskDemand(
            id="row",
            kind=TaskKind.FIXED_SERVICE,
            service_code=ServiceCode.HOME_CLEAN,
            weekday=1,
            period=Period.AM,
            source_evidence=evidence,
            primary_source_evidence_id=primary.id,
        )

    one = generate_demands(_snapshot(
        workers=[], demands=[demand([primary])]
    )).weekly_demands[0]
    two = generate_demands(_snapshot(
        workers=[], demands=[demand([override, primary])]
    )).weekly_demands[0]
    assert one.demand_id == two.demand_id

    missing_primary = demand([primary, override]).model_copy(
        update={"primary_source_evidence_id": None}
    )
    with pytest.raises(ValueError, match="primary_source_evidence_id"):
        generate_demands(_snapshot(workers=[], demands=[missing_primary]))


def test_unknown_route_is_reviewed_linked_and_preserved_through_repair() -> None:
    demand = _fixed(
        "meal", ServiceCode.MEAL, worker_id="W1", route="R1"
    )
    workers = [_worker("W1"), _worker("W2")]
    baseline_result = run_scheduler(_snapshot(workers=workers, demands=[demand]))
    baseline_entry = baseline_result.version.entries[0]
    assert baseline_entry.status == EntryStatus.NEEDS_REVIEW
    assert "route_qualification_unverified" in baseline_entry.constraint_flags
    assert baseline_entry.data_gap_ids and baseline_entry.source_evidence
    linked = [
        audit for audit in baseline_result.version.audit_items
        if baseline_entry.id in audit.entry_ids and audit.kind == AuditKind.DATA_GAP
    ]
    assert len(linked) == 1
    assert linked[0].id in baseline_entry.audit_ids

    leave = ChangeEvent(
        id="leave-w1",
        type=ChangeType.LEAVE,
        change_date=WEEK_START,
        period=Period.AM,
        worker_id="W1",
    )
    repaired = run_scheduler(_snapshot(
        workers=workers, demands=[demand], changes=[leave]
    ))
    current = next(
        entry for entry in repaired.version.entries
        if entry.demand_id == repaired.generated.tasks[0].demand_id
        and entry.superseded_by is None
        and entry.status in {EntryStatus.NEEDS_REVIEW, EntryStatus.SCHEDULED}
    )
    assert current.worker_id == "W2"
    assert current.status == EntryStatus.NEEDS_REVIEW
    assert current.data_gap_ids


def test_confirmed_route_and_skill_candidates_beat_uncertain_candidates() -> None:
    seed_evidence = SourceEvidence(
        kind="master_data",
        source_id="worker:W1",
        field="skill_facts:ESC",
        confidence="seed",
    )
    seed_gap = DataGap(
        kind="skill",
        entity_id="W1",
        field="skill_facts:HC",
        reason_code="seed_skill_unverified",
        message="seed",
        blocking=False,
        policy="allowed_with_review",
        source_ref_ids=[seed_evidence.id],
    )
    seed_worker = _worker("W1", skills=[ServiceCode.ESCORT])
    seed_worker.seed_skills = [ServiceCode.ESCORT]
    seed_worker.seed_skill_gap_ids = {ServiceCode.ESCORT: seed_gap.id}
    seed_worker.source_evidence = [seed_evidence]
    confirmed = _worker("W2", skills=[ServiceCode.ESCORT])
    escort = TaskDemand(
        id="escort",
        kind=TaskKind.ESCORT,
        service_code=ServiceCode.ESCORT,
        task_date=WEEK_START,
        period=Period.AM,
        session_index=None,
        occupies_full_period=True,
        elder_id="E1",
        destination="D",
    )
    skill_result = run_scheduler(_snapshot(
        workers=[seed_worker, confirmed],
        elders=[Elder(id="E1", display_name="E1", gender=Gender.FEMALE, district="D")],
        demands=[escort],
        gaps=[seed_gap],
    ))
    assert skill_result.version.entries[0].worker_id == "W2"
    assert skill_result.version.entries[0].status == EntryStatus.SCHEDULED
    assert not skill_result.version.audit_items

    route_result = run_scheduler(_snapshot(
        workers=[_worker("W1"), _worker("W2", routes=["R1"])],
        demands=[_fixed("meal", ServiceCode.MEAL, worker_id="missing", route="R1")],
    ))
    assert route_result.version.entries[0].worker_id == "W2"
    assert not route_result.version.entries[0].data_gap_ids
    assert not any(a.kind == AuditKind.DATA_GAP for a in route_result.version.audit_items)


def test_unused_seed_gap_is_silent_but_used_gap_is_one_shared_audit() -> None:
    evidence = SourceEvidence(
        kind="master_data",
        source_id="worker:W1",
        field="skill_facts:HC",
        confidence="seed",
    )
    gap = DataGap(
        kind="skill",
        entity_id="W1",
        field="skill_facts:HC",
        reason_code="seed_skill_unverified",
        message="seed skill",
        blocking=False,
        policy="allowed_with_review",
        source_ref_ids=[evidence.id],
    )
    seed = _worker("W1", skills=[ServiceCode.HOME_CLEAN])
    seed.seed_skills = [ServiceCode.HOME_CLEAN]
    seed.seed_skill_gap_ids = {ServiceCode.HOME_CLEAN: gap.id}
    seed.source_evidence = [evidence]
    confirmed = _worker("W2", skills=[ServiceCode.HOME_CLEAN])

    unused = run_scheduler(_snapshot(
        workers=[seed, confirmed],
        demands=[_fixed("unused", ServiceCode.HOME_CLEAN, worker_id="W2")],
        gaps=[gap],
    ))
    assert unused.version.reconciliation.publication_state == "ready"
    assert not unused.version.audit_items

    used = run_scheduler(_snapshot(
        workers=[seed],
        demands=[
            _fixed("used-1", ServiceCode.HOME_CLEAN, worker_id="W1", session=1),
            _fixed("used-2", ServiceCode.HOME_CLEAN, worker_id="W1", session=2),
        ],
        gaps=[gap],
    ))
    entries = [entry for entry in used.version.entries if entry.superseded_by is None]
    assert len(entries) == 2
    assert {entry.status for entry in entries} == {EntryStatus.NEEDS_REVIEW}
    audits = [audit for audit in used.version.audit_items if gap.id in audit.data_gap_ids]
    assert len(audits) == 1
    assert set(audits[0].entry_ids) == {entry.id for entry in entries}
    assert all(audits[0].id in entry.audit_ids for entry in entries)


def test_unknown_elder_gender_allows_known_worker_review_not_unknown_worker() -> None:
    gap = DataGap(
        kind="gender",
        entity_id="E1",
        field="gender_requirement",
        reason_code="elder_gender_unverified",
        message="elder gender unknown",
        blocking=False,
        policy="allowed_with_review",
    )
    elder = Elder(id="E1", display_name="E1", gender=None, district="D")
    result = run_scheduler(_snapshot(
        workers=[
            _worker("W0", skills=[ServiceCode.BATH], gender=None),
            _worker("W1", skills=[ServiceCode.BATH], gender=Gender.FEMALE),
        ],
        elders=[elder],
        demands=[_fixed(
            "bath", ServiceCode.BATH, elder_id="E1", gaps=[gap]
        )],
    ))
    entry = result.version.entries[0]
    assert entry.worker_id == "W1"
    assert entry.status == EntryStatus.NEEDS_REVIEW
    assert "gender_ok_unverified" in entry.constraint_flags
    assert gap.id in entry.data_gap_ids
    assert any(
        audit.kind == AuditKind.DATA_GAP and entry.id in audit.entry_ids
        for audit in result.version.audit_items
    )


def test_candidate_skill_gap_and_evidence_reach_unassigned_terminal_audit() -> None:
    master = MasterDataSet(
        workers=[MasterWorker(id="W1", display_name="W1")],
        elders=[MasterElder(id="E1", display_name="E1", district="D")],
        fixed_services=[MasterFixedService(
            id="FS1",
            elder_id="E1",
            service_code=ServiceCode.HOME_CLEAN,
            weekday=1,
            period=Period.AM,
            assigned_worker_id="W1",
        )],
    )
    result = run_scheduler(build_scheduler_snapshot_from_master_data(
        master, week_start=WEEK_START
    ))
    entry = next(e for e in result.version.entries if e.status == EntryStatus.UNASSIGNED)
    assert entry.data_gap_ids
    assert entry.source_evidence
    terminal = [
        audit for audit in result.version.audit_items
        if entry.demand_id in audit.demand_ids
        and audit.kind == AuditKind.UNASSIGNED_TASK
    ]
    assert len(terminal) == 1
    assert set(entry.data_gap_ids) <= set(terminal[0].data_gap_ids)
    assert set(item.id for item in entry.source_evidence) <= set(terminal[0].evidence_refs)


def test_cancelled_demand_with_gap_has_explicit_cancellation_audit() -> None:
    gap = DataGap(
        kind="other",
        entity_id="row",
        field="status",
        reason_code="status_pending_review",
        message="status source needs review",
        blocking=False,
        policy="allowed_with_review",
    )
    demand = _fixed("cancelled", ServiceCode.HOME_CLEAN, gaps=[gap])
    demand.status = "cancelled"
    result = run_scheduler(_snapshot(workers=[], demands=[demand]))
    disposition = result.version.demand_dispositions[0]
    assert disposition.disposition == "confirmed_cancelled"
    cancellation = [
        audit for audit in result.version.audit_items
        if audit.kind == AuditKind.SERVICE_CANCELLATION
        and disposition.demand_id in audit.demand_ids
    ]
    assert len(cancellation) == 1
    assert cancellation[0].evidence_refs
    assert gap.id in cancellation[0].data_gap_ids


def test_preexisting_shared_gap_audit_is_extended_to_all_entries() -> None:
    evidence = SourceEvidence(
        kind="master_data", source_id="W1", field="skill_facts:HC", confidence="seed"
    )
    gap = DataGap(
        kind="skill",
        entity_id="W1",
        field="skill_facts:HC",
        reason_code="seed_skill_unverified",
        message="seed",
        blocking=False,
        policy="allowed_with_review",
        source_ref_ids=[evidence.id],
    )
    worker = _worker("W1", skills=[ServiceCode.HOME_CLEAN])
    worker.seed_skills = [ServiceCode.HOME_CLEAN]
    worker.seed_skill_gap_ids = {ServiceCode.HOME_CLEAN: gap.id}
    worker.source_evidence = [evidence]
    snapshot = _snapshot(
        workers=[worker],
        demands=[
            _fixed("one", ServiceCode.HOME_CLEAN, worker_id="W1", session=1),
            _fixed("two", ServiceCode.HOME_CLEAN, worker_id="W1", session=2),
        ],
        gaps=[gap],
    )
    generated = generate_demands(snapshot)
    baseline = build_baseline(to_dataset(snapshot, generated))
    first = baseline.entries[0]
    baseline.audit_items.append(AuditItem(
        id="partial",
        kind=AuditKind.DATA_GAP,
        reason="seed",
        reasons=[ManualReviewReason(
            code=ReviewReasonCode.SKILL_MISMATCH,
            message="seed",
        )],
        demand_ids=[first.demand_id],
        entry_ids=[first.id],
        data_gap_ids=[gap.id],
        evidence_refs=[evidence.id],
    ))
    finalize_version_provenance(baseline, generated)
    audits = [a for a in baseline.audit_items if gap.id in a.data_gap_ids]
    assert len(audits) == 1
    assert set(audits[0].entry_ids) == {entry.id for entry in baseline.entries}
    assert all(audits[0].id in entry.audit_ids for entry in baseline.entries)


def test_reconciliation_rejects_nonreciprocal_zero_and_duplicate_dispositions() -> None:
    result = run_scheduler(_snapshot(
        workers=[_worker("W1")],
        demands=[_fixed("meal", ServiceCode.MEAL, worker_id="W1", route="R1")],
    ))
    broken = result.version.model_copy(deep=True)
    entry = broken.entries[0]
    linked = next(a for a in broken.audit_items if entry.id in a.entry_ids)
    linked.entry_ids.remove(entry.id)
    report = reconcile_weekly_demands(broken, result.generated)
    assert report.publication_state == "blocked"
    assert any(error.code == "missing_audit_link" for error in report.errors)

    zero = ScheduleVersion(
        id="v-zero",
        created_at=datetime.now(timezone.utc),
        week_start=WEEK_START,
    )
    zero_report = reconcile_weekly_demands(zero, result.generated)
    assert zero_report.publication_state == "blocked"
    assert any(error.code == "demand_conservation_error" for error in zero_report.errors)

    duplicate = result.version.model_copy(deep=True)
    copy = duplicate.entries[0].model_copy(deep=True)
    copy.id = "duplicate-terminal"
    copy.audit_ids = []
    duplicate.entries.append(copy)
    duplicate_report = reconcile_weekly_demands(duplicate, result.generated)
    assert duplicate_report.publication_state == "blocked"
    assert any(error.code == "demand_conservation_error"
               for error in duplicate_report.errors)


def test_repair_parent_is_immutable_and_child_ids_are_version_scoped() -> None:
    snapshot = representative_snapshot()
    generated = generate_demands(snapshot)
    dataset = to_dataset(snapshot, generated)
    parent = build_baseline(dataset)
    finalize_version_provenance(parent, generated, include_generated_audits=False)
    before = parent.model_dump(mode="json")
    child, reports = apply_changes(dataset, parent, generated.leave_events)
    finalize_version_provenance(child, generated, reports=reports)

    assert parent.model_dump(mode="json") == before
    for entry in child.entries:
        if not entry.demand_id:
            continue
        assert entry.id == stable_id("ent_", "schedule_entry", {
            "version_id": child.id,
            "demand_id": entry.demand_id,
            "entry_role": entry.entry_role,
            "revision": entry.revision,
        })
    for audit in child.audit_items:
        assert audit.version_id == child.id
        assert audit.id.startswith("aud_") and audit.dedupe_key.startswith("adk_")
        embedded = [
            entry for entry in (audit.original_entry, audit.suggested_entry)
            if entry is not None
        ]
        if len(embedded) == 2 and embedded[0].demand_id == embedded[1].demand_id:
            assert embedded[0].id != embedded[1].id


def test_audit_merge_is_order_independent_and_fail_closed() -> None:
    generated = GeneratedDemands(week_start=WEEK_START)

    def finalized(rows):
        version = ScheduleVersion(
            id="v-audit-merge",
            kind=VersionKind.BASELINE,
            created_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
            week_start=WEEK_START,
            audit_items=rows,
        )
        finalize_version_provenance(
            version, generated, include_generated_audits=False
        )
        return version.audit_items[0].model_dump(mode="json")

    low = AuditItem(
        id="low",
        kind=AuditKind.DATA_GAP,
        severity=Severity.INFO,
        blocking=False,
        reason="B reason",
        reasons=[ManualReviewReason(
            code=ReviewReasonCode.NO_QUALIFIED_WORKER, message="B"
        )],
    )
    high = AuditItem(
        id="high",
        kind=AuditKind.DATA_GAP,
        severity=Severity.HIGH,
        blocking=True,
        reason="A reason",
        reasons=[ManualReviewReason(
            code=ReviewReasonCode.NO_QUALIFIED_WORKER, message="A"
        )],
    )
    forward = finalized([low.model_copy(deep=True), high.model_copy(deep=True)])
    reverse = finalized([high.model_copy(deep=True), low.model_copy(deep=True)])
    assert forward == reverse
    assert forward["blocking"] is True
    assert forward["severity"] == "high"

    approved = low.model_copy(update={
        "id": "approved", "status": AuditStatus.APPROVED, "decision_id": "dec-a"
    })
    rejected = low.model_copy(update={
        "id": "rejected", "status": AuditStatus.REJECTED, "decision_id": "dec-b"
    })
    with pytest.raises(ValueError, match="conflicting decided audit states"):
        finalized([approved, rejected])


def test_assumptions_and_change_gap_policies_reach_entries() -> None:
    assumption_result = run_scheduler(_snapshot(
        workers=[_worker("W1", skills=[ServiceCode.HOME_CLEAN])],
        demands=[_fixed(
            "assumption",
            ServiceCode.HOME_CLEAN,
            worker_id="W1",
            assumptions=["count is provisional"],
        )],
    ))
    assert assumption_result.version.entries[0].assumptions == ["count is provisional"]

    evidence = SourceEvidence(
        kind="weekly_change", source_id="change", field="new_escort"
    )
    gap = DataGap(
        kind="other",
        entity_id="change",
        field="destination",
        reason_code="destination_unverified",
        message="destination needs review",
        blocking=False,
        policy="allowed_with_review",
        source_ref_ids=[evidence.id],
    )
    request = EscortRequest(
        id="new-escort",
        service_date=WEEK_START,
        period=Period.AM,
        elder_id="E1",
        destination="D",
        source_evidence=[evidence],
        data_gap_ids=[gap.id],
        data_gap_policies={gap.id: gap.policy},
    )
    event = ChangeEvent(
        id="new-escort-event",
        type=ChangeType.ESCORT_NEW,
        change_date=WEEK_START,
        period=Period.AM,
        new_escort=request,
    )
    result = run_scheduler(_snapshot(
        workers=[_worker("W1", skills=[ServiceCode.ESCORT])],
        elders=[Elder(id="E1", display_name="E1", gender=Gender.FEMALE, district="D")],
        demands=[],
        gaps=[gap],
        changes=[event],
    ))
    entry = next(e for e in result.version.entries if e.demand_id)
    assert entry.status == EntryStatus.NEEDS_REVIEW
    assert gap.id in entry.data_gap_ids
    assert entry.data_gap_policies[gap.id] == "allowed_with_review"


@pytest.mark.parametrize("change_type", [
    ChangeType.LEAVE,
    ChangeType.ELDER_CANCELLATION,
    ChangeType.ESCORT_CANCELLED,
])
def test_change_event_evidence_reaches_entries_audits_and_registry(change_type) -> None:
    evidence = SourceEvidence(
        kind="weekly_change",
        source_id=f"event:{change_type.value}",
        field=change_type.value,
        confidence="high",
    )
    gap = DataGap(
        kind="other",
        entity_id=f"event:{change_type.value}",
        field="change_payload",
        reason_code="change_payload_review",
        message="change payload needs review",
        blocking=False,
        policy="allowed_with_review",
        source_ref_ids=[evidence.id],
    )
    workers = [
        _worker("W1", skills=[ServiceCode.HOME_CLEAN, ServiceCode.ESCORT]),
        _worker("W2", skills=[ServiceCode.HOME_CLEAN, ServiceCode.ESCORT]),
    ]
    elders = [
        Elder(id="E1", display_name="E1", gender=Gender.FEMALE, district="D")
    ]
    if change_type == ChangeType.ESCORT_CANCELLED:
        demands = [TaskDemand(
            id="escort-source",
            kind=TaskKind.ESCORT,
            service_code=ServiceCode.ESCORT,
            task_date=WEEK_START,
            period=Period.AM,
            session_index=None,
            occupies_full_period=True,
            elder_id="E1",
            destination="D",
        )]
    else:
        demands = [_fixed(
            "fixed-source",
            ServiceCode.HOME_CLEAN,
            worker_id="W1",
            elder_id="E1",
        )]
    event_kwargs = {
        "type": change_type,
        "change_date": WEEK_START,
        "period": Period.AM,
        "source_refs": ["ops:7"],
        "source_evidence": [evidence],
        "data_gap_ids": [gap.id],
        "data_gap_policies": {gap.id: gap.policy},
    }
    if change_type == ChangeType.LEAVE:
        event_kwargs["worker_id"] = "W1"
    elif change_type == ChangeType.ELDER_CANCELLATION:
        event_kwargs["elder_id"] = "E1"
    else:
        event_kwargs["escort_request_id"] = "escort-source"
    event = ChangeEvent(**event_kwargs)

    result = run_scheduler(_snapshot(
        workers=workers,
        elders=elders,
        demands=demands,
        gaps=[gap],
        changes=[event],
    ))
    registry = {item.id for item in result.generated.source_evidence}
    assert evidence.id in registry
    triggered = [
        audit for audit in result.version.audit_items
        if audit.trigger_event_id == event.id
    ]
    assert triggered
    assert all(evidence.id in audit.evidence_refs for audit in triggered)
    assert all(gap.id in audit.data_gap_ids for audit in triggered)
    affected_ids = {entry_id for audit in triggered for entry_id in audit.entry_ids}
    affected = [entry for entry in result.version.entries if entry.id in affected_ids]
    assert affected
    assert all("ops:7" in entry.source_refs for entry in affected)
    assert all(evidence.id in {item.id for item in entry.source_evidence}
               for entry in affected)
    assert all(gap.id in entry.data_gap_ids for entry in affected)


def test_change_event_ids_and_order_ignore_presentation_fields() -> None:
    leave_a = ChangeEvent(
        type=ChangeType.LEAVE,
        change_date=WEEK_START,
        period=Period.AM,
        worker_id="W1",
        reason="first display reason",
        source_refs=["display:a"],
    )
    leave_b = ChangeEvent(
        type=ChangeType.LEAVE,
        change_date=WEEK_START,
        period=Period.AM,
        worker_id="W1",
        reason="renamed display reason",
        source_refs=["display:b"],
    )
    assert leave_a.id == leave_b.id

    cancel = ChangeEvent(
        type=ChangeType.ELDER_CANCELLATION,
        change_date=WEEK_START,
        period=Period.PM,
        elder_id="E1",
    )
    first = generate_demands(_snapshot(
        workers=[], demands=[], changes=[leave_a, cancel]
    ))
    second = generate_demands(_snapshot(
        workers=[], demands=[], changes=[cancel, leave_a]
    ))
    assert [event.id for event in first.leave_events] == [
        event.id for event in second.leave_events
    ]


def test_unassigned_terminal_audit_must_be_reciprocal_not_demand_only() -> None:
    master = MasterDataSet(
        workers=[MasterWorker(id="W1", display_name="W1")],
        elders=[MasterElder(id="E1", display_name="E1", district="D")],
        fixed_services=[MasterFixedService(
            id="FS1",
            elder_id="E1",
            service_code=ServiceCode.HOME_CLEAN,
            weekday=1,
            period=Period.AM,
            assigned_worker_id="W1",
        )],
    )
    result = run_scheduler(build_scheduler_snapshot_from_master_data(
        master, week_start=WEEK_START
    ))
    broken = result.version.model_copy(deep=True)
    entry = next(e for e in broken.entries if e.status == EntryStatus.UNASSIGNED)
    terminal = next(
        audit for audit in broken.audit_items
        if audit.kind == AuditKind.UNASSIGNED_TASK
        and entry.demand_id in audit.demand_ids
    )
    terminal.entry_ids = []
    entry.audit_ids = [audit_id for audit_id in entry.audit_ids if audit_id != terminal.id]
    fake = terminal.model_copy(deep=True)
    fake.id = "fake-demand-only"
    fake.dedupe_key = None
    fake.entry_ids = []
    broken.audit_items.append(fake)
    report = reconcile_weekly_demands(broken, result.generated)
    assert report.publication_state == "blocked"
    assert any(
        error.code == "demand_conservation_error"
        and entry.demand_id in error.demand_ids
        for error in report.errors
    )


def test_manual_forbid_override_is_causal_resolvable_provenance() -> None:
    master = MasterDataSet(
        workers=[
            MasterWorker(
                id="W1",
                display_name="W1",
                skill_facts=[WorkerSkillFact(
                    service_code=ServiceCode.HOME_CLEAN,
                    level="qualified",
                    source="ngo_confirmed",
                )],
            ),
        ],
        elders=[MasterElder(id="E1", display_name="E1", district="D")],
        fixed_services=[MasterFixedService(
            id="FS1",
            elder_id="E1",
            service_code=ServiceCode.HOME_CLEAN,
            weekday=1,
            period=Period.AM,
            assigned_worker_id="W1",
        )],
        manual_overrides=[ManualOverride(
            id="OVR1",
            scope="recurring",
            pin=ManualOverridePin(
                worker_id="W1", weekday=1, period=Period.AM
            ),
            action="forbid_assignment",
            reason="capacity lock display note",
        )],
    )
    result = run_scheduler(build_scheduler_snapshot_from_master_data(
        master, week_start=WEEK_START
    ))
    entry = next(
        item for item in result.version.entries
        if item.demand_id and item.superseded_by is None
    )
    override_evidence = [
        item for item in entry.source_evidence
        if item.kind == "master_data" and item.field == "action"
    ]
    assert entry.status == EntryStatus.UNASSIGNED
    assert entry.worker_id is None
    assert override_evidence
    assert "manual_override:OVR1" in entry.source_refs
    registry = {item.id for item in result.generated.source_evidence}
    assert {item.id for item in override_evidence} <= registry
    audit = next(a for a in result.version.audit_items if entry.id in a.entry_ids)
    assert {item.id for item in override_evidence} <= set(audit.evidence_refs)


def test_every_entry_audit_gap_and_evidence_reference_resolves() -> None:
    result = run_scheduler(_snapshot(
        workers=[_worker("W1")],
        demands=[_fixed(
            "meal", ServiceCode.MEAL, worker_id="W1", route="R1"
        )],
    ))
    gap_ids = {gap.id for gap in result.generated.data_gaps}
    evidence_ids = {item.id for item in result.generated.source_evidence}
    audit_ids = {audit.id for audit in result.version.audit_items}
    entry_ids = {entry.id for entry in result.version.entries}
    assert len(gap_ids) == len(result.generated.data_gaps)
    assert len(evidence_ids) == len(result.generated.source_evidence)
    for entry in result.version.entries:
        assert set(entry.data_gap_ids) <= gap_ids
        assert {item.id for item in entry.source_evidence} <= evidence_ids
        assert set(entry.audit_ids) <= audit_ids
    for audit in result.version.audit_items:
        assert set(audit.data_gap_ids) <= gap_ids
        assert set(audit.evidence_refs) <= evidence_ids
        assert set(audit.entry_ids) <= entry_ids


def test_duplicate_gap_blocking_merge_is_order_independent_and_fail_closed() -> None:
    low = DataGap(
        kind="week_pattern",
        entity_id="FS1",
        field="week_pattern",
        reason_code="week_pattern_unparseable",
        message="display B",
        blocking=False,
        policy="ineligible",
    )
    high = DataGap.model_validate({
        **low.model_dump(exclude={"id"}),
        "message": "display A",
        "blocking": True,
    })
    assert low.id == high.id

    def run(rows):
        return run_scheduler(_snapshot(
            workers=[], demands=[], gaps=rows
        )).version.reconciliation

    forward = run([low, high])
    reverse = run([high, low])
    assert forward.publication_state == reverse.publication_state == "blocked"
    assert forward.pending_audit_counts == reverse.pending_audit_counts


def test_gender_review_repair_never_selects_unknown_gender_worker() -> None:
    gap = DataGap(
        kind="gender",
        entity_id="E1",
        field="gender_requirement",
        reason_code="elder_gender_unverified",
        message="elder gender unknown",
        blocking=False,
        policy="allowed_with_review",
    )
    elder = Elder(id="E1", display_name="E1", gender=None, district="D")
    leave = ChangeEvent(
        type=ChangeType.LEAVE,
        change_date=WEEK_START,
        period=Period.AM,
        worker_id="W1",
    )
    result = run_scheduler(_snapshot(
        workers=[
            _worker("W1", skills=[ServiceCode.BATH], gender=Gender.FEMALE),
            _worker("W2", skills=[ServiceCode.BATH], gender=None),
            _worker("W3", skills=[ServiceCode.BATH], gender=Gender.MALE),
        ],
        elders=[elder],
        demands=[_fixed(
            "bath",
            ServiceCode.BATH,
            worker_id="W1",
            elder_id="E1",
            gaps=[gap],
        )],
        changes=[leave],
    ))
    current = next(
        entry for entry in result.version.entries
        if entry.demand_id and entry.superseded_by is None
        and entry.status == EntryStatus.NEEDS_REVIEW
    )
    assert current.worker_id == "W3"
    assert current.worker_id != "W2"
    assert result.version.reconciliation.errors == []


def test_gender_review_repair_to_unassigned_has_no_false_flag_error() -> None:
    gap = DataGap(
        kind="gender",
        entity_id="E1",
        field="gender_requirement",
        reason_code="elder_gender_unverified",
        message="elder gender unknown",
        blocking=False,
        policy="allowed_with_review",
    )
    elder = Elder(id="E1", display_name="E1", gender=None, district="D")
    result = run_scheduler(_snapshot(
        workers=[
            _worker("W1", skills=[ServiceCode.BATH], gender=Gender.FEMALE),
            _worker("W2", skills=[ServiceCode.BATH], gender=None),
        ],
        elders=[elder],
        demands=[_fixed(
            "bath", ServiceCode.BATH, worker_id="W1", elder_id="E1", gaps=[gap]
        )],
        changes=[ChangeEvent(
            type=ChangeType.LEAVE,
            change_date=WEEK_START,
            period=Period.AM,
            worker_id="W1",
        )],
    ))
    terminal = next(
        entry for entry in result.version.entries
        if entry.demand_id and entry.superseded_by is None
        and entry.status == EntryStatus.UNASSIGNED
    )
    assert "gender_ok_unverified" not in terminal.constraint_flags
    assert result.version.reconciliation.errors == []


def test_conflicting_evidence_confidence_is_conservative_and_order_independent() -> None:
    high = SourceEvidence(
        kind="fixture", source_id="row", field="weekly_demand", confidence="high"
    )
    seed = high.model_copy(update={"confidence": "seed"})

    def build(evidence):
        demand = TaskDemand(
            id="row",
            kind=TaskKind.FIXED_SERVICE,
            service_code=ServiceCode.HOME_CLEAN,
            weekday=1,
            period=Period.AM,
            pinned_worker_id="W1",
            source_evidence=evidence,
            primary_source_evidence_id=high.id,
        )
        generated = generate_demands(_snapshot(
            workers=[_worker("W1", skills=[ServiceCode.HOME_CLEAN])],
            demands=[demand],
        ))
        version = build_baseline(to_dataset(_snapshot(
            workers=[_worker("W1", skills=[ServiceCode.HOME_CLEAN])],
            demands=[demand],
        ), generated))
        version.id = "v-confidence-order"
        finalize_version_provenance(version, generated)
        report = reconcile_weekly_demands(version, generated)
        return generated, version, report

    forward = build([high, seed])
    reverse = build([seed, high])
    assert forward[0].source_evidence[0].confidence == "seed"
    assert reverse[0].source_evidence[0].confidence == "seed"
    assert forward[1].entries[0].source_evidence[0].confidence == "seed"
    assert forward[2].publication_state == reverse[2].publication_state == "draft"
    assert version_content_hash(forward[1]) == version_content_hash(reverse[1])


def test_duplicate_change_events_merge_all_provenance_in_either_order() -> None:
    high = SourceEvidence(
        kind="weekly_change", source_id="ticket", field="leave", confidence="high"
    )
    seed = high.model_copy(update={"confidence": "seed"})
    first = ChangeEvent(
        type=ChangeType.LEAVE,
        change_date=WEEK_START,
        period=Period.AM,
        worker_id="W1",
        source_refs=["ticket:A"],
        source_evidence=[high],
    )
    second = ChangeEvent(
        type=ChangeType.LEAVE,
        change_date=WEEK_START,
        period=Period.AM,
        worker_id="W1",
        source_refs=["ticket:B"],
        source_evidence=[seed],
    )
    generated_a = generate_demands(_snapshot(
        workers=[_worker("W1")], demands=[], changes=[first, second]
    ))
    generated_b = generate_demands(_snapshot(
        workers=[_worker("W1")], demands=[], changes=[second, first]
    ))
    assert generated_a.leave_events[0].model_dump(mode="json") == (
        generated_b.leave_events[0].model_dump(mode="json")
    )
    assert generated_a.leave_events[0].source_refs == ["ticket:A", "ticket:B"]
    assert generated_a.leave_events[0].source_evidence[0].confidence == "seed"


def test_identity_whitespace_cannot_change_change_or_route_behavior() -> None:
    event_a = ChangeEvent(
        type=ChangeType.LEAVE, change_date=WEEK_START, period=Period.AM,
        worker_id="W1",
    )
    event_b = ChangeEvent(
        type=ChangeType.LEAVE, change_date=WEEK_START, period=Period.AM,
        worker_id=" W1 ",
    )
    assert event_a.model_dump(mode="json") == event_b.model_dump(mode="json")

    def run(route: str):
        return run_scheduler(_snapshot(
            workers=[_worker("W1", routes=["R1"])],
            demands=[_fixed("meal", ServiceCode.MEAL, worker_id="W1", route=route)],
        ))

    route_a = run("R1")
    route_b = run(" R1 ")
    assert route_a.generated.tasks[0].demand_id == route_b.generated.tasks[0].demand_id
    assert route_a.version.entries[0].status == route_b.version.entries[0].status
    assert route_a.version.entries[0].route == route_b.version.entries[0].route == "R1"


def test_authoritative_registries_reject_orphan_and_stale_consumers() -> None:
    result = run_scheduler(_snapshot(
        workers=[_worker("W1")],
        demands=[_fixed("meal", ServiceCode.MEAL, worker_id="W1", route="R1")],
    ))
    without_evidence = result.generated.model_copy(
        deep=True, update={"source_evidence": []}
    )
    report = reconcile_weekly_demands(
        result.version.model_copy(deep=True), without_evidence
    )
    assert report.publication_state == "blocked"
    assert any(error.code == "missing_evidence_link" for error in report.errors)

    without_gaps = result.generated.model_copy(deep=True, update={"data_gaps": []})
    report = reconcile_weekly_demands(
        result.version.model_copy(deep=True), without_gaps
    )
    assert report.publication_state == "blocked"
    assert any(error.code == "missing_data_gap_link" for error in report.errors)

    orphan_gap = DataGap(
        kind="other",
        entity_id="unused",
        message="orphan evidence",
        blocking=False,
        policy="informational",
        source_ref_ids=["src_does_not_exist"],
    )
    with_orphan = result.generated.model_copy(
        deep=True, update={"data_gaps": [*result.generated.data_gaps, orphan_gap]}
    )
    report = reconcile_weekly_demands(
        result.version.model_copy(deep=True), with_orphan
    )
    assert report.publication_state == "blocked"
    assert "src_does_not_exist" in {
        ref for error in report.errors for ref in error.evidence_refs
    }


def test_missing_and_duplicate_weekly_demand_ids_block_conservation() -> None:
    result = run_scheduler(_snapshot(
        workers=[_worker("W1")],
        demands=[_fixed("meal", ServiceCode.MEAL, worker_id="W1")],
    ))
    demand = result.generated.tasks[0]
    duplicate = result.generated.model_copy(
        deep=True, update={"tasks": [demand, demand.model_copy(deep=True)]}
    )
    report = reconcile_weekly_demands(
        result.version.model_copy(deep=True), duplicate
    )
    assert report.publication_state == "blocked"
    assert report.weekly_demand_total == 2
    assert any(
        error.code == "demand_conservation_error" for error in report.errors
    )

    missing = result.generated.model_copy(
        deep=True,
        update={"tasks": [demand.model_copy(update={"demand_id": None})]},
    )
    report = reconcile_weekly_demands(result.version.model_copy(deep=True), missing)
    assert report.publication_state == "blocked"
    assert report.weekly_demand_total == 1


def test_needs_review_audit_must_cover_relevant_gap_and_evidence() -> None:
    result = run_scheduler(_snapshot(
        workers=[_worker("W1")],
        demands=[_fixed("meal", ServiceCode.MEAL, worker_id="W1", route="R1")],
    ))
    broken = result.version.model_copy(deep=True)
    entry = next(item for item in broken.entries if item.status == EntryStatus.NEEDS_REVIEW)
    audit = next(
        item for item in broken.audit_items
        if entry.id in item.entry_ids and item.kind == AuditKind.DATA_GAP
    )
    audit.data_gap_ids = []
    audit.evidence_refs = []
    report = reconcile_weekly_demands(broken, result.generated)
    assert report.publication_state == "blocked"
    assert any(
        error.code == "missing_audit_link" and entry.id in error.entry_ids
        for error in report.errors
    )


def test_cancelled_disposition_requires_reciprocal_evidence_audit() -> None:
    event = ChangeEvent(
        type=ChangeType.ELDER_CANCELLATION,
        change_date=WEEK_START,
        period=Period.AM,
        elder_id="E1",
    )
    result = run_scheduler(_snapshot(
        workers=[_worker("W1", skills=[ServiceCode.HOME_CLEAN])],
        elders=[Elder(id="E1", display_name="E1", gender=Gender.FEMALE, district="D")],
        demands=[_fixed(
            "hc", ServiceCode.HOME_CLEAN, worker_id="W1", elder_id="E1"
        )],
        changes=[event],
    ))
    broken = result.version.model_copy(deep=True)
    entry = next(item for item in broken.entries if item.status == EntryStatus.CANCELLED)
    audit = next(
        item for item in broken.audit_items
        if item.kind == AuditKind.SERVICE_CANCELLATION
        and entry.demand_id in item.demand_ids
    )
    entry.audit_ids = [item for item in entry.audit_ids if item != audit.id]
    audit.entry_ids = [item for item in audit.entry_ids if item != entry.id]
    for item in broken.audit_items:
        item.status = AuditStatus.APPROVED
    report = reconcile_weekly_demands(broken, result.generated)
    assert report.publication_state == "blocked"
    assert any(error.code == "missing_audit_link" for error in report.errors)


def test_unknown_change_target_becomes_blocking_gap() -> None:
    result = run_scheduler(_snapshot(
        workers=[],
        demands=[],
        changes=[ChangeEvent(
            type=ChangeType.LEAVE,
            change_date=WEEK_START,
            worker_id="W404",
        )],
    ))
    assert result.version.reconciliation.publication_state == "blocked"
    assert any(
        gap.reason_code == "change_target_missing:worker_id"
        and gap.blocking
        for gap in result.generated.data_gaps
    )


def test_manual_override_origin_is_distinct_and_reaches_terminal_audit() -> None:
    def run(origin: str):
        master = MasterDataSet(
            workers=[MasterWorker(
                id="W1", display_name="W1", gender="F",
                skill_facts=[WorkerSkillFact(
                    service_code=ServiceCode.HOME_CLEAN,
                    level="qualified", source="ngo_confirmed",
                )],
                saturday_team="A",
            )],
            fixed_services=[MasterFixedService(
                id="FS1", service_code=ServiceCode.HOME_CLEAN,
                weekday=1, period=Period.AM, assigned_worker_id="W1",
            )],
            manual_overrides=[ManualOverride(
                id="OVR1", scope="recurring",
                pin=ManualOverridePin(worker_id="W1", weekday=1, period=Period.AM),
                action="forbid_assignment", reason="lock",
                origin_audit_item_id=origin,
            )],
        )
        return run_scheduler(build_scheduler_snapshot_from_master_data(
            master, week_start=WEEK_START
        ))

    first = run("aud-parent-A")
    second = run("aud-parent-B")
    first_evidence = {
        item.id for item in first.generated.source_evidence if item.field == "action"
    }
    second_evidence = {
        item.id for item in second.generated.source_evidence if item.field == "action"
    }
    assert first_evidence != second_evidence
    entry = next(item for item in first.version.entries if item.status == EntryStatus.UNASSIGNED)
    audit = next(item for item in first.version.audit_items if entry.id in item.entry_ids)
    assert "OVR1" in entry.override_ids and "OVR1" in audit.override_ids
    assert "aud-parent-A" in entry.depends_on and "aud-parent-A" in audit.depends_on


def test_conflicting_master_skill_and_route_facts_fail_closed() -> None:
    skill_master = MasterDataSet(
        workers=[MasterWorker(
            id="W1", display_name="W1", gender="F", saturday_team="A",
            skill_facts=[
                WorkerSkillFact(service_code=ServiceCode.HOME_CLEAN,
                                level="qualified", source="ngo_confirmed"),
                WorkerSkillFact(service_code=ServiceCode.HOME_CLEAN,
                                level="training", source="manual"),
            ],
        )],
        fixed_services=[MasterFixedService(
            id="FS1", service_code=ServiceCode.HOME_CLEAN,
            weekday=1, period=Period.AM, assigned_worker_id="W1",
        )],
    )
    skill = run_scheduler(build_scheduler_snapshot_from_master_data(
        skill_master, week_start=WEEK_START
    ))
    assert skill.version.entries[0].status == EntryStatus.UNASSIGNED
    assert any(
        gap.reason_code == "conflicting_skill_facts"
        and gap.policy == "ineligible"
        for gap in skill.generated.data_gaps
    )

    route_master = MasterDataSet(
        workers=[MasterWorker(
            id="W1", display_name="W1", gender="F", saturday_team="A",
            route_facts=[
                RouteFact(route_code="R1", qualified=True, source="ngo_confirmed"),
                RouteFact(route_code="R1", qualified=False, source="manual"),
            ],
        )],
        fixed_services=[MasterFixedService(
            id="FS1", service_code=ServiceCode.MEAL,
            weekday=1, period=Period.AM, assigned_worker_id="W1", route="R1",
        )],
    )
    route = run_scheduler(build_scheduler_snapshot_from_master_data(
        route_master, week_start=WEEK_START
    ))
    assert route.version.entries[0].status == EntryStatus.UNASSIGNED
    assert any(
        gap.reason_code == "conflicting_route_facts"
        and gap.id in route.version.entries[0].data_gap_ids
        for gap in route.generated.data_gaps
    )


def test_missing_candidate_skill_is_materialized_on_terminal_provenance() -> None:
    result = run_scheduler(_snapshot(
        workers=[_worker("W1", skills=[ServiceCode.HOME_CLEAN])],
        demands=[_fixed("bath", ServiceCode.BATH, worker_id="W1")],
    ))
    entry = next(item for item in result.version.entries if item.status == EntryStatus.UNASSIGNED)
    gap = next(
        item for item in result.generated.data_gaps
        if item.entity_id == "W1"
        and item.field == f"skill_facts:{ServiceCode.BATH.value}"
    )
    assert gap.policy == "ineligible"
    assert gap.id in entry.data_gap_ids
    audit = next(
        item for item in result.version.audit_items
        if item.kind == AuditKind.UNASSIGNED_TASK and entry.id in item.entry_ids
    )
    assert gap.id in audit.data_gap_ids
    assert set(gap.source_ref_ids) <= set(audit.evidence_refs)


def test_prior_leave_evidence_is_causal_for_later_unassigned_repair() -> None:
    evidence_w2 = SourceEvidence(
        kind="weekly_change", source_id="leave-w2", field="leave"
    )
    evidence_w1 = SourceEvidence(
        kind="weekly_change", source_id="leave-w1", field="leave"
    )
    result = run_scheduler(_snapshot(
        workers=[
            _worker("W1", skills=[ServiceCode.HOME_CLEAN]),
            _worker("W2", skills=[ServiceCode.EXERCISE]),
        ],
        demands=[_fixed("hc", ServiceCode.HOME_CLEAN, worker_id="W1")],
        changes=[
            ChangeEvent(
                id="a-leave-w2", type=ChangeType.LEAVE,
                change_date=WEEK_START, period=Period.AM, worker_id="W2",
                source_evidence=[evidence_w2],
            ),
            ChangeEvent(
                id="b-leave-w1", type=ChangeType.LEAVE,
                change_date=WEEK_START, period=Period.AM, worker_id="W1",
                source_evidence=[evidence_w1],
            ),
        ],
    ))
    entry = next(
        item for item in result.version.entries
        if item.status == EntryStatus.UNASSIGNED and item.superseded_by is None
    )
    evidence_ids = {item.id for item in entry.source_evidence}
    assert {evidence_w1.id, evidence_w2.id} <= evidence_ids
    audit = next(
        item for item in result.version.audit_items
        if item.kind == AuditKind.UNASSIGNED_TASK and entry.id in item.entry_ids
    )
    assert {evidence_w1.id, evidence_w2.id} <= set(audit.evidence_refs)


def test_decided_and_pending_audit_merge_is_order_independent() -> None:
    from app.scheduler.reconciliation import _merge_audit

    pending = AuditItem(
        id="pending",
        kind=AuditKind.DATA_GAP,
        reason="pending reason",
        human_note="pending note",
    )
    decided = AuditItem(
        id="decided",
        kind=AuditKind.DATA_GAP,
        reason="decided reason",
        status=AuditStatus.APPROVED,
        decision_id="dec-1",
        human_note="approved note",
        decided_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
    )
    forward = pending.model_copy(deep=True)
    _merge_audit(forward, decided.model_copy(deep=True))
    reverse = decided.model_copy(deep=True)
    _merge_audit(reverse, pending.model_copy(deep=True))
    assert forward.model_dump(mode="json", exclude={"id"}) == reverse.model_dump(
        mode="json", exclude={"id"}
    )


def test_unrelated_worker_forbid_does_not_pollute_pinned_assignment() -> None:
    evidence = SourceEvidence(
        kind="manual_override", source_id="OVR-W1", field="action"
    )
    snapshot = _snapshot(
        workers=[
            _worker("W1", skills=[ServiceCode.HOME_CLEAN]),
            _worker("W2", skills=[ServiceCode.HOME_CLEAN]),
        ],
        demands=[_fixed("hc", ServiceCode.HOME_CLEAN, worker_id="W2")],
    ).model_copy(update={
        "availability": [WorkerAvailability(
            worker_id="W1",
            available_date=WEEK_START,
            period=Period.AM,
            is_available=False,
            reason="manual_override",
            source_refs=["manual_override:OVR-W1"],
            source_evidence=[evidence],
            override_ids=["OVR-W1"],
            depends_on=["AUD-W1"],
        )],
    })
    result = run_scheduler(snapshot)
    entry = result.version.entries[0]
    assert entry.worker_id == "W2"
    assert entry.status == EntryStatus.SCHEDULED
    assert entry.override_ids == []
    assert entry.depends_on == []
    assert "manual_override:OVR-W1" not in entry.source_refs
    assert all("OVR-W1" not in audit.override_ids for audit in result.version.audit_items)
