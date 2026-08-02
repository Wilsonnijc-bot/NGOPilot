# Export And Review Audit

> **Archived:** this is the 2026-07-09 pre-v0.5.0 audit and remediation
> record. It no longer defines current behaviour. Current publication safety is
> specified by
> [`PROVENANCE_AND_PUBLICATION_SPEC.md`](../spec/PROVENANCE_AND_PUBLICATION_SPEC.md)
> and tested through the active acceptance matrix.

**Review date:** 2026-07-09
**Scope:** scheduler output, validator, audit generation, both Excel export
paths, weekly-demo API/UI, the Excel and human-review contracts, and related
tests.

> **Status: historical findings remediated in v0.5.0.** This document keeps
> the original pre-remediation audit for traceability. The implementation now
> has a preflight manifest, fail-closed review-draft export, derived audit and
> unassigned rows for placement failures, additive comment/border markers, and
> publication-state UI. The remaining work is entry-level uncertainty linkage
> and NGO parallel-run validation, not the P0 export failures recorded below.

## Decision

**Current decision:** a generated workbook may be downloaded only as a clearly
labelled **審核草稿** after the export preflight succeeds. It is distributable
only when `publication_state=ready`. `review_export_allowed=true` means the
grid is safe to write for review; it does not mean staff may receive it.

## Direct answers

| Question | Current answer | Evidence |
| --- | --- | --- |
| Can generated assignments safely land in 恆常服務? | **Yes for a review draft only.** Validator and placement preflight run before any template mutation; hard-rule or placement failure returns 409. | `prepare_generated_division_roster_export`, `ExportPreflightError`. |
| Are unsafe assignments routed to RC_未分配? | **Yes.** Validator and placement failures derive one blocking audit and one structured unassigned row. | generated export plan and derived audit helpers. |
| Are all risky decisions visible in RC_審核? | **Yes for export failures and `needs_review` entries.** Entry-level linkage for every global data gap remains future work. | generated export plan and review markers. |
| Are business fill colours preserved? | **Yes, covered by generated-path regression tests.** | `test_generated_export_preserves_existing_comment_border_and_fill`. |
| Are comments and borders additive? | **Yes.** Business comments are retained and RC notes appended; an unused border edge is marked without replacing existing sides. | `_append_rc_comment`, `_add_marker_border`. |
| Does the UI/report explain unassigned work? | **Yes.** API/UI/RC sheet share the structured reason code, message, audit id, source, and next action. | `ExportUnassignedItem`, `renderUnassigned`. |
| Does the system pretend uncertain data is confirmed? | **Partly resolved.** Publication state and review markers are explicit, but global seed/data-gap items are not yet linked to every affected cell. | master-data bridge and exporter review plan. |

## Observed behaviour

### What is working

- Eligibility and the independent validator cover skills, gender, leave,
  capacity locks, exclusivity, and time conflicts.
- Normal scheduler paths generate structured reasons and audit items for
  unassigned fixed work, escort work, and duty shortfall.
- RC_審核 lists existing version audit items; RC_未分配 lists normal unassigned
  entries; business fills survive current value writes.
- The reviewed targeted suite passed with the project environment
  (.venv/bin/python, Python 3.12): **38 passed** across exporter, weekly-demo,
  scheduler, bridge, and hard-validator tests.

### Historical fixture-run observation

Using the built-in division workbook plus the supplied January escort workbook
for week 2026-01-05, the current end-to-end run produced:

- 831 entries; 772 active placements; 28 needs_review; 48 unassigned;
- zero independent validator violations;
- 187 audit items, including **59 pending blocking** items;
- 48 RC_未分配 rows and no mapper overflow in that specific run.

Zero validator violations is necessary but not sufficient for publication. In
v0.5.0 this same condition is labelled `不可發放`; it may be downloaded only as
a review draft, never as a staff-ready workbook.

### Reproduced boundary failures

1. A deliberately modified scheduled entry with an unknown-gender personal-care
   assignment produced a gender_unknown validator violation. The generated
   writer still wrote PC:... into 恆常服務, did not route it to RC_未分配, and did
   not create a review item. Normal scheduler output being clean therefore
   does not make the exporter safe.
2. The template comment at 恆常服務!F48, "6/3 開始改時間", was replaced by a
   RosterCopiilot comment rather than retained/appended. This conflicts with
   the Excel contract's requirement to retain business comments and notes.
3. A marker assigns MARK_BORDER as a whole border. Existing top/right/bottom/
   left styles can therefore be replaced rather than preserved plus marked.

