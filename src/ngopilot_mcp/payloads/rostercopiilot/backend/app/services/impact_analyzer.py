"""Impact analysis facade.

The repair engine (`app.engine.repair`) produces per-event ImpactReports as a
by-product of repairing; this module exposes preview-only analysis (simulate)
and summary helpers for the API and the Excel export.
"""
from __future__ import annotations

from ..domain import (
    ChangeEvent,
    ImpactReport,
    ScheduleVersion,
    Severity,
)
from .state import AppState


def analyze_changes(state: AppState, events: list[ChangeEvent],
                    base: ScheduleVersion | None = None
                    ) -> tuple[ScheduleVersion, list[ImpactReport]]:
    """Dry-run: what would happen if these events were applied now."""
    return state.simulate(events, base)


def overall_risk(reports: list[ImpactReport]) -> Severity:
    order = {Severity.INFO: 0, Severity.WARNING: 1, Severity.HIGH: 2}
    return max((r.risk_level for r in reports), key=lambda s: order[s],
               default=Severity.INFO)


def summarize_reports(reports: list[ImpactReport]) -> dict:
    return {
        "events": len(reports),
        "risk_level": overall_risk(reports).value,
        "requires_review": any(r.requires_review for r in reports),
        "impact_count": sum(len(r.impacts) for r in reports),
        "blocking_audits": sum(
            1 for r in reports for i in r.impacts if i.requires_review),
    }
