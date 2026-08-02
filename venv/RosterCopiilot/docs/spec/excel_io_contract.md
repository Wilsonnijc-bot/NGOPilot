# Excel Output And Fixture Contract

**Status:** direction-corrected 2026-07-04.

The NGO keeps receiving a familiar Excel workbook. The product does not require
the NGO to upload several source workbooks as the normal weekly workflow.

## 1. Correct Boundary

```text
scheduler snapshot → ScheduleVersion → division workbook export
```

Support-only path:

```text
sample workbooks → parser → fixtures / evidence / regression checks
```

## 2. Staff-Facing Output Workbook

The final workbook must follow the `照顧員工作分工表` structure:

- worker columns in the original order;
- merged weekday/period blocks;
- two session slots per half-day;
- assignment-cell grammar like `E+RO:Y容(EH)`;
- semantic fill colours preserved;
- business comments/notes retained when present.

The division workbook is the main output artifact because staff already know how
to read it.

## 3. Changed And Review-Required Cells

- Changed assignment: border + comment explaining reason and audit id.
- Needs review: comment prefix `RC:待審` and corresponding review sheet row.
- Cancelled assignment: strikethrough or explicit cancellation marker while
  preserving business colour.
- Unassigned task: visible `待分配` marker and row in `RC_未分配`.

Do not overwrite business fill colours to show review state.

## 4. Optional `RC_*` Sheets

- `RC_變更摘要`: changed cells and reasons.
- `RC_審核`: open audit items.
- `RC_未分配`: unresolved tasks.
- `RC_meta`: version id, config hash, export metadata.

These sheets are additive. They do not replace the staff-facing roster grid.

## 5. How Existing Parsers Should Be Used

The parser modules may read the sample workbooks to:

- verify the strong-agent reverse-engineering results;
- create regression fixtures;
- preserve source-cell evidence for rules;
- detect workbook pathologies such as Excel-date-mangled week patterns.

They should not drive product requirements toward a multi-workbook upload flow.

## 6. Fixture Invariants

For analysis tooling only:

- sample parser runs should have `silently_dropped_cells == 0`;
- ambiguous cells should produce explicit ambiguity records;
- full-name leaks and unconfirmed semantics should remain review-required;
- fixture imports must not silently become hard scheduling rules.
