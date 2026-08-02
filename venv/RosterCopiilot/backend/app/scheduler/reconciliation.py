"""Deterministic provenance finalization and weekly-demand conservation."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable

from ..domain import (
    AuditItem,
    AuditKind,
    AuditStatus,
    DataGap,
    DemandDisposition,
    DemandReconciliationReport,
    EntrySource,
    EntryStatus,
    ExcludedSourceRecord,
    ImpactReport,
    ManualReviewReason,
    ReconciliationError,
    ReviewReasonCode,
    ScheduleEntry,
    ScheduleVersion,
    Severity,
    canonical_json,
    content_fingerprint,
    merge_source_evidence,
    stable_id,
)
from .generator import GeneratedDemands


_TERMINAL_UNASSIGNED_AUDIT_KINDS = {
    AuditKind.UNASSIGNED_TASK,
    AuditKind.DUTY_UNDER_COVERAGE,
}


def finalize_version_provenance(
    version: ScheduleVersion,
    generated: GeneratedDemands,
    *,
    reports: list[ImpactReport] | None = None,
    include_generated_audits: bool = True,
) -> None:
    """Finalize stable entry/audit IDs and authoritative ID links in place."""

    if include_generated_audits:
        _ensure_confirmed_cancellation_entries(version, generated)
    entry_remap = _finalize_entry_ids(version)
    _remap_entry_links(version, entry_remap, reports or [])
    if include_generated_audits:
        _ensure_uncertainty_audits(version, generated)
        _ensure_suppression_audits(version, generated)
        _ensure_applied_override_audits(version)
    audit_remap = _finalize_audits(version)
    _remap_audit_links(version, audit_remap, reports or [])
    _link_entries_to_audits(version)


def reconcile_weekly_demands(
    version: ScheduleVersion,
    generated: GeneratedDemands,
    *,
    hard_violation_count: int = 0,
    export_failure_count: int = 0,
    placement_count: int = 0,
    changed_cell_count: int = 0,
) -> DemandReconciliationReport:
    """Require exactly one terminal disposition for every dated weekly demand."""

    errors: list[ReconciliationError] = []
    weekly_rows = generated.weekly_demands
    missing_id_rows = [demand for demand in weekly_rows if not demand.demand_id]
    if missing_id_rows:
        errors.append(ReconciliationError(
            code="demand_conservation_error",
            message="weekly demand registry contains rows without demand_id",
        ))
    duplicate_demand_ids = sorted(
        demand_id for demand_id, count in Counter(
            demand.demand_id for demand in weekly_rows if demand.demand_id
        ).items() if count > 1
    )
    if duplicate_demand_ids:
        errors.append(ReconciliationError(
            code="demand_conservation_error",
            message="weekly demand registry contains duplicate demand IDs",
            demand_ids=duplicate_demand_ids,
        ))
    demand_by_id = {
        demand.demand_id: demand
        for demand in weekly_rows
        if demand.demand_id
    }
    gap_by_id = {gap.id: gap for gap in generated.data_gaps}
    gap_ids = set(gap_by_id)
    authoritative_evidence = merge_source_evidence(generated.source_evidence)
    evidence_by_id = {item.id: item for item in authoritative_evidence}
    evidence_ids = set(evidence_by_id)
    if len(gap_by_id) != len(generated.data_gaps):
        errors.append(ReconciliationError(
            code="missing_data_gap_link",
            message="authoritative data-gap registry contains duplicate IDs",
            data_gap_ids=sorted(
                gap_id for gap_id, count in Counter(
                    gap.id for gap in generated.data_gaps
                ).items() if count > 1
            ),
        ))
    if len(authoritative_evidence) != len(generated.source_evidence):
        errors.append(ReconciliationError(
            code="missing_evidence_link",
            message="authoritative source-evidence registry contains duplicate IDs",
            evidence_refs=sorted(
                evidence_id for evidence_id, count in Counter(
                    item.id for item in generated.source_evidence
                ).items() if count > 1
            ),
        ))
    embedded_entry_ids = {
        entry.id for audit in version.audit_items for entry in _audit_entries(audit)
    }
    version_entry_ids = {entry.id for entry in version.entries}
    valid_entry_ids = version_entry_ids | embedded_entry_ids
    audit_by_id = {audit.id: audit for audit in version.audit_items}

    for gap in generated.data_gaps:
        missing = sorted(set(gap.source_ref_ids) - evidence_ids)
        if missing:
            errors.append(ReconciliationError(
                code="missing_evidence_link",
                message=f"data gap {gap.id} references missing source evidence",
                data_gap_ids=[gap.id],
                evidence_refs=missing,
            ))

    for demand in generated.weekly_demands:
        if not demand.demand_id:
            continue
        demand_evidence_ids = {item.id for item in demand.source_evidence}
        missing_evidence = sorted(demand_evidence_ids - evidence_ids)
        mismatched_evidence = sorted(
            item.id for item in demand.source_evidence
            if item.id in evidence_by_id
            and canonical_json(item.model_dump(mode="json"))
            != canonical_json(evidence_by_id[item.id].model_dump(mode="json"))
        )
        primary = demand.primary_source_evidence_id
        if primary is None or primary not in demand_evidence_ids or primary not in evidence_ids:
            if primary:
                missing_evidence.append(primary)
            errors.append(ReconciliationError(
                code="missing_evidence_link",
                message=(f"demand {demand.demand_id} has no resolvable primary "
                         "source evidence"),
                demand_ids=[demand.demand_id],
                evidence_refs=sorted(set(missing_evidence)),
            ))
        elif missing_evidence or mismatched_evidence:
            errors.append(ReconciliationError(
                code="missing_evidence_link",
                message=f"demand {demand.demand_id} has orphan or stale evidence",
                demand_ids=[demand.demand_id],
                evidence_refs=sorted(set(missing_evidence + mismatched_evidence)),
            ))
        demand_gap_ids = {
            *demand.data_gap_ids,
            *(gap.id for gap in demand.data_gaps),
        }
        missing_gaps = sorted(demand_gap_ids - gap_ids)
        if missing_gaps:
            errors.append(ReconciliationError(
                code="missing_data_gap_link",
                message=f"demand {demand.demand_id} references missing data gaps",
                demand_ids=[demand.demand_id],
                data_gap_ids=missing_gaps,
            ))

    for event in generated.leave_events:
        event_gap_ids = set(event.data_gap_ids)
        missing_gaps = sorted(event_gap_ids - gap_ids)
        if missing_gaps:
            errors.append(ReconciliationError(
                code="missing_data_gap_link",
                message=f"change event {event.id} references missing data gaps",
                data_gap_ids=missing_gaps,
            ))
        missing_evidence = sorted(
            {item.id for item in event.source_evidence} - evidence_ids
        )
        mismatched_evidence = sorted(
            item.id for item in event.source_evidence
            if item.id in evidence_by_id
            and canonical_json(item.model_dump(mode="json"))
            != canonical_json(evidence_by_id[item.id].model_dump(mode="json"))
        )
        if missing_evidence or mismatched_evidence:
            errors.append(ReconciliationError(
                code="missing_evidence_link",
                message=f"change event {event.id} has orphan or stale evidence",
                evidence_refs=sorted(set(missing_evidence + mismatched_evidence)),
            ))
    for entry in version.entries:
        if entry.demand_id is None:
            errors.append(ReconciliationError(
                code="missing_demand_link",
                message=f"entry {entry.id} has no weekly demand link",
                entry_ids=[entry.id],
            ))
        elif entry.demand_id not in demand_by_id:
            errors.append(ReconciliationError(
                code="missing_demand_link",
                message=f"entry {entry.id} references unknown demand {entry.demand_id}",
                demand_ids=[entry.demand_id],
                entry_ids=[entry.id],
            ))
        missing_audits = sorted(set(entry.audit_ids) - set(audit_by_id))
        if missing_audits:
            errors.append(ReconciliationError(
                code="missing_audit_link",
                message=f"entry {entry.id} references missing audits",
                entry_ids=[entry.id],
                audit_ids=missing_audits,
            ))
        nonreciprocal_audits = sorted(
            audit_id for audit_id in entry.audit_ids
            if audit_id in audit_by_id
            and entry.id not in audit_by_id[audit_id].entry_ids
        )
        if nonreciprocal_audits:
            errors.append(ReconciliationError(
                code="missing_audit_link",
                message=f"entry {entry.id} has non-reciprocal audit links",
                entry_ids=[entry.id],
                audit_ids=nonreciprocal_audits,
            ))
        missing_gaps = sorted(set(entry.data_gap_ids) - gap_ids)
        if missing_gaps:
            errors.append(ReconciliationError(
                code="missing_data_gap_link",
                message=f"entry {entry.id} references missing data gaps",
                entry_ids=[entry.id],
                data_gap_ids=missing_gaps,
            ))
        missing_evidence = sorted(
            {item.id for item in entry.source_evidence} - evidence_ids
        )
        mismatched_evidence = sorted(
            item.id for item in entry.source_evidence
            if item.id in evidence_by_id
            and canonical_json(item.model_dump(mode="json"))
            != canonical_json(evidence_by_id[item.id].model_dump(mode="json"))
        )
        if missing_evidence or mismatched_evidence:
            errors.append(ReconciliationError(
                code="missing_evidence_link",
                message=f"entry {entry.id} references missing or stale source evidence",
                entry_ids=[entry.id],
                evidence_refs=sorted(set(missing_evidence + mismatched_evidence)),
            ))
        if entry.status in {
            EntryStatus.NEEDS_REVIEW,
            EntryStatus.UNASSIGNED,
            EntryStatus.CANCELLED,
        }:
            reciprocal = [
                audit_by_id[audit_id]
                for audit_id in entry.audit_ids
                if audit_id in audit_by_id
                and entry.id in audit_by_id[audit_id].entry_ids
            ]
            covered_gaps = {
                gap_id for audit in reciprocal for gap_id in audit.data_gap_ids
            }
            covered_evidence = {
                evidence_id for audit in reciprocal
                for evidence_id in audit.evidence_refs
            }
            uncovered_gaps = sorted(set(entry.data_gap_ids) - covered_gaps)
            uncertain_evidence = {
                item.id for item in entry.source_evidence
                if item.confidence in {"low", "seed"}
            }
            uncovered_evidence = sorted(uncertain_evidence - covered_evidence)
            if uncovered_gaps or uncovered_evidence:
                errors.append(ReconciliationError(
                    code="missing_audit_link",
                    message=(f"entry {entry.id} uncertainty is not covered by "
                             "reciprocal audits"),
                    demand_ids=[entry.demand_id] if entry.demand_id else [],
                    entry_ids=[entry.id],
                    audit_ids=[audit.id for audit in reciprocal],
                    data_gap_ids=uncovered_gaps,
                    evidence_refs=uncovered_evidence,
                ))
        if (
            "gender_ok_unverified" in entry.constraint_flags
            and "supervisor_hard_bypass" not in entry.constraint_flags
            and entry.status in {EntryStatus.SCHEDULED, EntryStatus.NEEDS_REVIEW}
        ):
            linked_gender_gap_audit = any(
                audit_id in audit_by_id
                and audit_by_id[audit_id].kind == AuditKind.DATA_GAP
                and bool(set(entry.data_gap_ids) & set(audit_by_id[audit_id].data_gap_ids))
                and entry.id in audit_by_id[audit_id].entry_ids
                for audit_id in entry.audit_ids
            )
            if (
                entry.status != EntryStatus.NEEDS_REVIEW
                or not entry.data_gap_ids
                or not linked_gender_gap_audit
            ):
                errors.append(ReconciliationError(
                    code="invalid_uncertainty_state",
                    message=(
                        f"entry {entry.id} uses gender_ok_unverified without a "
                        "reciprocal data-gap audit"
                    ),
                    demand_ids=[entry.demand_id] if entry.demand_id else [],
                    entry_ids=[entry.id],
                    data_gap_ids=list(entry.data_gap_ids),
                ))

    for audit in version.audit_items:
        missing_demands = sorted(set(audit.demand_ids) - set(demand_by_id))
        if missing_demands:
            errors.append(ReconciliationError(
                code="missing_demand_link",
                message=f"audit {audit.id} references missing demands",
                demand_ids=missing_demands,
                audit_ids=[audit.id],
            ))
        missing_entries = sorted(set(audit.entry_ids) - valid_entry_ids)
        if missing_entries:
            errors.append(ReconciliationError(
                code="missing_entry_link",
                message=f"audit {audit.id} references missing entries",
                entry_ids=missing_entries,
                audit_ids=[audit.id],
            ))
        nonreciprocal_entries = sorted(
            entry_id for entry_id in audit.entry_ids
            if entry_id in version_entry_ids
            and audit.id not in (version.entry_by_id(entry_id).audit_ids)  # type: ignore[union-attr]
        )
        if nonreciprocal_entries:
            errors.append(ReconciliationError(
                code="missing_audit_link",
                message=f"audit {audit.id} has non-reciprocal entry links",
                entry_ids=nonreciprocal_entries,
                audit_ids=[audit.id],
            ))
        missing_gaps = sorted(set(audit.data_gap_ids) - gap_ids)
        if missing_gaps:
            errors.append(ReconciliationError(
                code="missing_data_gap_link",
                message=f"audit {audit.id} references missing data gaps",
                audit_ids=[audit.id],
                data_gap_ids=missing_gaps,
            ))
        missing_evidence = sorted(set(audit.evidence_refs) - evidence_ids)
        if missing_evidence:
            errors.append(ReconciliationError(
                code="missing_evidence_link",
                message=f"audit {audit.id} references missing evidence",
                audit_ids=[audit.id],
                evidence_refs=missing_evidence,
            ))

    embedded_consumers = {
        entry.id: entry
        for audit in version.audit_items
        for entry in _audit_entries(audit)
        if entry.id not in version_entry_ids
    }
    for entry in embedded_consumers.values():
        missing_gaps = sorted(set(entry.data_gap_ids) - gap_ids)
        missing_evidence = sorted(
            {item.id for item in entry.source_evidence} - evidence_ids
        )
        mismatched_evidence = sorted(
            item.id for item in entry.source_evidence
            if item.id in evidence_by_id
            and canonical_json(item.model_dump(mode="json"))
            != canonical_json(evidence_by_id[item.id].model_dump(mode="json"))
        )
        if missing_gaps:
            errors.append(ReconciliationError(
                code="missing_data_gap_link",
                message=f"embedded entry {entry.id} references missing data gaps",
                entry_ids=[entry.id],
                data_gap_ids=missing_gaps,
            ))
        if missing_evidence or mismatched_evidence:
            errors.append(ReconciliationError(
                code="missing_evidence_link",
                message=(f"embedded entry {entry.id} references missing or stale "
                         "source evidence"),
                entry_ids=[entry.id],
                evidence_refs=sorted(set(missing_evidence + mismatched_evidence)),
            ))

    dispositions: list[DemandDisposition] = []
    suppressed_ids = {
        demand.demand_id for demand in generated.suppressed_weekly_demands
        if demand.demand_id
    }
    entries_by_demand: dict[str, list[ScheduleEntry]] = defaultdict(list)
    for entry in version.entries:
        if entry.demand_id:
            entries_by_demand[entry.demand_id].append(entry)

    for demand_id, demand in sorted(demand_by_id.items()):
        linked_entries = entries_by_demand.get(demand_id, [])
        terminal_entries = [
            entry for entry in linked_entries
            if entry.entry_role != "alternative"
            and entry.superseded_by is None
            and entry.status in {
                EntryStatus.SCHEDULED,
                EntryStatus.NEEDS_REVIEW,
                EntryStatus.UNASSIGNED,
                EntryStatus.CANCELLED,
            }
        ]
        linked_audit_ids = sorted({
            audit.id for audit in version.audit_items
            if demand_id in audit.demand_ids
        } | {
            audit_id for entry in linked_entries for audit_id in entry.audit_ids
        })

        if len(terminal_entries) == 1:
            entry = terminal_entries[0]
            disposition = _entry_disposition(
                entry,
                [audit_by_id[audit_id] for audit_id in linked_audit_ids
                 if audit_id in audit_by_id],
                demand.status,
            )
            if disposition == "scheduled" and _entry_uses_uncertainty(entry):
                errors.append(ReconciliationError(
                    code="invalid_uncertainty_state",
                    message=f"scheduled entry {entry.id} uses unresolved uncertainty",
                    demand_ids=[demand_id],
                    entry_ids=[entry.id],
                    data_gap_ids=list(entry.data_gap_ids),
                    evidence_refs=[item.id for item in entry.source_evidence
                                   if item.confidence in {"low", "seed"}],
                ))
            if disposition == "needs_review":
                pending = [
                    audit_id for audit_id in linked_audit_ids
                    if audit_by_id.get(audit_id)
                    and audit_by_id[audit_id].status == AuditStatus.PENDING
                    and audit_id in entry.audit_ids
                    and entry.id in audit_by_id[audit_id].entry_ids
                ]
                if not pending:
                    errors.append(ReconciliationError(
                        code="missing_audit_link",
                        message=f"needs-review entry {entry.id} has no pending audit",
                        demand_ids=[demand_id],
                        entry_ids=[entry.id],
                    ))
            if disposition == "unassigned":
                terminal_audits = [
                    audit for audit in version.audit_items
                    if demand_id in audit.demand_ids
                    and audit.kind in _TERMINAL_UNASSIGNED_AUDIT_KINDS
                    and audit.blocking
                    and entry.id in audit.entry_ids
                    and audit.id in entry.audit_ids
                ]
                if len(terminal_audits) != 1:
                    errors.append(ReconciliationError(
                        code="demand_conservation_error",
                        message=(f"unassigned demand {demand_id} requires exactly one "
                                 "terminal blocking audit"),
                        demand_ids=[demand_id],
                        entry_ids=[entry.id],
                        audit_ids=sorted(audit.id for audit in terminal_audits),
                    ))
            if entry.status == EntryStatus.CANCELLED:
                cancellation_audits = [
                    audit for audit in version.audit_items
                    if demand_id in audit.demand_ids
                    and audit.kind in {
                        AuditKind.SERVICE_CANCELLATION,
                        AuditKind.ESCORT_ADJUSTMENT,
                    }
                    and audit.evidence_refs
                ]
                confirmation_expected = (
                    demand.status in {"cancelled", "hospitalised"}
                    or any(
                        audit.trigger_event_id is not None
                        for audit in cancellation_audits
                    )
                )
                reciprocal = [
                    audit for audit in cancellation_audits
                    if entry.id in audit.entry_ids and audit.id in entry.audit_ids
                ]
                if confirmation_expected and not reciprocal:
                    errors.append(ReconciliationError(
                        code="missing_audit_link",
                        message=(f"cancelled entry {entry.id} has no reciprocal "
                                 "evidence-bearing cancellation audit"),
                        demand_ids=[demand_id],
                        entry_ids=[entry.id],
                        audit_ids=sorted(audit.id for audit in cancellation_audits),
                    ))
            dispositions.append(DemandDisposition(
                demand_id=demand_id,
                disposition=disposition,
                entry_id=entry.id,
                audit_ids=linked_audit_ids,
                source_ref_ids=sorted(item.id for item in demand.source_evidence),
                reason_code=_disposition_reason(entry, audit_by_id),
            ))
            continue

        if not terminal_entries and (
            demand_id in suppressed_ids
            or any(
                audit.kind == AuditKind.EXCLUSIVE_CANCELLATION
                and demand_id in audit.demand_ids
                for audit in version.audit_items
            )
        ) and linked_audit_ids:
            dispositions.append(DemandDisposition(
                demand_id=demand_id,
                disposition="suppressed_with_audit",
                audit_ids=linked_audit_ids,
                source_ref_ids=sorted(item.id for item in demand.source_evidence),
                reason_code="explicit_suppression",
            ))
            continue

        errors.append(ReconciliationError(
            code="demand_conservation_error",
            message=(f"demand {demand_id} has {len(terminal_entries)} terminal "
                     "entries; exactly one is required"),
            demand_ids=[demand_id],
            entry_ids=sorted(entry.id for entry in terminal_entries),
            audit_ids=linked_audit_ids,
        ))

    counts = Counter(item.disposition for item in dispositions)
    excluded_counts = Counter(row.reason_code for row in generated.excluded_source_records)
    pending = [a for a in version.audit_items if a.status == AuditStatus.PENDING]
    decided = [a for a in version.audit_items if a.status != AuditStatus.PENDING]
    active_entries = [
        entry for entry in version.entries
        if entry.status in {EntryStatus.SCHEDULED, EntryStatus.NEEDS_REVIEW}
        and entry.superseded_by is None
    ]
    blocked = bool(
        errors
        or hard_violation_count
        or export_failure_count
        or counts["unassigned"]
        or any(a.blocking for a in pending)
    )
    publication_state = (
        "blocked" if blocked
        else "draft" if counts["needs_review"] or pending
        else "ready"
    )
    report = DemandReconciliationReport(
        weekly_demand_total=len(weekly_rows),
        scheduled=counts["scheduled"],
        needs_review=counts["needs_review"],
        unassigned=counts["unassigned"],
        confirmed_cancelled=counts["confirmed_cancelled"],
        suppressed_with_audit=counts["suppressed_with_audit"],
        dispositions=dispositions,
        excluded_source_records=list(generated.excluded_source_records),
        excluded_source_record_counts=dict(sorted(excluded_counts.items())),
        active_entry_ids=sorted(entry.id for entry in active_entries),
        review_entry_ids=sorted(
            entry.id for entry in active_entries if entry.status == EntryStatus.NEEDS_REVIEW
        ),
        unassigned_entry_ids=sorted(
            entry.id for entry in version.entries if entry.status == EntryStatus.UNASSIGNED
        ),
        cancellation_entry_ids=sorted(
            entry.id for entry in version.entries if entry.status == EntryStatus.CANCELLED
        ),
        suppression_demand_ids=sorted(
            item.demand_id for item in dispositions
            if item.disposition == "suppressed_with_audit"
        ),
        pending_audit_counts=_audit_counts(pending),
        decided_audit_counts=_audit_counts(decided),
        placement_count=placement_count,
        changed_cell_count=changed_cell_count,
        hard_violation_count=hard_violation_count,
        export_failure_count=export_failure_count,
        errors=sorted(errors, key=_error_sort_key),
        publication_state=publication_state,
        version_id=version.id,
    )
    version.demand_dispositions = dispositions
    version.reconciliation = report
    report.content_hash = version_content_hash(version)
    return report


def version_content_hash(version: ScheduleVersion) -> str:
    """Hash immutable scheduling content, excluding timestamps/runtime/report hash."""

    payload = version.model_dump(
        mode="json",
        exclude={"created_at", "reconciliation"},
    )
    summary = dict(payload.get("summary", {}))
    summary.pop("runtime_ms", None)
    payload["summary"] = summary
    return content_fingerprint(payload)


def _finalize_entry_ids(version: ScheduleVersion) -> dict[str, str]:
    remap: dict[str, str] = {}
    semantics_by_stable_id: dict[str, str] = {}
    entries = list(version.entries)
    for audit in version.audit_items:
        entries.extend(_audit_entries(audit))
    seen_objects: set[int] = set()
    for entry in entries:
        if id(entry) in seen_objects:
            continue
        seen_objects.add(id(entry))
        if not entry.demand_id:
            continue
        old_id = entry.id
        expected = stable_id("ent_", "schedule_entry", {
            "version_id": version.id,
            "demand_id": entry.demand_id,
            "entry_role": entry.entry_role,
            "revision": entry.revision,
        })
        semantic_fingerprint = content_fingerprint(entry.model_dump(
            mode="json",
            exclude={"id", "audit_ids"},
        ))
        prior_semantics = semantics_by_stable_id.get(expected)
        if prior_semantics is not None and prior_semantics != semantic_fingerprint:
            raise ValueError(
                f"non-equivalent schedule entries resolve to stable ID {expected}"
            )
        semantics_by_stable_id[expected] = semantic_fingerprint
        entry.id = expected
        if old_id != expected:
            remap[old_id] = expected
    return remap


def _remap_entry_links(
    version: ScheduleVersion,
    remap: dict[str, str],
    reports: list[ImpactReport],
) -> None:
    if not remap:
        return
    for entry in version.entries:
        if entry.id in remap:
            entry.id = remap[entry.id]
        if entry.superseded_by in remap:
            entry.superseded_by = remap[entry.superseded_by]
    for audit in version.audit_items:
        audit.entry_ids = sorted({remap.get(item, item) for item in audit.entry_ids})
        for entry in _audit_entries(audit):
            if entry.id in remap:
                entry.id = remap[entry.id]
            if entry.superseded_by in remap:
                entry.superseded_by = remap[entry.superseded_by]
    for impact in version.impacts:
        impact.affected_entry_ids = [remap.get(item, item) for item in impact.affected_entry_ids]
        impact.suggested_entry_ids = [remap.get(item, item) for item in impact.suggested_entry_ids]
    for report in reports:
        for impact in report.impacts:
            impact.affected_entry_ids = [remap.get(item, item) for item in impact.affected_entry_ids]
            impact.suggested_entry_ids = [remap.get(item, item) for item in impact.suggested_entry_ids]


def _ensure_uncertainty_audits(
    version: ScheduleVersion,
    generated: GeneratedDemands,
) -> None:
    gaps = {gap.id: gap for gap in generated.data_gaps}
    gap_entries: dict[str, list[ScheduleEntry]] = defaultdict(list)
    evidence_entries: dict[str, list[ScheduleEntry]] = defaultdict(list)
    evidence_objects = {}
    for entry in version.entries:
        for gap_id in entry.data_gap_ids:
            gap_entries[gap_id].append(entry)
        for evidence in entry.source_evidence:
            evidence_objects[evidence.id] = evidence
            if evidence.confidence in {"low", "seed"}:
                evidence_entries[evidence.id].append(entry)

    represented_gaps: dict[str, list[AuditItem]] = defaultdict(list)
    represented_evidence: dict[str, list[AuditItem]] = defaultdict(list)
    for audit in version.audit_items:
        if audit.kind != AuditKind.DATA_GAP:
            continue
        for gap_id in audit.data_gap_ids:
            represented_gaps[gap_id].append(audit)
        for evidence_id in audit.evidence_refs:
            represented_evidence[evidence_id].append(audit)
    for gap_id, gap in sorted(gaps.items()):
        affected = gap_entries.get(gap_id, [])
        # Worker/entity uncertainty is auditable only when it actually affects
        # a weekly placement.  A blocking gap with no entity is generation-wide
        # and remains an explicit blocker even when no entry could be produced.
        if not affected and not gap.blocking:
            continue
        if represented_gaps.get(gap_id):
            for audit in represented_gaps[gap_id]:
                audit.demand_ids = sorted({
                    *audit.demand_ids,
                    *(entry.demand_id for entry in affected if entry.demand_id),
                })
                audit.entry_ids = sorted({
                    *audit.entry_ids, *(entry.id for entry in affected)
                })
                audit.evidence_refs = sorted({
                    *audit.evidence_refs, *gap.source_ref_ids
                })
            continue
        version.audit_items.append(AuditItem(
            id=f"pending-gap-{gap_id}",
            kind=AuditKind.DATA_GAP,
            severity=Severity.HIGH if gap.blocking else Severity.WARNING,
            blocking=gap.blocking,
            reason=gap.message,
            reasons=[ManualReviewReason(
                code=_gap_reason_code(gap),
                message=gap.message,
                params={"entity_id": gap.entity_id or "", "gap_id": gap.id},
            )],
            demand_ids=sorted({e.demand_id for e in affected if e.demand_id}),
            entry_ids=sorted(e.id for e in affected),
            data_gap_ids=[gap.id],
            evidence_refs=sorted(gap.source_ref_ids),
        ))
    for evidence_id, affected in sorted(evidence_entries.items()):
        if represented_evidence.get(evidence_id):
            for audit in represented_evidence[evidence_id]:
                audit.demand_ids = sorted({
                    *audit.demand_ids,
                    *(entry.demand_id for entry in affected if entry.demand_id),
                })
                audit.entry_ids = sorted({
                    *audit.entry_ids, *(entry.id for entry in affected)
                })
            continue
        evidence = evidence_objects[evidence_id]
        if any(evidence_id in gap.source_ref_ids for gap in gaps.values()):
            continue
        version.audit_items.append(AuditItem(
            id=f"pending-evidence-{evidence_id}",
            kind=AuditKind.DATA_GAP,
            severity=Severity.WARNING,
            blocking=False,
            reason=f"low-confidence evidence {evidence_id} was used by a placement",
            reasons=[ManualReviewReason(
                code=ReviewReasonCode.NO_QUALIFIED_WORKER,
                message="排班使用了尚待確認的來源資料",
                params={"evidence_id": evidence_id},
                rule_ref="RB-DATA-01",
            )],
            demand_ids=sorted({e.demand_id for e in affected if e.demand_id}),
            entry_ids=sorted(e.id for e in affected),
            evidence_refs=[evidence_id],
        ))


def _ensure_suppression_audits(
    version: ScheduleVersion,
    generated: GeneratedDemands,
) -> None:
    represented = {
        demand_id
        for audit in version.audit_items
        if audit.kind in {
            AuditKind.SERVICE_CANCELLATION,
            AuditKind.ESCORT_ADJUSTMENT,
            AuditKind.EXCLUSIVE_CANCELLATION,
        }
        for demand_id in audit.demand_ids
    }
    for demand in sorted(
        generated.suppressed_weekly_demands,
        key=lambda item: item.demand_id or "",
    ):
        if not demand.demand_id or demand.demand_id in represented:
            continue
        linked_entries = [
            entry for entry in version.entries if entry.demand_id == demand.demand_id
        ]
        version.audit_items.append(AuditItem(
            id=f"pending-suppression-{demand.demand_id}",
            kind=AuditKind.SERVICE_CANCELLATION,
            severity=Severity.INFO,
            blocking=False,
            reason=f"weekly demand {demand.demand_id} explicitly suppressed: {demand.status}",
            reasons=[ManualReviewReason(
                code=ReviewReasonCode.ELDER_CANCELLED,
                message=f"需求已明確標記為 {demand.status}",
                params={"status": demand.status},
            )],
            demand_ids=[demand.demand_id],
            entry_ids=[entry.id for entry in linked_entries],
            data_gap_ids=list(demand.data_gap_ids),
            evidence_refs=sorted(item.id for item in demand.source_evidence),
            override_ids=list(demand.override_ids),
            depends_on=list(demand.depends_on),
        ))


def _ensure_confirmed_cancellation_entries(
    version: ScheduleVersion,
    generated: GeneratedDemands,
) -> None:
    existing = {entry.demand_id for entry in version.entries if entry.demand_id}
    for demand in generated.suppressed_weekly_demands:
        if (
            not demand.demand_id
            or demand.demand_id in existing
            or demand.status not in {"cancelled", "hospitalised"}
            or demand.task_date is None
            or demand.period is None
            or demand.service_code is None
        ):
            continue
        version.entries.append(ScheduleEntry(
            id=f"pending-cancel-{demand.demand_id}",
            demand_id=demand.demand_id,
            schedule_date=demand.task_date,
            weekday=demand.weekday or demand.task_date.isoweekday(),  # type: ignore[arg-type]
            period=demand.period,
            session_index=demand.session_index,
            worker_id=(demand.exclusive_worker_id or demand.pinned_worker_id),
            service_code=demand.service_code,
            elder_id=demand.elder_id,
            center=demand.centre,
            district=demand.district,
            route=demand.route,
            destination=demand.destination,
            start_time=demand.start_time,
            end_time=demand.end_time,
            source=EntrySource.SYSTEM_REASSIGNED,
            status=EntryStatus.CANCELLED,
            explanation=f"來源已明確標記為 {demand.status}",
            source_refs=list(demand.source_refs),
            source_evidence=list(demand.source_evidence),
            data_gap_ids=list(demand.data_gap_ids),
            data_gap_policies={
                gap.id: gap.policy for gap in demand.data_gaps
                if gap.id in demand.data_gap_ids
            },
            assumptions=list(demand.assumptions),
            override_ids=list(demand.override_ids),
            depends_on=list(demand.depends_on),
        ))
        existing.add(demand.demand_id)


def _ensure_applied_override_audits(version: ScheduleVersion) -> None:
    """Record an already-applied override even when it caused no warning."""

    represented = {
        override_id
        for audit in version.audit_items
        for override_id in (
            *audit.override_ids,
            *(
                override_id
                for entry in _audit_entries(audit)
                for override_id in entry.override_ids
            ),
        )
    }
    for entry in sorted(version.entries, key=lambda item: item.id):
        missing = sorted(set(entry.override_ids) - represented)
        if not missing:
            continue
        version.audit_items.append(AuditItem(
            id=f"pending-applied-override-{entry.id}",
            kind=AuditKind.TEMPLATE_ISSUE,
            severity=Severity.INFO,
            blocking=False,
            status=AuditStatus.APPROVED,
            reason=f"manual override applied to {entry.demand_id or entry.id}",
            original_entry=entry,
            demand_ids=[entry.demand_id] if entry.demand_id else [],
            entry_ids=[entry.id],
            evidence_refs=[item.id for item in entry.source_evidence],
            override_ids=missing,
            depends_on=list(entry.depends_on),
            human_note="persisted manual override applied by the scheduler",
        ))
        represented.update(missing)


def _finalize_audits(version: ScheduleVersion) -> dict[str, str]:
    remap: dict[str, str] = {}
    deduped: dict[tuple[str, str], AuditItem] = {}
    ordered: list[AuditItem] = []
    for audit in version.audit_items:
        embedded = _audit_entries(audit)
        audit.demand_ids = sorted({
            *audit.demand_ids,
            *(entry.demand_id for entry in embedded if entry.demand_id),
        })
        audit.entry_ids = sorted({*audit.entry_ids, *(entry.id for entry in embedded)})
        audit.data_gap_ids = sorted({
            *audit.data_gap_ids,
            *(gap_id for entry in embedded for gap_id in entry.data_gap_ids),
        })
        audit.evidence_refs = sorted({
            *audit.evidence_refs,
            *(item.id for entry in embedded for item in entry.source_evidence),
        })
        audit.override_ids = sorted({
            *audit.override_ids,
            *(override_id for entry in embedded for override_id in entry.override_ids),
        })
        audit.depends_on = sorted({
            *audit.depends_on,
            *(dependency for entry in embedded for dependency in entry.depends_on),
        })
        reason_codes = sorted({reason.code.value for reason in audit.reasons})
        expected_key = stable_id("adk_", "audit_dedupe", {
            "kind": audit.kind.value,
            "reason_code": reason_codes or [audit.kind.value],
            "demand_ids": audit.demand_ids,
            "entry_ids": audit.entry_ids,
            "data_gap_ids": audit.data_gap_ids,
            "trigger_event_id": audit.trigger_event_id,
        })
        old_id = audit.id
        expected_id = stable_id("aud_", "audit_item", {
            "origin_version_id": version.id,
            "dedupe_key": expected_key,
        })
        audit.dedupe_key = expected_key
        audit.version_id = version.id
        audit.id = expected_id
        if old_id != expected_id:
            remap[old_id] = audit.id
        key = (version.id, expected_key)
        prior = deduped.get(key)
        if prior is None:
            deduped[key] = audit
            ordered.append(audit)
            continue
        remap[audit.id] = prior.id
        _merge_audit(prior, audit)
    version.audit_items = ordered
    return remap


def _merge_audit(target: AuditItem, duplicate: AuditItem) -> None:
    severity_order = {Severity.INFO: 0, Severity.WARNING: 1, Severity.HIGH: 2}
    merged_notes = sorted({
        note for note in (target.human_note, duplicate.human_note) if note
    })
    decided = [
        audit for audit in (target, duplicate)
        if audit.status != AuditStatus.PENDING
    ]
    if len(decided) == 2:
        if decided[0].status != decided[1].status:
            raise ValueError("conflicting decided audit states for one dedupe key")
        if decided[0].decision_id != decided[1].decision_id:
            raise ValueError("conflicting audit decision IDs for one dedupe key")
    elif len(decided) == 1:
        source = decided[0]
        target.status = source.status
        target.decision_id = source.decision_id
        target.human_note = source.human_note
        target.decided_at = source.decided_at

    target.blocking = target.blocking or duplicate.blocking
    target.severity = max(
        (target.severity, duplicate.severity),
        key=lambda item: severity_order[item],
    )
    target.reason = " | ".join(sorted({target.reason, duplicate.reason}))
    reasons = {
        canonical_json(reason.model_dump(mode="json")): reason
        for reason in (*target.reasons, *duplicate.reasons)
    }
    target.reasons = [reasons[key] for key in sorted(reasons)]
    target.demand_ids = sorted({*target.demand_ids, *duplicate.demand_ids})
    target.entry_ids = sorted({*target.entry_ids, *duplicate.entry_ids})
    target.data_gap_ids = sorted({*target.data_gap_ids, *duplicate.data_gap_ids})
    target.evidence_refs = sorted({*target.evidence_refs, *duplicate.evidence_refs})
    target.override_ids = sorted({*target.override_ids, *duplicate.override_ids})
    target.depends_on = sorted({*target.depends_on, *duplicate.depends_on})
    target.human_note = " | ".join(merged_notes) or None
    if target.decided_at and duplicate.decided_at:
        target.decided_at = max(target.decided_at, duplicate.decided_at)


def _remap_audit_links(
    version: ScheduleVersion,
    remap: dict[str, str],
    reports: list[ImpactReport],
) -> None:
    for entry in version.entries:
        entry.audit_ids = sorted({remap.get(item, item) for item in entry.audit_ids})
    for audit in version.audit_items:
        audit.depends_on = sorted({remap.get(item, item) for item in audit.depends_on})
    for report in reports:
        report.audit_item_ids = [remap.get(item, item) for item in report.audit_item_ids]


def _link_entries_to_audits(version: ScheduleVersion) -> None:
    entries: dict[str, list[ScheduleEntry]] = defaultdict(list)
    for entry in version.entries:
        entries[entry.id].append(entry)
    # Embedded original/suggested/chain entries may intentionally share a
    # canonical ID with the active entry.  Reciprocal links are part of the
    # entry payload, so every copy of that identity must receive the same
    # audit IDs; otherwise a restart/revalidation observes conflicting payloads
    # for one stable entry ID.
    for audit in version.audit_items:
        for entry in _audit_entries(audit):
            entries[entry.id].append(entry)
    # Audit.entry_ids is authoritative.  Carrying forward stale entry-side
    # links would make an audit appear reciprocal only on one embedded copy.
    linked: dict[str, set[str]] = {entry_id: set() for entry_id in entries}
    for audit in version.audit_items:
        for entry_id in audit.entry_ids:
            linked.setdefault(entry_id, set()).add(audit.id)
    for entry_id, copies in entries.items():
        audit_ids = sorted(linked.get(entry_id, set()))
        for entry in copies:
            entry.audit_ids = audit_ids


def _audit_entries(audit: AuditItem) -> list[ScheduleEntry]:
    entries = [
        entry for entry in (audit.original_entry, audit.suggested_entry) if entry
    ]
    entries.extend(audit.alternatives)
    for step in audit.chain:
        if step.entry_before:
            entries.append(step.entry_before)
        entries.append(step.entry_after)
    return entries


def _entry_disposition(
    entry: ScheduleEntry,
    audits: list[AuditItem],
    demand_status: str,
) -> str:
    if entry.status == EntryStatus.CANCELLED:
        source_confirmed = demand_status in {"cancelled", "hospitalised"} and any(
            audit.kind == AuditKind.SERVICE_CANCELLATION
            and audit.evidence_refs
            and entry.id in audit.entry_ids
            and audit.id in entry.audit_ids
            for audit in audits
        )
        event_confirmed = any(
            audit.kind in {AuditKind.SERVICE_CANCELLATION, AuditKind.ESCORT_ADJUSTMENT}
            and audit.trigger_event_id is not None
            and audit.evidence_refs
            and entry.id in audit.entry_ids
            and audit.id in entry.audit_ids
            for audit in audits
        )
        confirmed = source_confirmed or event_confirmed
        return "confirmed_cancelled" if confirmed else "suppressed_with_audit"
    return {
        EntryStatus.SCHEDULED: "scheduled",
        EntryStatus.NEEDS_REVIEW: "needs_review",
        EntryStatus.UNASSIGNED: "unassigned",
    }[entry.status]


def _entry_uses_uncertainty(entry: ScheduleEntry) -> bool:
    if "supervisor_hard_bypass" in entry.constraint_flags:
        return False
    return bool(
        entry.data_gap_ids
        or any(item.confidence in {"low", "seed"} for item in entry.source_evidence)
        or "gender_ok_unverified" in entry.constraint_flags
        or "seed_skill_unverified" in entry.constraint_flags
    )


def _disposition_reason(entry: ScheduleEntry, audits: dict[str, AuditItem]) -> str | None:
    for audit_id in entry.audit_ids:
        audit = audits.get(audit_id)
        if audit and audit.reasons:
            return audit.reasons[0].code.value
    return entry.review_reasons[0].code.value if entry.review_reasons else None


def _gap_reason_code(gap: DataGap) -> ReviewReasonCode:
    return {
        "gender": ReviewReasonCode.GENDER_UNKNOWN,
        "skill": ReviewReasonCode.SKILL_MISMATCH,
        "route": ReviewReasonCode.ROUTE_UNQUALIFIED,
        "availability": ReviewReasonCode.NOT_WORKING_DAY,
    }.get(gap.kind, ReviewReasonCode.NO_QUALIFIED_WORKER)


def _audit_counts(audits: Iterable[AuditItem]) -> dict[str, int]:
    counts = Counter()
    for audit in audits:
        counts["total"] += 1
        counts[f"blocking:{str(audit.blocking).lower()}"] += 1
        counts[f"severity:{audit.severity.value}"] += 1
        counts[f"kind:{audit.kind.value}"] += 1
    return dict(sorted(counts.items()))


def _error_sort_key(error: ReconciliationError) -> tuple:
    return (
        error.code,
        tuple(error.demand_ids),
        tuple(error.entry_ids),
        tuple(error.audit_ids),
        error.message,
    )
