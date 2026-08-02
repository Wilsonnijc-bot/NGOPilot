#!/usr/bin/env python3
"""Run the division importer against the real workbook and print a summary.

Usage:
    .venv/bin/python backend/scripts/inspect_division_import.py [path] [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.importer import parse_division_workbook  # noqa: E402

DEFAULT_PATH = (Path(__file__).resolve().parents[2]
                / "docs" / "照顧員工作分工表2026(HKU).xlsx")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    result = parse_division_workbook(args.path)
    s = result.summary

    print(f"\n=== Division import: {result.workbook_path}")
    print(f"sheet: {result.sheet_name} | declared max_row {result.declared_max_row}"
          f" -> effective {result.used_range['max_row']}"
          f" (cols -> {result.used_range['max_column']})")
    print(f"workers: {s['worker_count']}  | gaps: {s['gap_columns']}"
          f" | counters: {s['counter_columns']}")
    print(f"weekday blocks: {s['weekday_blocks']} | hours row: {s['hours_row']}"
          f" | saturday row: {s['saturday_row']}")
    print(f"assignments: {s['assignment_count']} "
          f"(stacked {s['stacked_assignment_count']}, "
          f"overflow {s['overflow_assignment_count']})")
    print(f"fixed-service candidates: {s['fixed_service_candidate_count']}")
    print(f"counter rows: {s['counter_rows']} | mismatches: "
          f"{s['counter_mismatch_count']}")
    print(f"ambiguities: {s['ambiguity_count']}")
    print(f"cells: nonempty {s['nonempty_cells']} = classified "
          f"{s['classified_cells']} + dropped {s['silently_dropped_cells']}")

    kinds = Counter(a.kind for a in result.assignments)
    print("\nassignment kinds:", dict(kinds.most_common()))
    amb = Counter(a.code for a in result.ambiguities)
    print("ambiguity codes:", dict(amb.most_common()))

    print("\n--- sample workers (first 5 + late columns):")
    late = [w for w in result.workers if w.column_letter in
            ("AO", "AP", "AR", "AS", "AT", "AU", "AV", "AW", "AX")]
    for w in list(result.workers)[:5] + late:
        print(f"  {w.column_letter:>3} {w.display_name:<4} tags={list(w.tags)} "
              f"status={w.status_inferred} hours={w.work_hours_raw} "
              f"sat={w.saturday_team}")

    print("\n--- sample fixed-service candidates:")
    for c in result.fixed_service_candidates[:6]:
        print(f"  {c.source_ref}: {c.service_code_raw}:{c.elder_alias}"
              f"({c.unit}) wd{c.weekday} {c.period} s{c.session_index} "
              f"pattern={c.week_pattern_raw} time={c.start_time}-{c.end_time} "
              f"district={c.district} mgr?={c.case_manager_candidate}")
    stacked = [c for c in result.fixed_service_candidates if c.stacked]
    print(f"\n--- stacked (shared-slot) candidates: {len(stacked)}")
    for c in stacked[:4]:
        print(f"  {c.source_ref}: {c.service_code_raw}:{c.elder_alias} "
              f"pattern={c.week_pattern_raw}")

    print("\n--- sample ambiguities:")
    for a in result.ambiguities[:8]:
        loc = a.source.cell.label if a.source and a.source.cell else "?"
        print(f"  [{a.code}] {loc}: {a.message[:90]}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result.to_json_dict(),
                                        ensure_ascii=False, indent=2))
        print(f"\nfull result written to {args.json}")

    return 0 if s["silently_dropped_cells"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
