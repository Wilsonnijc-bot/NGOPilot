"""Scheduler bridge tests: snapshot → draft ScheduleVersion via the greedy engine.

Covers ENGINEERING_SPEC.md §10.3–10.5: baseline solve from NGO-style tasks,
repair for leave, and zero hard-rule violations for accepted schedules.
"""
from pathlib import Path

import pytest

from app.domain import AuditKind, EntryStatus, VersionKind
from app.engine import build_baseline, validate_entries
from app.scheduler import generate_demands, representative_snapshot, run_scheduler
from app.scheduler.adapter import to_dataset


@pytest.fixture(scope="module")
def result():
    return run_scheduler(representative_snapshot())


def test_run_produces_a_schedule_version_with_the_expected_shape(result):
    version = result.version
    assert version.kind == VersionKind.REPAIR  # a leave event triggers repair
    assert version.entries
    assert version.summary["coverage_rate"] > 0
    assert version.audit_items
    # unassigned demand is surfaced as entries + metrics, never dropped
    assert version.summary["unassigned_count"] == len(
        [e for e in version.entries if e.status == EntryStatus.UNASSIGNED])


def test_accepted_schedule_has_zero_hard_violations(result):
    assert result.violations == []
    assert result.version.summary["hard_constraint_violations"] == 0


def test_baseline_before_repair_is_also_clean():
    snapshot = representative_snapshot()
    generated = generate_demands(snapshot)
    dataset = to_dataset(snapshot, generated)
    baseline = build_baseline(dataset)
    assert validate_entries(dataset, baseline.entries, leaves=set()) == []
    assert baseline.summary["hard_constraint_violations"] == 0


def test_exclusive_worker_leave_proposes_cancellation_not_substitution(result):
    exclusive_cancels = [a for a in result.version.audit_items
                         if a.kind == AuditKind.EXCLUSIVE_CANCELLATION]
    # W1 (娥) is off Monday AM and owns two exclusive E+RO services that morning
    assert len(exclusive_cancels) == 2
    assert all(a.blocking for a in exclusive_cancels)
    # the exclusive services are never handed to a substitute worker
    for entry in result.version.entries:
        if entry.origin_fixed_service_id in {"FS-ERO-1", "FS-ERO-2"}:
            assert entry.status in (EntryStatus.AFFECTED, EntryStatus.CANCELLED)
            assert entry.worker_id == "W1"


def test_leave_repair_marks_affected_entries(result):
    affected = [e for e in result.version.entries
                if e.status == EntryStatus.AFFECTED]
    assert affected, "leave must produce affected entries, not silent removal"
    assert all(e.worker_id == "W1" for e in affected)
    assert result.reports, "repair must yield an impact report"


def test_unknown_gender_escort_becomes_a_data_gap_review(result):
    # the escort for the unknown-gender elder cannot be verified -> unassigned
    escort = next(e for e in result.version.entries
                  if e.origin_escort_request_id == "ESC-1")
    assert escort.status == EntryStatus.UNASSIGNED
    assert any(a.kind == AuditKind.DATA_GAP for a in result.version.audit_items)
    # the snapshot-level worker gender gap is surfaced too
    assert any(a.id.startswith("datagap-snapshot") for a in result.data_gap_audits)


def test_snapshot_needs_no_excel_import_route():
    # functional: the whole pipeline runs from an in-memory fixture
    snapshot = representative_snapshot()
    assert snapshot.source_note and "import" in snapshot.source_note.lower()
    run_scheduler(snapshot)

    # static: the scheduler package must not depend on the importer or openpyxl
    pkg = Path(__file__).resolve().parents[1] / "app" / "scheduler"
    for module in pkg.glob("*.py"):
        source = module.read_text(encoding="utf-8")
        assert "import openpyxl" not in source
        assert "app.importer" not in source
        assert "from ..importer" not in source
