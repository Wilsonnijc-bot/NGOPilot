#!/usr/bin/env python3
"""RosterCopiilot benchmark runner.

Runs predefined scheduling scenarios against the deterministic engine and
reports quality metrics. Exits non-zero if ANY hard constraint is violated
or a scenario-specific expectation fails.

Usage:
    python backend/scripts/run_benchmark.py [--json PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain import (  # noqa: E402
    AuditKind,
    ChangeEvent,
    ChangeType,
    EntryStatus,
    Period,
    ServiceCode,
)
from app.engine import apply_changes, build_baseline  # noqa: E402
from app.mockdata import example_changes, generate_dataset  # noqa: E402

DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"
DIVISION_WORKBOOK = DOCS_DIR / "照顧員工作分工表2026(HKU).xlsx"
HC_WORKBOOK = DOCS_DIR / "2026_HC 時間表(HKU).xlsx"
ESCORT_WORKBOOK = DOCS_DIR / "護送個案總表(2026)(HKU).xlsx"


def _leave(worker_id, on, period=None, id_="bm"):
    return ChangeEvent(id=id_, type=ChangeType.LEAVE, change_date=on,
                       period=period, worker_id=worker_id, reason="benchmark")


class Scenario:
    def __init__(self, sid: str, name: str, seed: int, events_fn=None, checks=None):
        self.sid, self.name, self.seed = sid, name, seed
        self.events_fn = events_fn or (lambda ds, base: [])
        self.checks = checks or []

    def run(self) -> dict:
        dataset = generate_dataset(self.seed)
        baseline = build_baseline(dataset)
        events = self.events_fn(dataset, baseline)
        if events:
            version, _ = apply_changes(dataset, baseline, events)
        else:
            version = baseline
        m = version.summary
        row = {
            "scenario": self.sid,
            "name": self.name,
            "seed": self.seed,
            "events": len(events),
            "coverage_rate": m["coverage_rate"],
            "unassigned_count": m["unassigned_count"],
            "manual_review_total": m["manual_review_total"],
            "manual_review_blocking": m["manual_review_blocking"],
            "hard_constraint_violations": m["hard_constraint_violations"],
            "change_distance": m.get("change_distance_from_original", 0),
            "runtime_ms": m["runtime_ms"],
            "check_failures": [],
        }
        for check in self.checks:
            err = check(dataset, baseline, version)
            if err:
                row["check_failures"].append(err)
        return row


# ---------------------------------------------------------------- checks

def check_exclusive_cancellations(expected: int):
    def _check(ds, base, version):
        got = sum(1 for a in version.audit_items
                  if a.kind == AuditKind.EXCLUSIVE_CANCELLATION
                  and a.trigger_event_id)
        if got != expected:
            return f"expected {expected} exclusive cancellations, got {got}"
    return _check


def check_no_substitute_on_exclusive(ds, base, version):
    fixed = {fs.id: fs for fs in ds.fixed_services if fs.is_exclusive}
    for e in version.entries:
        if (e.origin_fixed_service_id in fixed
                and e.status in (EntryStatus.SCHEDULED, EntryStatus.NEEDS_REVIEW)
                and e.worker_id != fixed[e.origin_fixed_service_id].assigned_worker_id):
            return f"exclusive service {e.origin_fixed_service_id} substituted!"
    return None


def check_min_unassigned(n: int):
    def _check(ds, base, version):
        got = version.summary["unassigned_count"]
        if got < n:
            return f"expected >= {n} unassigned (scarcity), got {got}"
    return _check


def check_duty_still_covered(ds, base, version):
    if version.summary["center_duty_slots_below_required"] > 0:
        return "centre duty under-covered"
    return None


def check_change_distance_bounded(max_d: int):
    def _check(ds, base, version):
        d = version.summary.get("change_distance_from_original", 0)
        if d > max_d:
            return f"change distance {d} exceeds bound {max_d} (churn!)"
    return _check


def check_determinism(ds, base, version):
    again = build_baseline(ds)
    key = lambda v: [(e.worker_id, e.service_code.value, str(e.schedule_date),
                      e.period.value, e.session_index) for e in v.entries]
    if key(again) != key(base):
        return "baseline not deterministic"
    return None


# ---------------------------------------------------------------- scenarios

def _ev_extra_escort(ds, base):
    wed = ds.params.week_start + timedelta(days=2)
    from app.domain import EscortRequest
    return [ChangeEvent(
        id="bm-esc", type=ChangeType.ESCORT_NEW, change_date=wed, period=Period.AM,
        new_escort=EscortRequest(
            id="ER-BM1", service_date=wed, period=Period.AM,
            elder_id=ds.elders[20].id, destination="東區醫院", subject="眼科",
            appointment_time=None, transport="的士來回"),
        reason="benchmark extra escort")]


def _ev_duty_crunch(ds, base):
    """Three duty-skilled workers off on the same Monday."""
    ws = ds.params.week_start
    amc = [w.id for w in ds.employees
           if ServiceCode.DUTY_AMC in w.skills][:3]
    return [_leave(w, ws, id_=f"bm-crunch-{i}") for i, w in enumerate(amc)]


def _ev_gender_scarcity(ds, base):
    """W003 (only male bath specialist) off on his male-bath day."""
    fs = next(f for f in ds.fixed_services
              if f.service_code == ServiceCode.BATH and f.assigned_worker_id == "W003")
    on = ds.params.week_start + timedelta(days=fs.weekday - 1)
    return [_leave("W003", on, id_="bm-gender")]


SCENARIOS = [
    Scenario("S01", "baseline seed 2026", 2026,
             checks=[check_duty_still_covered, check_determinism]),
    Scenario("S02", "baseline seed 7", 7, checks=[check_duty_still_covered]),
    Scenario("S03", "baseline seed 99", 99, checks=[check_duty_still_covered]),
    Scenario("S04", "exclusive worker half-day leave (W001 Mon AM)", 2026,
             lambda ds, base: [_leave("W001", ds.params.week_start, Period.AM)],
             checks=[check_exclusive_cancellations(2),
                     check_no_substitute_on_exclusive,
                     check_change_distance_bounded(10)]),
    Scenario("S05", "escort-heavy worker full-day leave (W002 Tue)", 2026,
             lambda ds, base: [_leave("W002", ds.params.week_start + timedelta(days=1))],
             checks=[check_duty_still_covered, check_change_distance_bounded(12)]),
    Scenario("S06", "elder cancellation (hospitalised)", 2026,
             lambda ds, base: [e for e in example_changes(ds)
                               if e.type == ChangeType.ELDER_CANCELLATION],
             checks=[check_change_distance_bounded(6)]),
    Scenario("S07", "extra escort on over-quota morning", 2026, _ev_extra_escort,
             checks=[check_duty_still_covered, check_change_distance_bounded(8)]),
    Scenario("S08", "escort cancelled", 2026,
             lambda ds, base: [e for e in example_changes(ds)
                               if e.type == ChangeType.ESCORT_CANCELLED],
             checks=[check_change_distance_bounded(4)]),
    Scenario("S09", "batch: all example events together", 2026,
             lambda ds, base: example_changes(ds),
             checks=[check_no_substitute_on_exclusive,
                     check_change_distance_bounded(30)]),
    Scenario("S10", "duty crunch: 3 duty workers off same Monday", 2026,
             _ev_duty_crunch, checks=[check_change_distance_bounded(40)]),
    Scenario("S11", "gender scarcity: only male bath worker off", 2026,
             _ev_gender_scarcity,
             checks=[check_min_unassigned(1)]),
    Scenario("S12", "repair on alternate seed", 7,
             lambda ds, base: example_changes(ds)[:3]),
]


def _run_import_roundtrip() -> dict:
    start = time.perf_counter()
    failures: list[str] = []
    try:
        from app.exporter import compare_workbook_cells, save_ngo_division_workbook
        from app.importer import (
            parse_division_workbook,
            parse_escort_workbook,
            parse_hc_timetable_workbook,
            parse_skills_sheet,
            parse_transfer_log,
        )
        from app.importer.workbook_utils import load_workbook, require_sheet

        division = parse_division_workbook(DIVISION_WORKBOOK)
        hc = parse_hc_timetable_workbook(HC_WORKBOOK)
        escort = parse_escort_workbook(ESCORT_WORKBOOK)
        wb = load_workbook(DIVISION_WORKBOOK)
        skills = parse_skills_sheet(require_sheet(wb, "新同工跟服務紀錄表"))
        transfers = parse_transfer_log(require_sheet(wb, "個案轉移紀錄_2025"))
        silent = (
            division.summary["silently_dropped_cells"]
            + hc.summary.silently_dropped_cells
            + escort.summary.silently_dropped_cells
            + skills.summary.silently_dropped_cells
            + transfers.summary.silently_dropped_cells
        )
        if silent:
            failures.append(f"expected 0 silently dropped cells, got {silent}")
        if len(escort.records) != 111:
            failures.append(f"expected 111 escort requests, got {len(escort.records)}")
        mangled = sum(1 for a in hc.ambiguities
                      if a.code == "MANGLED_WEEK_PATTERN_DATE")
        if mangled != 6:
            failures.append(f"expected 6 HC mangled cells, got {mangled}")
        with tempfile.TemporaryDirectory(prefix="rostercopiilot_bm_") as tmp:
            out = save_ngo_division_workbook(
                template_path=DIVISION_WORKBOOK,
                output_dir=Path(tmp),
            )
            diffs = compare_workbook_cells(DIVISION_WORKBOOK, out)
            if diffs:
                failures.append(f"round-trip cell diff produced {len(diffs)} diff(s)")
    except Exception as exc:  # pragma: no cover - benchmark should report details
        failures.append(f"import round-trip failed: {exc}")
    runtime = round((time.perf_counter() - start) * 1000, 1)
    return {
        "scenario": "S13",
        "name": "real workbook import + NGO-format no-edit round-trip",
        "seed": 0,
        "events": 0,
        "coverage_rate": 1.0,
        "unassigned_count": 0,
        "manual_review_total": 0,
        "manual_review_blocking": 0,
        "hard_constraint_violations": 0,
        "change_distance": 0,
        "runtime_ms": runtime,
        "check_failures": failures,
    }


def _run_scheduler_snapshot() -> dict:
    """Benchmark the scheduler itself on the rule-based snapshot fixture —
    a draft roster produced without reading any workbook."""
    start = time.perf_counter()
    failures: list[str] = []
    metrics: dict[str, float] = {}
    events = 0
    try:
        from app.scheduler import (
            generate_demands,
            representative_snapshot,
            run_scheduler,
        )

        snapshot = representative_snapshot()
        generated = generate_demands(snapshot)
        result = run_scheduler(snapshot)
        metrics = result.version.summary
        events = len(generated.leave_events)

        counts = generated.counts_by_kind
        fixed_hc = counts.get("fixed_service", 0) + counts.get("hc_pattern", 0)
        if fixed_hc < 10:
            failures.append(f"expected >= 10 fixed/HC tasks, got {fixed_hc}")
        if counts.get("escort", 0) < 3:
            failures.append(f"expected >= 3 escort tasks, got {counts.get('escort', 0)}")
        if len(generated.duty_requirements) < 2:
            failures.append("expected >= 2 centre duty requirements")
        if result.violations:
            failures.append(f"{len(result.violations)} hard constraint violation(s)")
        if not any(a.kind == AuditKind.EXCLUSIVE_CANCELLATION
                   for a in result.version.audit_items):
            failures.append("exclusive worker leave did not propose a cancellation")
        if not any(a.kind == AuditKind.DATA_GAP for a in result.version.audit_items):
            failures.append("unknown-gender escort did not surface a data gap")
    except Exception as exc:  # pragma: no cover - benchmark should report details
        failures.append(f"scheduler snapshot run failed: {exc}")
    runtime = round((time.perf_counter() - start) * 1000, 1)
    return {
        "scenario": "S14",
        "name": "rule-based snapshot → draft roster (no workbook)",
        "seed": 0,
        "events": events,
        "coverage_rate": metrics.get("coverage_rate", 0.0),
        "unassigned_count": metrics.get("unassigned_count", 0),
        "manual_review_total": metrics.get("manual_review_total", 0),
        "manual_review_blocking": metrics.get("manual_review_blocking", 0),
        "hard_constraint_violations": metrics.get("hard_constraint_violations", 0),
        "change_distance": metrics.get("change_distance_from_original", 0),
        "runtime_ms": runtime,
        "check_failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, default=None,
                        help="write results to a JSON file")
    args = parser.parse_args()

    rows = [s.run() for s in SCENARIOS]
    rows.append(_run_scheduler_snapshot())
    rows.append(_run_import_roundtrip())

    cols = ["scenario", "events", "coverage_rate", "unassigned_count",
            "manual_review_blocking", "manual_review_total",
            "hard_constraint_violations", "change_distance", "runtime_ms"]
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    print("\nRosterCopiilot benchmark —", len(rows), "scenarios\n")
    print(" | ".join(c.ljust(widths[c]) for c in cols))
    print("-+-".join("-" * widths[c] for c in cols))
    for r in rows:
        print(" | ".join(str(r[c]).ljust(widths[c]) for c in cols))
        if r["check_failures"]:
            for f in r["check_failures"]:
                print(f"    !! {r['scenario']} CHECK FAILED: {f}")
    print()

    total_violations = sum(r["hard_constraint_violations"] for r in rows)
    check_failures = [f for r in rows for f in r["check_failures"]]

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rows, indent=2, ensure_ascii=False))
        print(f"results written to {args.json}")

    if total_violations > 0:
        print(f"FAIL: {total_violations} hard constraint violation(s)")
        return 1
    if check_failures:
        print(f"FAIL: {len(check_failures)} scenario check(s) failed")
        return 2
    print(f"PASS: 0 hard constraint violations across {len(rows)} scenarios")
    return 0


if __name__ == "__main__":
    sys.exit(main())
