"""Canonical-promotion preview for Phase 1 imports.

Promotion remains conservative: division-sheet fixed services are the source of
truth; HC and transfer rows enrich or flag conflicts. The scheduler's mock
dataset is not replaced in Phase 1.
"""
from __future__ import annotations

from typing import Any

from .base import ImportResult
from .division_models import DivisionImportResult


def build_canonical_preview(
    *,
    division: DivisionImportResult,
    skills: ImportResult[dict[str, Any]],
    transfers: ImportResult[dict[str, Any]],
    hc: ImportResult[dict[str, Any]],
    escort: ImportResult[dict[str, Any]],
    resolution: ImportResult[dict[str, Any]],
) -> dict[str, Any]:
    worker_aliases = [worker.display_name for worker in division.workers]
    fixed_services = [
        {
            "source_ref": c.source_ref,
            "service_code": c.service_code,
            "service_code_raw": c.service_code_raw,
            "elder_alias": c.elder_alias,
            "worker_alias": c.worker_alias,
            "weekday": c.weekday,
            "period": c.period,
            "session_index": c.session_index,
            "week_pattern_raw": c.week_pattern_raw,
            "source_of_truth": "division",
        }
        for c in division.fixed_service_candidates
    ]
    escort_requests = [
        r.record for r in escort.records
        if r.record and r.record.get("status") == "requested"
    ]
    hc_enrichment = [
        r.record for r in hc.records
        if r.record and r.record.get("section") not in {"section_marker", None}
    ]
    transfer_review = [r.record for r in transfers.records if r.record]
    return {
        "employees": {
            "count": len(worker_aliases),
            "aliases": worker_aliases,
            "source_of_truth": "division.worker_columns",
            "skill_profiles": len(skills.records),
        },
        "fixed_services": {
            "count": len(fixed_services),
            "records": fixed_services[:50],
            "source_of_truth": "division",
            "hc_enrichment_count": len(hc_enrichment),
        },
        "escort_requests": {
            "count": len(escort_requests),
            "records": escort_requests[:50],
            "source_of_truth": "escort_workbook",
        },
        "transfer_review": {
            "count": len(transfer_review),
            "source_of_truth": "manual_review_before_promotion",
        },
        "alias_resolution": {
            "exact_links": len(resolution.records),
            "ambiguities": len(resolution.ambiguities),
        },
    }
