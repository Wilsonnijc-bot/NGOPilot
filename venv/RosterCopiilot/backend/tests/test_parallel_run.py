from __future__ import annotations

import csv
import json
import subprocess
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.domain import ScheduleEntry, ScheduleVersion, canonical_json, stable_id
from app.evaluation.parallel_run import (
    CSV_LEDGER_COLUMNS,
    ParallelRunValidationError,
    canonical_report_json,
    evaluate_parallel_run,
)
from app.exporter.division_writer import render_export_placement_values
from app.scheduler.reconciliation import version_content_hash


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "backend" / "scripts" / "run_parallel_review.py"


def _entry(week_start: date, suffix: str, *, status: str, worker: bool) -> dict:
    return {
        "id": f"ent_{week_start.isoformat()}_{suffix}",
        "demand_id": f"dem_{week_start.isoformat()}_{suffix}",
        "schedule_date": week_start.isoformat(),
        "weekday": 1,
        "period": "AM",
        "session_index": 1,
        "worker_id": "worker-1" if worker else None,
        "worker_name": "Fixture Worker" if worker else None,
        "service_code": "HC",
        "elder_id": "elder-1",
        "elder_name": "Fixture Elder",
        "status": status,
        "notes": "detail note" if worker else None,
    }


def _generated_run(week_start: date) -> tuple[dict, ScheduleEntry]:
    scheduled = _entry(week_start, "scheduled", status="scheduled", worker=True)
    unassigned = _entry(week_start, "unassigned", status="unassigned", worker=False)
    cancelled = _entry(week_start, "cancelled", status="cancelled", worker=False)
    audit_ids = {
        "unassigned": f"aud_{week_start.isoformat()}_unassigned",
        "cancelled": f"aud_{week_start.isoformat()}_cancelled",
        "suppressed": f"aud_{week_start.isoformat()}_suppressed",
    }
    unassigned["audit_ids"] = [audit_ids["unassigned"]]
    cancelled["audit_ids"] = [audit_ids["cancelled"]]
    dispositions = [
        {
            "demand_id": scheduled["demand_id"],
            "disposition": "scheduled",
            "entry_id": scheduled["id"],
        },
        {
            "demand_id": unassigned["demand_id"],
            "disposition": "unassigned",
            "entry_id": unassigned["id"],
            "audit_ids": [audit_ids["unassigned"]],
        },
        {
            "demand_id": cancelled["demand_id"],
            "disposition": "confirmed_cancelled",
            "entry_id": cancelled["id"],
            "audit_ids": [audit_ids["cancelled"]],
        },
        {
            "demand_id": f"dem_{week_start.isoformat()}_suppressed",
            "disposition": "suppressed_with_audit",
            "entry_id": None,
            "audit_ids": [audit_ids["suppressed"]],
        },
    ]
    version_id = f"ver_{week_start.isoformat()}"
    reconciliation = {
        "weekly_demand_total": 4,
        "scheduled": 1,
        "needs_review": 0,
        "unassigned": 1,
        "confirmed_cancelled": 1,
        "suppressed_with_audit": 1,
        "dispositions": dispositions,
        "active_entry_ids": [scheduled["id"]],
        "review_entry_ids": [],
        "unassigned_entry_ids": [unassigned["id"]],
        "cancellation_entry_ids": [cancelled["id"]],
        "suppression_demand_ids": [f"dem_{week_start.isoformat()}_suppressed"],
        "pending_audit_counts": {
            "total": 1,
            "blocking:true": 1,
            "severity:high": 1,
            "kind:unassigned_task": 1,
        },
        "decided_audit_counts": {
            "total": 2,
            "blocking:false": 2,
            "severity:info": 2,
            "kind:service_cancellation": 2,
        },
        "placement_count": 1,
        "changed_cell_count": 2,
        "hard_violation_count": 0,
        "export_failure_count": 0,
        "errors": [],
        "publication_state": "blocked",
        "version_id": version_id,
        "content_hash": "pending",
    }
    version_payload = {
        "id": version_id,
        "kind": "manual_edit",
        "created_at": "2026-01-01T00:00:00Z",
        "week_start": week_start.isoformat(),
        "entries": [scheduled, unassigned, cancelled],
        "audit_items": [
            {
                "id": audit_ids["unassigned"],
                "kind": "unassigned_task",
                "severity": "high",
                "blocking": True,
                "status": "pending",
                "reason": "synthetic unassigned fixture",
                "demand_ids": [unassigned["demand_id"]],
                "entry_ids": [unassigned["id"]],
            },
            {
                "id": audit_ids["cancelled"],
                "kind": "service_cancellation",
                "severity": "info",
                "blocking": False,
                "status": "approved",
                "reason": "synthetic cancellation fixture",
                "demand_ids": [cancelled["demand_id"]],
                "entry_ids": [cancelled["id"]],
            },
            {
                "id": audit_ids["suppressed"],
                "kind": "service_cancellation",
                "severity": "info",
                "blocking": False,
                "status": "approved",
                "reason": "synthetic suppression fixture",
                "demand_ids": [f"dem_{week_start.isoformat()}_suppressed"],
                "entry_ids": [],
            },
        ],
        "unassigned": [unassigned],
        "demand_dispositions": dispositions,
        "reconciliation": reconciliation,
        "summary": {"runtime_ms": 999.0},
    }
    parsed = ScheduleVersion.model_validate(version_payload)
    reconciliation["content_hash"] = version_content_hash(parsed)
    version_payload["reconciliation"] = deepcopy(reconciliation)
    placement = {
        "demand_id": scheduled["demand_id"],
        "entry_id": scheduled["id"],
        "disposition": "scheduled",
        "version_id": version_id,
        "status": "scheduled",
        "worker_name": "Fixture Worker",
        "schedule_date": week_start.isoformat(),
        "period": "AM",
        "service_code": "HC",
        "target": "Fixture Elder",
        "assignment_cell": "恆常服務!B2",
        "detail_cell": "恆常服務!B3",
        "audit_ids": [],
        "data_gap_ids": [],
        "source_evidence_ids": [],
        "source_refs": [],
    }
    run = {
        "run_id": f"run-{week_start.isoformat()}",
        "week_start": week_start.isoformat(),
        "version": version_payload,
        "reconciliation": deepcopy(reconciliation),
        "export_report": {
            "reconciliation": deepcopy(reconciliation),
            "publication_state": "blocked",
            "placements": [placement],
            "validator_violations": [],
            "export_failures": [],
        },
        "review_decisions": (
            [{"action": "approve"}, {"action": "reject"}]
            if week_start.day == 5
            else []
        ),
    }
    return run, ScheduleEntry.model_validate(scheduled)