## Historical findings and remediation

### P0 — Make generated-grid export fail closed — resolved

Add one preflight shared by the weekly-demo export and every future
NGO-grid assignment export. It must run before _clear_schedule_grid or any
template mutation.

The preflight must:

1. Re-run validate_entries with the exact leave and manual-capacity-lock set
   for the version. Any violation prevents a staff-facing grid write.
2. Build a complete placement manifest: worker column, weekday/period rows,
   session, assignment/detail target cells, source refs, and audit ids.
3. Reject collisions, unmapped workers, unmapped slots, unsupported cell
   grammar, and active entries that have no corresponding decision/audit state.
4. Permit scheduled entries only after the preflight. Permit needs_review
   entries only in a **draft**: their grid comment must begin RC:待審, include
   audit id(s), and publication must be blocked while required review is open.
5. Never clear the old grid after a failed preflight. The Phase 1 safe default
   is to refuse the generated staff-facing workbook and return a machine-
   readable placement report.

Document the current /api/export/ngo-format route as an append-only
review-sheet export. It is not an assignment export and is not equivalent to
the weekly-demo generated-grid path.

### P0 — Reconcile export failures into both review surfaces — resolved

An export-placement failure is operationally unsafe, not a row-writing warning.
Introduce a derived result such as export_placement_failure containing entry id,
source slot/ref, reason code, and proposed disposition. Before workbook build,
convert it into:

- one blocking unassigned_task-equivalent audit item in RC_審核;
- one structured RC_未分配 row with the same id, code/message, source ref, and
  audit id;
- one API/UI item from the same result, so download cannot introduce an unseen
  failure.

Required reconciliation invariants:

    every UNASSIGNED entry         -> one blocking audit + one RC_未分配 row
    every export-placement failure -> one blocking audit + one RC_未分配 row
    every NEEDS_REVIEW entry       -> audit + marked grid cell
    every marked grid cell         -> entry id + audit id(s)

Bring the domain audit record closer to audit_item_schema.json as well: retain
version id, evidence/source references, affected entry ids, and dependency/
decision data rather than relying only on embedded snapshots and free text.

### P0 — Separate draft generation from publishability — resolved

human_review_policy.md says blocking items prevent publication. Calculate one
publication_state from the version and placement manifest:

    blocked = validator violation OR unassigned work OR pending blocking audit
    draft   = no validator violation but review items remain
    ready   = no validator violation, no unassigned work, no pending blocking audit

The weekly-demo response and UI must show 草稿需審核 or 不可發放 for blocked and
draft; display the counts and links to responsible rows. Downloading a draft
may remain useful in a parallel run, but metadata/summary must label it draft.
A future publish/send/distribute action must reject every state other than
ready.

### P1 — Preserve business comments, borders, and layout semantics — resolved

The generated writer clears values **and comments**. Use the placement manifest
to preserve business comments verbatim. Where a cell changes, append one
RosterCopiilot paragraph after the original comment; never replace existing
author/text. Preserve comment provenance in review evidence when it affected an
assignment.

Do not replace cell.border wholesale. Copy every existing side and colour, then
add a marker only on an unused edge. If no edge can change without losing a
business style, preserve the border and use the required comment plus
RC_變更摘要; make that exception explicit and tested. Fills, merged ranges, row
heights, column widths, formulas, data validation, and non-RC sheets must stay
unchanged except for manifest-authorized value/comment/marker deltas.

### P1 — Make uncertainty entry-specific and visible at the cell — remaining

The bridge appends snapshot-level data_gap audits after scheduling. That avoids
silent loss, but does not tell the reviewer which grid cells depend on a gap.
Carry source confidence, source refs, and data-gap ids from TaskDemand into
ScheduleEntry, then link each relevant entry to its audit id(s).

- Low-confidence source rows, seed skills, unknown routes, and unknown gender
  must not appear as visually ordinary scheduled cells.
- The documented gender_ok_unverified exception must be needs_review with that
  flag and a linked audit, never a normal scheduled entry.
- A cancelled/suppressed task needs an explicit disposition/audit unless it is
  a confirmed normal week-pattern exclusion.
- A review cell comment must begin RC:待審, then state reason, audit id, and
  source evidence as required by excel_io_contract.md.

### P1 — Explain unassigned work from one structured source — resolved

The API serializes review_reasons, but the frontend and generated RC_未分配 use
only entry.explanation. Render the reason code and message, audit id, and next
action in both places. A user must be able to answer “why was this not
assigned?” without reverse-engineering a generic sentence or downloading a
second file.

