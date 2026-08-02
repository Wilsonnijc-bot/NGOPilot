#!/usr/bin/env python3
"""Run the escort importer against the real workbook and print a summary."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.importer.escort import parse_workbook  # noqa: E402
from app.importer.serialization import to_jsonable  # noqa: E402

DEFAULT_PATH = (Path(__file__).resolve().parents[2]
                / "docs" / "護送個案總表(2026)(HKU).xlsx")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    result = parse_workbook(args.path)
    requests = [r.record for r in result.records
                if r.record and r.record.get("status") == "requested"]
    histogram = Counter((r["service_date"], r["period"]) for r in requests)
    prefs = [r for r in requests if r.get("preferred_worker_alias")]
    print(f"\n=== Escort import: {args.path}")
    print(f"requests: {len(requests)} | ambiguities: {len(result.ambiguities)}")
    print(f"half-day histogram values: {sorted(set(histogram.values()))}")
    print(f"preference hints: {len(prefs)}")
    for row in prefs[:8]:
        print(f"  row {row['row']}: {row['elder_alias']} -> "
              f"{row['preferred_worker_alias']} ({row['preference_strength']})")
    for ambiguity in result.ambiguities[:8]:
        loc = ambiguity.source.cell.label if ambiguity.source and ambiguity.source.cell else "?"
        print(f"  [{ambiguity.code}] {loc}: {ambiguity.message}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(to_jsonable(result),
                                        ensure_ascii=False, indent=2))
        print(f"full result written to {args.json}")
    return 0 if result.summary.silently_dropped_cells == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