def _diff(
    week_start: date,
    *,
    kind: str,
    cell_or_ref: str,
    generated_exists: bool,
    manual_exists: bool,
    generated_value,
    manual_value,
    demand_id: str | None = None,
    manual_key: str | None = None,
    entry_id: str | None = None,
    category: str = "expected",
) -> dict:
    identity = {
        "week_start": week_start,
        "kind": kind,
        "demand_id": demand_id,
        "manual_key": manual_key,
        "entry_id": entry_id,
    }
    if kind in {"placement_cell", "manual_only"}:
        identity["cell"] = cell_or_ref
    row = {
        "diff_id": stable_id("dif_", "parallel_run_diff", identity),
        "week_start": week_start.isoformat(),
        "demand_id": demand_id,
        "manual_key": manual_key,
        "entry_id": entry_id,
        "cell_or_ref": cell_or_ref,
        "generated_exists": generated_exists,
        "manual_exists": manual_exists,
        "generated_value": generated_value,
        "manual_value": manual_value,
        "category": category,
        "note": "synthetic comparison classification",
    }
    if category == "reviewer_approved":
        row.update({
            "reviewer": "fixture-reviewer",
            "reviewed_at": "2026-01-20T10:00:00Z",
        })
    if category == "blocking":
        row["blocking_reason"] = "synthetic unresolved mismatch"
    return row