## Edge-case test plan

Add these tests before enabling staff-facing generated-grid export.

| Case | Setup | Required assertion |
| --- | --- | --- |
| Export revalidation | Modify a valid version into skill/gender/leave/exclusivity/time-conflict violation. | Preflight rejects grid write; template grid remains unchanged; API reports blocked export. |
| Worker or slot unmapped | Use an active entry whose worker column or weekday/period/session cannot resolve. | One blocking audit and one structured RC_未分配 row; source grid is not cleared; failure visible before download. |
| Third task in two-session half-day | Three same-worker session entries, plus a full-period escort variant. | Collision is detected before mutation; no silent overwrite/reassignment. |
| Normal scheduler unassigned | Produce no eligible worker. | Exactly one unassigned_task audit, one RC_未分配 row, and code/message/audit id visible in API and UI. |
| Unknown gender/skill/route | Use unknown elder gender, unknown worker skill, seed skill, and missing meal route. | Configured policy holds; no ordinary scheduled cell represents unverified constraint; cell/audit linkage is exact. |
| needs_review export | Template fallback and repair suggestion. | Cell retains business fill, begins RC:待審 with audit id, uses an additive marker, and output is non-publishable. |
| Existing comment | Cover known 恆常服務!F48 and an existing RosterCopiilot comment. | Original text/author survives; new note appends once; repeated export does not duplicate it. |
| Existing border and fill | Cover coloured duty, yellow ESC, and multi-side border cell. | Fill is byte-equivalent; existing border sides/colours remain; only permitted marker delta changes. |
| No-change and changed round trips | Export with no manifest deltas, then a small manifest. | Non-RC sheets, merged cells, untouched values/formulas/dimensions/validations/comments/fills/borders reconcile exactly. |
| Export-time audit | Force mapper failure after scheduler success. | RC_審核 includes the derived failure; it is not only an RC_未分配 row. |
| Blocking presentation | Fixture run with unassigned and pending blocking audits. | UI says 草稿需審核/不可發放 rather than green-ready; counts match API, RC sheets, and metadata. |
| Demand conservation | Generate, suppress, cancel, repair, and fail placement together. | Every demand is exactly scheduled, needs_review, unassigned, confirmed-cancelled, or explicitly suppressed-with-audit. |

## Parallel-run demo acceptance criteria

The parallel run is a review exercise, not automatic publication. Run it for at
least two NGO-selected weeks with fixed work plus real weekly demand; include
one controlled leave/change scenario in each. Keep the manual workbook as the
operational source of truth throughout.

The coding agent may declare the demo ready only when every run satisfies all
of the following:

1. The preflight manifest is complete. There are zero validator violations,
   zero unexplained demand losses, and zero grid writes without a mapped
   source/target/audit state.
2. Each scheduled/review/unassigned/cancelled/suppressed demand reconciles to a
   manual comparison ledger. Every diff is expected, reviewer-approved, or
   blocking; none is uncategorized.
3. Every unassigned or export-placement failure appears once in RC_未分配 and
   once as a blocking item in RC_審核. Each needs_review cell begins RC:待審 and
   contains audit id(s). Counts reconcile across API, UI, RC sheets, and
   RC_meta.
4. Workbook-diff tests prove business fills, existing comments, border sides,
   formulas, merged cells, dimensions, and untouched values survive. Only
   manifest-authorized values and additive markers/comments may differ.
5. The UI labels a run with unassigned work or pending blocking audit as a
   blocked draft. No publish/send/distribute action is enabled unless
   publication_state is ready.
6. A roster owner reviews every discrepancy and blocking item, records a
   decision, and signs the comparison ledger. The generated workbook is not
   sent to staff or elders during the parallel run.
7. The edge-case suite is green under .venv/bin/python, and the weekly-demo
   end-to-end test asserts actual generated 恆常服務 content, not only sheet
   existence, merged-range counts, or a generic RosterCopiilot comment.

## Completion and next gate

1. Completed: preflight placement manifest and fail-closed review-draft export.
2. Completed: export failures reconcile into API, `RC_審核`, and `RC_未分配`.
3. Completed: additive comments/borders, structured reasons, and publication
   state in the UI.
4. Next: attach global data-gap evidence to every affected entry/cell, then run
   two NGO-selected parallel weeks with a roster owner. The generated workbook
   remains a review draft unless `publication_state=ready`.
