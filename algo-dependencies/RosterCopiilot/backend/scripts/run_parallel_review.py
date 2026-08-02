#!/usr/bin/env python3
"""Run the deterministic two-week manual-roster comparison harness."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation import (  # noqa: E402
    ParallelRunValidationError,
    canonical_report_json,
    evaluate_parallel_run,
    failure_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare two generated weekly-run payloads with roster-owner "
            "workbooks and explicit classification ledgers."
        )
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--json", required=True, dest="output", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = evaluate_parallel_run(args.manifest)
    except ParallelRunValidationError as exc:
        report = failure_report(exc)
        exit_code = 2
    else:
        exit_code = 0 if report["status"] == "passed" else 2

    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            canonical_report_json(report, pretty=args.pretty),
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"parallel-run report write failed: {exc}", file=sys.stderr)
        return 2

    engineering = report["engineering_gate"]["state"]
    comparison = report["comparison_gate"]["state"]
    ngo = report["ngo_gate"]
    summary = (
        f"parallel-run: engineering={engineering} "
        f"comparison={comparison} ngo={ngo}"
    )
    print(summary, file=sys.stdout if exit_code == 0 else sys.stderr)
    if "error" in report:
        print(
            f"{report['error']['code']}: {report['error']['message']}",
            file=sys.stderr,
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
