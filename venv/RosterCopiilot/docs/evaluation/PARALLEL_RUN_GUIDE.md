# Two-Week Parallel-Run Guide

**Status:** engineering harness implemented; NGO evidence and signed operational
weeks remain external gates.

This harness compares two stored weekly-run API payloads with the roster
owner's manual workbooks. It does not call the scheduler, derive demand from
Excel, or fill unknown gender, skill, route, availability, elder, or rule facts.
The manual workbook remains the operational source of truth during a parallel
run.

## Run it

```bash
.venv/bin/python backend/scripts/run_parallel_review.py \
  --manifest /path/to/parallel-run/manifest.json \
  --json /tmp/rostercopiilot_parallel_run.json
```

Add `--pretty` for indented JSON. The default output is canonical JSON and is
byte-identical for identical inputs. The command does not write to
`data/benchmark_results.json` and never includes runtime, current timestamps,
or input/output paths in its report.

Exit code `0` means both engineering and comparison gates passed. A malformed,
uncategorized, or blocking comparison exits non-zero. Missing NGO evidence
leaves `ngo_gate=pending` but does not turn an otherwise valid engineering run
into a failure.

## Manifest

Paths are resolved relative to the manifest. Exactly two unique Monday week
starts are required, and every referenced input must exist.

```json
{
  "schema_version": "1.0",
  "scope": "real_parallel_run",
  "ngo_master_data": {
    "confirmed": false,
    "evidence_refs": []
  },
  "weeks": [
    {
      "week_start": "2026-01-05",
      "generated_run": "week-1-run.json",
      "manual_workbook": "week-1-manual.xlsx",
      "comparison_ledger": "week-1-ledger.json"
    },
    {
      "week_start": "2026-01-12",
      "generated_run": "week-2-run.json",
      "manual_workbook": "week-2-manual.xlsx",
      "comparison_ledger": "week-2-ledger.csv"
    }
  ]
}
```

`generated_run` is the stored response shape returned by
`GET /api/demo/weekly-roster/{run_id}`. The harness verifies its week, version,
content hash, reconciliation copies, dispositions, entries, placement links,
and exact cell references. It does not rerun scheduling.

For a real NGO gate, set `ngo_master_data.confirmed=true` with at least one
evidence reference and add this object to both week cases:

```json
{
  "roster_owner_signoff": {
    "reviewer": "roster owner identifier",
    "signed_at": "2026-01-16T17:00:00+08:00",
    "evidence_ref": "signed-ledger-record"
  }
}
```

Do not add synthetic sign-offs to an operational manifest. Use
`scope=fixture_smoke` for fixtures; that scope always returns
`ngo_gate=not_evaluated` and `claims_ngo_acceptance=false`.

## JSON ledger

The ledger has three sections:

- `disposition_comparisons` covers every generated demand that has no export
  placement. Its manual disposition is explicit; the harness never infers it
  from a blank workbook cell.
- `manual_only` records a stable operator-defined key and an exact non-empty
  workbook cell for content that cannot map to a generated demand. It creates a
  diff, never a new demand.
- `diffs` classifies every actual placement-cell, disposition, and manual-only
  difference. Missing, duplicate, stale, or extra rows fail closed.

```json
{
  "schema_version": "1.0",
  "week_start": "2026-01-05",
  "disposition_comparisons": [
    {
      "demand_id": "dem_example",
      "manual_disposition": "unassigned",
      "reference": "manual-ledger:row-17"
    }
  ],
  "manual_only": [
    {
      "manual_key": "manual-extra-001",
      "cell": "恆常服務!Z17"
    }
  ],
  "diffs": [
    {
      "diff_id": "dif_generated_by_first_validation_run",
      "week_start": "2026-01-05",
      "demand_id": "dem_example",
      "manual_key": null,
      "entry_id": "ent_example",
      "cell_or_ref": "恆常服務!B12",
      "generated_exists": true,
      "manual_exists": true,
      "generated_value": "HC:case-alias",
      "manual_value": "HC:manual-case-alias",
      "category": "reviewer_approved",
      "note": "Roster owner kept the manual assignment.",
      "reviewer": "roster owner identifier",
      "reviewed_at": "2026-01-16T17:00:00+08:00"
    }
  ]
}
```

Start with `diffs: []` after completing disposition/manual-only observations.
The expected non-zero result lists `uncategorized_diffs` with stable IDs and
exact generated/manual facts. Copy those facts into the ledger and add one of:

- `expected`, with a non-empty `note`;
- `reviewer_approved`, with `note`, `reviewer`, and `reviewed_at`;
- `blocking`, with `note` and `blocking_reason`.

Run again after classification. Never delete a difference merely to obtain a
green report.

## CSV ledger

CSV uses the same contract. Its exact header is:

```text
schema_version,week_start,row_type,demand_id,manual_disposition,reference,manual_key,cell,diff_id,entry_id,cell_or_ref,generated_exists,manual_exists,generated_value_json,manual_value_json,category,note,reviewer,reviewed_at,blocking_reason
```

Include exactly one `meta` row with `schema_version` and `week_start`. Other
`row_type` values are `disposition`, `manual_only`, and `diff`. For `diff` rows,
existence values are exactly `true`/`false`; generated and manual values are
JSON encoded (`null`, a quoted string, number, or boolean).

## Reading the gates

- `engineering_gate=passed`: both stored runs were structurally consistent,
  all cells/dispositions were reconstructed, classifications were complete,
  and no reconciliation, hard-rule, or export failure was present.
- `comparison_gate=passed`: engineering passed and there are zero differences
  categorized as `blocking`.
- `ngo_gate=pending`: real evidence or one of the two roster-owner sign-offs is
  missing, or another gate is blocked.
- `ngo_gate=accepted`: real mode only, with confirmed master-data evidence, two
  signed weeks, engineering pass, zero uncategorized differences, and zero
  blocking differences.

Even `ngo_gate=accepted` is evidence about this two-week comparison only. It is
not a claim that the system is staff-ready, and it never authorizes automatic
publication or distribution.