def _write_case(
    base: Path,
    week_start: date,
    *,
    assignment_diff: bool,
    disposition_diff: bool,
    manual_only: bool,
) -> dict:
    slug = week_start.isoformat()
    run, entry = _generated_run(week_start)
    run_path = base / f"run-{slug}.json"
    run_path.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")

    assignment_value, detail_value = render_export_placement_values(entry)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "恆常服務"
    sheet["B2"] = "HC:Manual Fixture" if assignment_diff else assignment_value
    sheet["B3"] = detail_value
    if manual_only:
        sheet["Z1"] = "Manual-only fixture assignment"
    workbook_path = base / f"manual-{slug}.xlsx"
    workbook.save(workbook_path)

    observations = []
    for suffix, generated in (
        ("unassigned", "unassigned"),
        ("cancelled", "confirmed_cancelled"),
        ("suppressed", "suppressed_with_audit"),
    ):
        manual = "scheduled" if disposition_diff and suffix == "unassigned" else generated
        observations.append({
            "demand_id": f"dem_{slug}_{suffix}",
            "manual_disposition": manual,
            "reference": f"manual-ledger:{suffix}",
        })
    diffs = []
    if assignment_diff:
        diffs.append(_diff(
            week_start,
            kind="placement_cell",
            demand_id=entry.demand_id,
            entry_id=entry.id,
            cell_or_ref="恆常服務!B2",
            generated_exists=True,
            manual_exists=True,
            generated_value=assignment_value,
            manual_value="HC:Manual Fixture",
        ))
    if disposition_diff:
        diffs.append(_diff(
            week_start,
            kind="disposition",
            demand_id=f"dem_{slug}_unassigned",
            entry_id=f"ent_{slug}_unassigned",
            cell_or_ref="manual-ledger:unassigned",
            generated_exists=True,
            manual_exists=True,
            generated_value="unassigned",
            manual_value="scheduled",
            category="reviewer_approved",
        ))
    manual_only_rows = []
    if manual_only:
        manual_only_rows.append({"manual_key": f"manual-{slug}-extra", "cell": "恆常服務!Z1"})
        diffs.append(_diff(
            week_start,
            kind="manual_only",
            manual_key=f"manual-{slug}-extra",
            cell_or_ref="恆常服務!Z1",
            generated_exists=False,
            manual_exists=True,
            generated_value=None,
            manual_value="Manual-only fixture assignment",
        ))
    ledger = {
        "schema_version": "1.0",
        "week_start": slug,
        "disposition_comparisons": observations,
        "manual_only": manual_only_rows,
        "diffs": diffs,
    }
    ledger_path = base / f"ledger-{slug}.json"
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    return {
        "week_start": slug,
        "generated_run": run_path.name,
        "manual_workbook": workbook_path.name,
        "comparison_ledger": ledger_path.name,
    }


