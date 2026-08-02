#!/usr/bin/env python3
"""Run the Phase 1 import-review-export demo flow.

The script uses the public FastAPI endpoints with a temporary SQLite database:

1. POST /api/import/workbooks?use_default_docs=true
2. GET /api/import/ambiguities for the new batch
3. POST one demo ambiguity resolution
4. POST /api/export/ngo-format

It does not replace the mock scheduler dataset and does not add CP-SAT.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402
from app.services import state as state_module  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Demo Phase 1 workbook import, ambiguity review, and export."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite DB path. Defaults to a temporary file.",
    )
    parser.add_argument(
        "--export-dir",
        type=Path,
        default=Path(tempfile.gettempdir()) / "rostercopiilot_demo_exports",
        help="Directory for the NGO-format export artifact.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    args.export_dir.mkdir(parents=True, exist_ok=True)
    db_path = args.db or Path(tempfile.gettempdir()) / "rostercopiilot_demo.db"

    os.environ["ROSTER_EXPORT_DIR"] = str(args.export_dir)
    state_module.reset_state(db_path=db_path)
    client = TestClient(app)

    imported = client.post("/api/import/workbooks?use_default_docs=true")
    imported.raise_for_status()
    batch = imported.json()
    print(f"import batch: {batch['id']}")
    print(f"source files: {', '.join(batch['source_names'])}")
    print(
        "summary: "
        f"parsed={batch['summary']['parsed_count']} "
        f"flagged={batch['summary']['flagged_count']} "
        f"dropped={batch['summary']['silently_dropped_cells']}"
    )

    ambiguities = client.get(
        f"/api/import/ambiguities?batch_id={batch['id']}"
    ).json()
    blocking = [item for item in ambiguities if item["severity"] == "blocking"]
    print(f"pending ambiguities: {len(ambiguities)} "
          f"(blocking={len(blocking)})")

    target = blocking[0] if blocking else (ambiguities[0] if ambiguities else None)
    if target:
        resolved = client.post(
            f"/api/import/ambiguities/{target['id']}/resolution",
            json={
                "status": "resolved",
                "resolution": {"demo_acknowledged": True},
                "note": "Demo acknowledgement only; semantics still need review.",
            },
        )
        resolved.raise_for_status()
        print(f"resolved one ambiguity: {target['id']} [{target['code']}]")

    before = set(args.export_dir.glob("ngo_division_*.xlsx"))
    exported = client.post("/api/export/ngo-format", json={})
    exported.raise_for_status()
    after = set(args.export_dir.glob("ngo_division_*.xlsx"))
    new_files = sorted(after - before)
    if new_files:
        print(f"exported workbook: {new_files[-1]}")
    else:
        print(f"export endpoint returned {len(exported.content)} bytes")
    print(f"db path: {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
