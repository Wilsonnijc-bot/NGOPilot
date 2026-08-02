"""Scheduler bridge — snapshot in, draft ``ScheduleVersion`` out.

Orchestrates the scheduler-first pipeline (ENGINEERING_SPEC.md §5):

1. generate dated demand from the snapshot (``generator``);
2. lower it into the engine's dataset (``adapter``);
3. draft a baseline roster with the existing greedy engine;
4. apply leave / cancellation / escort change events as a repair pass;
5. surface declared data gaps as reviewable audit items (RB-DATA-01);
6. re-validate the accepted entries with the independent hard-rule validator.

No Excel is read at any step. The result carries the draft version, the impact
reports, the surfaced data gaps and the validator output so callers can assert
zero hard violations.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..domain import (
    AuditItem,
    AuditKind,
    DataGap,
    HardViolation,
    ImpactReport,
    ManualReviewReason,
    MockDataset,
    ReviewReasonCode,
    ScheduleVersion,
    SchedulerSnapshot,
    Severity,
)
from ..engine import apply_changes, build_baseline, validate_entries
from .adapter import to_dataset
from .generator import GeneratedDemands, generate_demands
from .reconciliation import finalize_version_provenance, reconcile_weekly_demands

_GAP_RULE_REF = {
    "gender": "RB-GEND-01",
    "skill": "RB-SKILL-01",
    "route": "RB-SKILL-03",
    "week_pattern": "RB-FIX-02",
    "duty_requirement": "RB-DUTY-01",
    "availability": "RB-LEAVE-01",
}


@dataclass
class SchedulerResult:
    """Everything a caller needs from one scheduler run."""

    snapshot: SchedulerSnapshot
    generated: GeneratedDemands
    dataset: MockDataset
    baseline: ScheduleVersion
    version: ScheduleVersion
    reports: list[ImpactReport] = field(default_factory=list)
    data_gap_audits: list[AuditItem] = field(default_factory=list)
    violations: list[HardViolation] = field(default_factory=list)

    @property
    def has_hard_violations(self) -> bool:
        return bool(self.violations)


def run_scheduler(snapshot: SchedulerSnapshot) -> SchedulerResult:
    """Draft a roster for one week from a rule-based snapshot."""
    generated = generate_demands(snapshot)
    dataset = to_dataset(snapshot, generated)

    baseline = build_baseline(dataset)
    # Baseline IDs are finalized before a repair child copies them.  Generated
    # gap/suppression audits belong only to the accepted final version below.
    finalize_version_provenance(
        baseline,
        generated,
        include_generated_audits=False,
    )

    events = generated.leave_events
    if events:
        version, reports = apply_changes(dataset, baseline, events)
    else:
        version, reports = baseline, []

    # Kept as a compatibility diagnostic list.  The authoritative version
    # audits are created/deduplicated by the provenance finalizer.
    gap_audits = _data_gap_audits(generated.data_gaps)
    finalize_version_provenance(version, generated, reports=reports)

    # Recompute leave bookkeeping for an independent validation pass: the
    # accepted (SCHEDULED / NEEDS_REVIEW) entries must never violate a hard rule.
    leaves = _leaves_from_events(events)
    violations = validate_entries(dataset, version.entries, leaves)
    reconcile_weekly_demands(
        version,
        generated,
        hard_violation_count=len(violations),
    )

    return SchedulerResult(
        snapshot=snapshot,
        generated=generated,
        dataset=dataset,
        baseline=baseline,
        version=version,
        reports=reports,
        data_gap_audits=gap_audits,
        violations=violations,
    )


def _data_gap_audits(gaps: list[DataGap]) -> list[AuditItem]:
    audits: list[AuditItem] = []
    for i, gap in enumerate(gaps, start=1):
        audits.append(AuditItem(
            id=f"datagap-snapshot-{i:03d}",
            kind=AuditKind.DATA_GAP,
            severity=Severity.HIGH if gap.blocking else Severity.WARNING,
            blocking=gap.blocking,
            reason=gap.message,
            reasons=[ManualReviewReason(
                code=(ReviewReasonCode.GENDER_UNKNOWN if gap.kind == "gender"
                      else ReviewReasonCode.SKILL_MISMATCH if gap.kind == "skill"
                      else ReviewReasonCode.NO_QUALIFIED_WORKER),
                message=gap.message,
                params={"entity_id": gap.entity_id} if gap.entity_id else {},
                rule_ref=_GAP_RULE_REF.get(gap.kind),
            )],
        ))
    return audits


def _leaves_from_events(events) -> set[tuple[str, object, str]]:
    from ..domain import Period
    leaves: set[tuple[str, object, str]] = set()
    for ev in events:
        if ev.worker_id is None:
            continue
        periods = [ev.period.value] if ev.period else [Period.AM.value, Period.PM.value]
        for p in periods:
            leaves.add((ev.worker_id, ev.change_date, p))
    return leaves