def _fixture(tmp_path: Path, *, scope: str = "real_parallel_run") -> tuple[Path, dict]:
    weeks = [
        _write_case(
            tmp_path,
            date(2026, 1, 5),
            assignment_diff=True,
            disposition_diff=True,
            manual_only=False,
        ),
        _write_case(
            tmp_path,
            date(2026, 1, 12),
            assignment_diff=False,
            disposition_diff=False,
            manual_only=True,
        ),
    ]
    manifest = {
        "schema_version": "1.0",
        "scope": scope,
        "weeks": weeks,
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return path, manifest


def _write_manifest(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _ledger_path(tmp_path: Path, manifest: dict, index: int = 0) -> Path:
    return tmp_path / manifest["weeks"][index]["comparison_ledger"]


def test_e01_report_is_byte_deterministic_and_omits_runtime_and_paths(tmp_path):
    manifest_path, _ = _fixture(tmp_path)
    first = canonical_report_json(evaluate_parallel_run(manifest_path))
    second = canonical_report_json(evaluate_parallel_run(manifest_path))

    assert first == second
    assert "runtime_ms" not in first
    assert str(tmp_path) not in first
    assert "created_at" not in first
    assert "published_at" not in first


def test_e02_two_weeks_conserve_demands_cells_and_dispositions(tmp_path):
    manifest_path, _ = _fixture(tmp_path)
    report = evaluate_parallel_run(manifest_path)

    assert report["engineering_gate"]["state"] == "passed"
    assert report["comparison_gate"]["state"] == "passed"
    assert report["ngo_gate"] == "pending"
    assert report["total"]["week_count"] == 2
    assert report["total"]["demand_counts"]["total"] == 8
    assert report["total"]["reconciliation_counts"]["disposition_total"] == 8
    assert report["total"]["placement_cell_comparison_counts"] == {
        "placement_count": 2,
        "cell_total": 4,
        "matched": 3,
        "differences": 1,
    }
    assert report["total"]["disposition_comparison_counts"] == {
        "nonplacement_total": 6,
        "matched": 5,
        "differences": 1,
        "manual_only": 1,
    }
    # A manual-only workbook row is tracked separately; it never changes demand.
    assert report["total"]["diff_category_counts"]["manual_only"] == 1
    assert report["total"]["demand_counts"]["total"] == 8


def test_e02_csv_ledger_uses_the_same_strict_comparison_contract(tmp_path):
    manifest_path, manifest = _fixture(tmp_path)
    ledger_path = _ledger_path(tmp_path, manifest, index=1)
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    csv_path = ledger_path.with_suffix(".csv")
    rows = [{
        "schema_version": "1.0",
        "week_start": ledger["week_start"],
        "row_type": "meta",
    }]
    rows.extend({
        "row_type": "disposition",
        "demand_id": item["demand_id"],
        "manual_disposition": item["manual_disposition"],
        "reference": item["reference"],
    } for item in ledger["disposition_comparisons"])
    rows.extend({
        "row_type": "manual_only",
        "manual_key": item["manual_key"],
        "cell": item["cell"],
    } for item in ledger["manual_only"])
    for item in ledger["diffs"]:
        rows.append({
            **item,
            "row_type": "diff",
            "generated_exists": str(item["generated_exists"]).lower(),
            "manual_exists": str(item["manual_exists"]).lower(),
            "generated_value_json": json.dumps(
                item["generated_value"], ensure_ascii=False
            ),
            "manual_value_json": json.dumps(item["manual_value"], ensure_ascii=False),
        })
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_LEDGER_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    manifest["weeks"][1]["comparison_ledger"] = csv_path.name
    _write_manifest(manifest_path, manifest)

    report = evaluate_parallel_run(manifest_path)
    assert report["engineering_gate"]["state"] == "passed"
    assert report["total"]["diff_category_counts"]["manual_only"] == 1


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("missing_category", "LEDGER_SCHEMA_INVALID"),
        ("duplicate", "LEDGER_SCHEMA_INVALID"),
        ("unknown_diff", "LEDGER_DIFF_SET_MISMATCH"),
        ("wrong_value", "LEDGER_DIFF_MISMATCH"),
    ],
)
def test_e03_ledger_is_fail_closed(tmp_path, mutation, expected_code):
    manifest_path, manifest = _fixture(tmp_path)
    path = _ledger_path(tmp_path, manifest)
    ledger = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "missing_category":
        ledger["diffs"][0].pop("category")
    elif mutation == "duplicate":
        ledger["diffs"].append(deepcopy(ledger["diffs"][0]))
    elif mutation == "unknown_diff":
        ledger["diffs"][0]["diff_id"] = "dif_unknown"
    elif mutation == "wrong_value":
        ledger["diffs"][0]["manual_value"] = "wrong ledger copy"
    path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ParallelRunValidationError) as raised:
        evaluate_parallel_run(manifest_path)
    assert raised.value.code == expected_code


@pytest.mark.parametrize(
    ("target", "expected_code"),
    [
        ("run_week", "GENERATED_RUN_WEEK_MISMATCH"),
        ("placement", "GENERATED_PLACEMENT_LINK_INVALID"),
        ("cell", "LEDGER_DIFF_SET_MISMATCH"),
    ],
)
def test_e03_run_and_placement_mismatches_fail_closed(tmp_path, target, expected_code):
    manifest_path, manifest = _fixture(tmp_path)
    run_path = tmp_path / manifest["weeks"][0]["generated_run"]
    run = json.loads(run_path.read_text(encoding="utf-8"))
    if target == "run_week":
        run["week_start"] = "2026-01-19"
    elif target == "placement":
        run["export_report"]["placements"][0]["entry_id"] = "ent_missing"
    else:
        run["export_report"]["placements"][0]["assignment_cell"] = "恆常服務!C2"
    run_path.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ParallelRunValidationError) as raised:
        evaluate_parallel_run(manifest_path)
    assert raised.value.code == expected_code


