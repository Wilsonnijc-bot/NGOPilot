#!/usr/bin/env python3
"""Run the HC timetable importer against the real workbook and print a summary."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.importer.hc_timetable import parse_workbook  # noqa: E402
from app.importer.serialization import to_jsonable  # noqa: E402

DEFAULT_PATH = (Path(__file__).resolve().parents[2]
                / "docs" / "2026_HC 時間表(HKU).xlsx")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    result = parse_workbook(args.path)
    by_week = Counter(r.record["week"] for r in result.records
                      if r.record and isinstance(r.record.get("week"), int))
    mangled = [a for a in result.ambiguities
               if a.code == "MANGLED_WEEK_PATTERN_DATE"]
    print(f"\n=== HC import: {args.path}")
    print(f"records: {result.summary.parsed_count} | "
          f"ambiguities: {len(result.ambiguities)}")
    print("records by week:", dict(sorted(by_week.items())))
    print(f"recovered Excel-date week-pattern cells: {len(mangled)}")
    for ambiguity in mangled:
        loc = ambiguity.source.cell.label if ambiguity.source and ambiguity.source.cell else "?"
        print(f"  {loc}: {ambiguity.raw_value} -> 1,5")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(to_jsonable(result),
                                        ensure_ascii=False, indent=2))
        print(f"full result written to {args.json}")
    return 0 if result.summary.silently_dropped_cells == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
