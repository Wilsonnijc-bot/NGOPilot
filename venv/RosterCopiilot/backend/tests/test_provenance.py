from datetime import date, time

import pytest

from app.domain import (
    ChangeEvent,
    ChangeType,
    DataGap,
    DemandDisposition,
    EscortRequest,
    Period,
    SchedulerConfig,
    SchedulerSnapshot,
    ServiceCode,
    SourceEvidence,
    TaskDemand,
    TaskKind,
    canonical_json,
    stable_id,
)
from app.scheduler import generate_demands


def test_canonical_json_normalizes_strings_dates_and_key_order() -> None:
    left = {"z": "  Cafe\u0301 ", "a": date(2026, 7, 13), "t": time(8, 30)}
    right = {"t": "08:30:00", "a": "2026-07-13", "z": "Caf\u00e9"}

    assert canonical_json(left) == canonical_json(right)
    assert stable_id("dem_", "weekly_demand", left) == stable_id(
        "dem_", "weekly_demand", right
    )


def test_canonical_json_rejects_sets_and_non_finite_numbers() -> None:
    with pytest.raises(TypeError, match="sets are forbidden"):
        canonical_json({"unsafe": {"a", "b"}})
    with pytest.raises(ValueError, match="non-finite"):
        canonical_json({"unsafe": float("nan")})


def test_source_evidence_and_data_gap_ids_are_stable_and_validated() -> None:
    evidence = SourceEvidence(
        kind="division_template",
        source_id="master-data",
        source_version="17",
        locator="恆常服務!C12",
        field="service_code",
        content_fingerprint="a" * 64,
        confidence="high",
    )
    repeat = SourceEvidence.model_validate(evidence.model_dump())
    gap = DataGap(
        kind="skill",
        entity_id="W001",
        field="skill_facts",
        message="seed skill pending confirmation",
        blocking=False,
        policy="allowed_with_review",
        source_ref_ids=[evidence.id],
    )

    assert evidence.id == repeat.id
    assert evidence.id.startswith("src_")
    assert gap.id.startswith("gap_")
    with pytest.raises(ValueError, match="does not match"):
        SourceEvidence.model_validate({**evidence.model_dump(), "id": "src_bad"})


def test_new_provenance_fields_are_additive_and_json_serializable() -> None:
    evidence = SourceEvidence(kind="fixture", source_id="row-1", locator="HC!A2")
    gap = DataGap(
        kind="route",
        entity_id="W001",
        message="route is unknown",
        source_ref_ids=[evidence.id],
    )
    demand = TaskDemand(
        id="legacy-row-1",
        kind=TaskKind.ESCORT,
        source_evidence=[evidence],
        data_gaps=[gap],
        data_gap_ids=[gap.id],
    )
    disposition = DemandDisposition(
        demand_id="dem_0123456789abcdef0123",
        disposition="unassigned",
        audit_ids=["aud_0123456789abcdef0123"],
        source_ref_ids=[evidence.id],
    )

    payload = demand.model_dump(mode="json")
    assert payload["id"] == "legacy-row-1"
    assert payload["source_evidence"][0]["id"] == evidence.id
    assert disposition.model_dump(mode="json")["disposition"] == "unassigned"


def test_weekly_demand_ids_cover_all_generation_routes_and_survive_shuffle() -> None:
    evidence_a = SourceEvidence(kind="fixture", source_id="row-a", locator="HC!A2")
    evidence_b = SourceEvidence(kind="fixture", source_id="row-b", locator="HC!A3")
    demands = [
        TaskDemand(
            id="fixed",
            kind=TaskKind.FIXED_SERVICE,
            service_code=ServiceCode.EXERCISE,
            weekday=1,
            period=Period.AM,
            elder_id="E1",
        ),
        TaskDemand(
            id="hc-a",
            kind=TaskKind.HC_PATTERN,
            service_code=ServiceCode.HOME_CLEAN,
            weekday=2,
            period=Period.PM,
            elder_id="E2",
            source_evidence=[evidence_a],
        ),
        TaskDemand(
            id="hc-b",
            kind=TaskKind.HC_PATTERN,
            service_code=ServiceCode.HOME_CLEAN,
            weekday=2,
            period=Period.PM,
            elder_id="E2",
            source_evidence=[evidence_b],
        ),
        TaskDemand(
            id="escort",
            kind=TaskKind.ESCORT,
            service_code=ServiceCode.ESCORT,
            task_date=date(2026, 7, 15),
            period=Period.AM,
            session_index=None,
            occupies_full_period=True,
            elder_id="E3",
        ),
        TaskDemand(
            id="duty",
            kind=TaskKind.CENTRE_DUTY,
            service_code=ServiceCode.DUTY_AMC,
            weekday=3,
            period=Period.PM,
            centre="AMC",
            required_count=2,
        ),
    ]
    change = ChangeEvent(
        id="change-escort",
        type=ChangeType.ESCORT_NEW,
        change_date=date(2026, 7, 16),
        new_escort=EscortRequest(
            id="new-escort",
            service_date=date(2026, 7, 16),
            period=Period.PM,
            elder_id="E4",
            destination="clinic",
        ),
    )

    def build(rows):
        return generate_demands(SchedulerSnapshot(
            week_start=date(2026, 7, 13),
            config=SchedulerConfig(centre_duty_placeholders=[]),
            demands=rows,
            change_events=[change.model_copy(deep=True)],
        ))

    first = build(demands)
    shuffled = build(list(reversed(demands)))
    by_source = lambda generated: {
        row.id: (row.demand_id, row.duplicate_ordinal)
        for row in generated.weekly_demands
    }

    assert by_source(first) == by_source(shuffled)
    assert all(row.demand_id and row.demand_id.startswith("dem_")
               for row in first.weekly_demands)
    assert {row.duplicate_ordinal for row in first.tasks if row.id in {"hc-a", "hc-b"}} \
        == {1, 2}
    assert len({row.demand_id for row in first.weekly_demands}) \
        == len(first.weekly_demands)


def test_normal_exclusions_are_not_weekly_demands_but_true_suppression_is() -> None:
    generated = generate_demands(SchedulerSnapshot(
        week_start=date(2026, 7, 13),
        config=SchedulerConfig(centre_duty_placeholders=[]),
        demands=[
            TaskDemand(
                id="outside",
                kind=TaskKind.ESCORT,
                service_code=ServiceCode.ESCORT,
                task_date=date(2026, 7, 20),
                period=Period.AM,
                session_index=None,
                occupies_full_period=True,
            ),
            TaskDemand(
                id="cancelled",
                kind=TaskKind.FIXED_SERVICE,
                service_code=ServiceCode.EXERCISE,
                weekday=1,
                period=Period.AM,
                status="cancelled",
            ),
        ],
    ))

    assert [row.id for row in generated.weekly_demands] == ["cancelled"]
    assert generated.weekly_demands[0].demand_id
    assert [(row.source_record_id, row.reason_code)
            for row in generated.excluded_source_records] == [
                ("outside", "outside_target_week")
            ]