def test_e03_all_categories_are_counted_and_blocking_stops_comparison(tmp_path):
    manifest_path, manifest = _fixture(tmp_path)
    path = _ledger_path(tmp_path, manifest, index=1)
    ledger = json.loads(path.read_text(encoding="utf-8"))
    ledger["diffs"][0]["category"] = "blocking"
    ledger["diffs"][0]["blocking_reason"] = "manual-only item unresolved"
    path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")

    report = evaluate_parallel_run(manifest_path)
    assert report["engineering_gate"]["state"] == "passed"
    assert report["comparison_gate"]["state"] == "blocked"
    assert report["total"]["diff_category_counts"] == {
        "total": 3,
        "expected": 1,
        "reviewer_approved": 1,
        "blocking": 1,
        "manual_only": 1,
    }
    assert len(report["comparison_gate"]["blocking_ids"]) == 1


def _add_synthetic_evidence(manifest: dict) -> dict:
    payload = deepcopy(manifest)
    payload["ngo_master_data"] = {
        "confirmed": True,
        "evidence_refs": ["synthetic-master-data-evidence"],
    }
    for index, week in enumerate(payload["weeks"], start=1):
        week["roster_owner_signoff"] = {
            "reviewer": f"synthetic-roster-owner-{index}",
            "signed_at": f"2026-01-{20 + index:02d}T10:00:00Z",
            "evidence_ref": f"synthetic-signoff-{index}",
        }
    return payload


def test_e04_ngo_gate_is_separate_from_engineering_and_can_accept_full_evidence(tmp_path):
    manifest_path, manifest = _fixture(tmp_path)
    pending = evaluate_parallel_run(manifest_path)
    assert pending["engineering_gate"]["state"] == "passed"
    assert pending["ngo_gate"] == "pending"
    assert pending["claims_ngo_acceptance"] is False

    _write_manifest(manifest_path, _add_synthetic_evidence(manifest))
    accepted = evaluate_parallel_run(manifest_path)
    assert accepted["ngo_gate"] == "accepted"
    assert accepted["claims_ngo_acceptance"] is True
    assert "not a staff-readiness" in accepted["interpretation"]


def test_e05_fixture_smoke_never_claims_ngo_acceptance(tmp_path):
    manifest_path, manifest = _fixture(tmp_path, scope="fixture_smoke")
    payload = _add_synthetic_evidence(manifest)
    payload["scope"] = "fixture_smoke"
    _write_manifest(manifest_path, payload)

    report = evaluate_parallel_run(manifest_path)
    assert report["scope"] == "fixture_smoke"
    assert report["ngo_gate"] == "not_evaluated"
    assert report["claims_ngo_acceptance"] is False


def test_cli_exit_codes_and_structured_output(tmp_path):
    manifest_path, manifest = _fixture(tmp_path)
    output = tmp_path / "report.json"
    success = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--manifest",
            str(manifest_path),
            "--json",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert success.returncode == 0, success.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["ngo_gate"] == "pending"
    assert "engineering=passed comparison=passed ngo=pending" in success.stdout

    path = _ledger_path(tmp_path, manifest, index=1)
    ledger = json.loads(path.read_text(encoding="utf-8"))
    ledger["diffs"][0]["category"] = "blocking"
    ledger["diffs"][0]["blocking_reason"] = "synthetic CLI blocker"
    path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    blocked = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--manifest",
            str(manifest_path),
            "--json",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert blocked.returncode != 0
    blocked_report = json.loads(output.read_text(encoding="utf-8"))
    assert blocked_report["status"] == "blocked"
    assert blocked_report["comparison_gate"]["state"] == "blocked"

    ledger["diffs"][0].pop("category")
    path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    failure = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--manifest",
            str(manifest_path),
            "--json",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert failure.returncode != 0
    failed_report = json.loads(output.read_text(encoding="utf-8"))
    assert failed_report["status"] == "failed"
    assert failed_report["error"]["code"] == "LEDGER_SCHEMA_INVALID"


def test_exporter_public_render_seam_preserves_exact_cell_grammar():
    entry = ScheduleEntry.model_validate({
        "id": "entry-render-parity",
        "demand_id": "demand-render-parity",
        "schedule_date": "2026-01-05",
        "weekday": 1,
        "period": "AM",
        "worker_id": "worker-1",
        "service_code": "ESC",
        "elder_name": "Fixture Elder",
        "start_time": "09:15",
        "end_time": "10:45",
        "destination": "Fixture Clinic",
        "notes": "fixture note",
    })
    assert render_export_placement_values(entry) == (
        "Esc:Fixture Elder",
        "09:15-10:45 Fixture Clinic fixture note",
    )
