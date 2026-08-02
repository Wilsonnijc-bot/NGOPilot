# Phase 1B — Provenance, Conservation, Review, And Publication

**Status:** engineering contract implemented; NGO-dependent acceptance pending
**Audience:** implementing agents and reviewers
**Depends on:** v0.5.0 master data, deterministic scheduler, independent
validator, and preflighted review-draft export.

This specification closes one bounded safety gap. It does not replace the
canonical domain model, the scheduler, or the NGO workbook format. It adds a
traceable spine from a weekly demand to its one terminal disposition, review
history, and exact exported cell.

## 1. Product boundary

The operational flow remains:

```text
built-in division template
  + uploaded HC workbook
  + uploaded escort workbook
  + target week and temporary changes
  -> deterministic scheduler
  -> independent validator
  -> human review
  -> review-draft workbook
  -> separate ready-only final publication action
```

The import APIs remain support tooling. No LLM may affect demand generation,
eligibility, ranking, repair, validation, review state, or publication. CP-SAT
remains out of scope. Unknown NGO facts remain unknown.

## 2. Scope and non-goals

Phase 1B adds:

1. stable demand, source-evidence, data-gap, entry, audit, decision, and
   override identities;
2. demand conservation and one explicit terminal disposition per weekly
   demand;
3. entry-level uncertainty and audit linkage;
4. durable weekly runs, immutable schedule-version lineage, decisions, and
   manual overrides;
5. approve/edit/hard-bypass plus revalidation in the existing four-step UI;
6. a separate final-publication action that accepts only `ready`;
7. one reconciliation report shared by API, UI, RC sheets, metadata, and a
   parallel-run comparison harness.

Phase 1B does not add a normalized per-entity database, a new weekly upload,
automatic communication to staff, real-name storage, a travel matrix, or an
optimizer.

## 3. Identity and serialization contract

### 3.1 Canonical hashing

Stable derived IDs use this algorithm:

1. serialize the identity fields as UTF-8 JSON with sorted keys and compact
   separators;
2. normalize strings to Unicode NFC, trim surrounding whitespace, and encode
   dates/times in ISO 8601;
3. omit presentation-only values such as display names, explanations, file
   names, list position, and runtime timestamps;
4. hash `namespace + ":" + canonical_json` with SHA-256;
5. use the first 20 lowercase hexadecimal characters with the prefix below;
6. fail on a same-prefix collision with different canonical input. Never
   silently add a random suffix.

Canonical helpers belong in one dependency-free domain module. The scheduler,
API, store, and exporter must not implement their own variants.

| Object | Prefix | Identity fields |
| --- | --- | --- |
| source evidence | `src_` | source kind, owning source ID/version, locator, field, content fingerprint |
| weekly demand | `dem_` | source evidence ID, dated occurrence, service, elder/centre/route, period/session, duplicate ordinal |
| data gap | `gap_` | kind, entity, affected field, source evidence IDs, normalized policy reason |
| schedule entry | `ent_` | version ID, demand ID, entry role (`current`, `alternative`, `manual`), revision |
| audit dedupe key | `adk_` | kind, reason code, demand IDs, entry IDs, data-gap IDs, trigger event ID |
| audit item | `aud_` | origin version ID plus audit dedupe key |
| decision | `dec_` | run ID, audit ID, resulting version ID |
| manual override | `ovr_` | decision ID, scope, action, canonical pin, effective dates |

`run_id` and `ScheduleVersion.id` may remain generated unique IDs because they
identify new immutable facts. Re-running identical inputs must reproduce the
same `demand_id` values, but intentionally creates a new run/version lineage.
Revalidating an unchanged stored version must not change entry or audit IDs.

If two genuinely distinct input rows normalize to the same demand identity,
assign `duplicate_ordinal` by sorting their structured source references, not
by the order in which parsers or dictionaries happen to return them.

### 3.2 Additive domain fields

Keep current compatibility fields while adding these authoritative links:

```text
SourceEvidence
  id, kind, source_id, source_version?, locator?, field?,
  content_fingerprint?, confidence(high|medium|low|seed)

DataGap
  id, kind, entity_id?, field?, message, blocking, policy,
  source_ref_ids[]

TaskDemand
  id                         # existing compatibility/source-record ID
  demand_id                  # stable dated weekly-demand ID
  source_refs[]              # existing readable strings, retained
  source_evidence[]          # structured SourceEvidence
  data_gap_ids[]

ScheduleEntry
  demand_id
  source_refs[]
  source_evidence[]
  data_gap_ids[]
  audit_ids[]                # ID links only; no recursive AuditItem objects

AuditItem
  version_id, dedupe_key
  demand_ids[], entry_ids[], data_gap_ids[], evidence_refs[]
  decision_id?, override_ids[], depends_on[]

DemandDisposition
  demand_id
  disposition
  entry_id?
  audit_ids[]
  source_ref_ids[]
  reason_code?
```

All new API fields are additive. Existing `id`, `origin_fixed_service_id`,
`origin_escort_request_id`, embedded audit entries, and readable
`source_refs` remain until a separately versioned API migration removes them.
Pydantic JSON mode is the storage and API serialization authority; sets and
non-JSON date objects are forbidden in persisted payloads.

## 4. Weekly demand boundary and conservation

A weekly demand exists only after a source definition expands to a concrete
dated occurrence inside the target Monday-Saturday window. A normal
week-pattern exclusion or an upload row outside the target week is an
`excluded_source_record`, not a weekly demand and not part of the conservation
denominator. It remains visible in generation diagnostics.

Every weekly demand must have exactly one of these terminal dispositions:

| Disposition | Required state |
| --- | --- |
| `scheduled` | exactly one active `scheduled` entry; no unresolved uncertainty used by the placement |
| `needs_review` | exactly one active `needs_review` entry and at least one pending linked audit |
| `unassigned` | exactly one unassigned entry and exactly one terminal blocking audit: normally `unassigned_task`, or `duty_under_coverage` for a duty demand |
| `confirmed_cancelled` | cancellation evidence/decision plus one cancelled entry and linked audit |
| `suppressed_with_audit` | no active placement; explicit suppression reason and linked audit |

Alternatives embedded in an audit are proposals, not dispositions. Superseded
entries remain in version history but only the current entry participates in
the disposition. A demand with zero or multiple terminal dispositions is a
`demand_conservation_error`, blocks publication, and prevents final export.

The required reconciliation equation is:

```text
weekly_demand_total
  = scheduled
  + needs_review
  + unassigned
  + confirmed_cancelled
  + suppressed_with_audit
```

The exporter may derive an export-placement failure, but it must not silently
change the scheduler disposition. It adds one blocking export audit and one
RC_未分配 row tied to the same demand and entry.

## 5. Provenance propagation

Provenance is copied, not reconstructed downstream:

```text
master-data fact / upload row / temporary change / rule-config assumption
  -> SourceEvidence
  -> TaskDemand
  -> engine Task
  -> ScheduleEntry
  -> AuditItem and DemandDisposition
  -> ExportPlacement
  -> exact assignment/detail cell
```

The adapter must never discard `demand_id`, source evidence, data-gap IDs, or
assumptions. Export code must not use free-form `notes` as the primary source
reference. Notes may be shown as context only.

Source locators use workbook role plus sheet/cell or canonical registry IDs;
uploaded file names are display metadata, not identity. Source evidence must
not contain real elder names or raw sensitive payloads. A content fingerprint
may prove equality without storing the content.

## 6. Uncertainty propagation

Data-gap policy has three consequences:

1. `ineligible`: the uncertain pair is never placed; if no alternative exists,
   the demand is `unassigned` and the gap plus consequence audits are linked;
2. `allowed_with_review`: the entry must be `needs_review`, carry every
   relevant `data_gap_id` and `audit_id`, and appear visually as a review cell;
3. `informational`: it affects ranking/reporting only and is linked to a cell
   only when that cell actually depended on the fact.

Low-confidence evidence, seed skills/routes, unknown gender, and any other
fact actually used to justify a placement may never produce an ordinary
`scheduled` cell. Seed skill warnings may deduplicate per worker/fact, but all
affected entries must link back to the shared audit.

`gender_ok_unverified` is allowed only on a `needs_review` entry with a linked
gender gap and audit. The validator must reject the same flag on a normal
scheduled entry.

## 7. Audit deduplication and linkage

Audit items are unique by `(origin_version_id, dedupe_key)`. The dedupe key is
calculated from structured reason and affected IDs; human-readable messages do
not determine identity. Revalidation must upsert the same logical item, not
append a duplicate.

Required cases:

- one unassigned demand -> one terminal blocking audit and one RC_未分配 row;
  use `unassigned_task` normally and the domain-specific
  `duty_under_coverage` kind for a duty demand; do not duplicate equivalent
  blockers merely to force one audit kind;
- one export failure -> one blocking export audit and one RC_未分配 row;
- one shared seed/data gap -> one audit may reference many entries, and every
  affected entry references that audit ID;
- one `needs_review` entry -> at least one audit; exporter derivation is a
  fail-safe, not the normal producer;
- audit dependencies and displacement chains list IDs and are decided
  atomically.

The exporter must fail closed if a `needs_review` entry has no audit ID, a
scheduled entry carries unresolved uncertainty, or an audit references a
missing demand/entry.

## 8. Review decisions and overrides

Every decision records `decision_id`, run ID, source version ID, resulting
version ID, audit ID, action, actor, timestamp, note, edited entry payload when
applicable, validator result, and content hash. Reject requires a note. Edit
requires a note and creates a `ManualOverride` linked to the decision and
audit.

Each review action creates a new immutable `ScheduleVersion(kind=manual_edit)`
whose `parent_version_id` is the prior current version. It must not mutate the
stored parent. A repeated request with the same idempotency key returns the
existing decision/version.

An override never erases evidence or validator output. A manual edit that
still violates a hard rule may be persisted as a blocked review draft with an
override note, but it cannot reach `publication_state=ready`. Phase 1B does not
invent a policy that waives P0 rules.

## 9. Durable weekly-run boundary

The process-memory `_RUNS` dictionary is replaced by a store-backed weekly-run
repository. JSON-backed SQLite rows are sufficient; no broad relational
rewrite is required. Persist at minimum:

- run ID, week, creation time, current version ID, master-data version;
- normalized scheduler snapshot and lowered dataset needed for revalidation;
- parse/source summaries and safe upload display names;
- every immutable schedule version;
- every decision and manual override;
- latest export/reconciliation report and version content hash.

The built-in division template remains the layout authority and may be parsed
again after restart. Uploaded workbook bytes are not required for later export
once the normalized evidence/snapshot is persisted. Existing demo response and
review-draft URL shapes remain compatible.

## 10. Export and exact-cell contract

`prepare_generated_division_roster_export(...)` remains the single safety
boundary and runs before workbook mutation. Every `ExportPlacement` exposes:

```text
demand_id, entry_id, disposition, source evidence IDs, data-gap IDs,
audit IDs, assignment cell, optional detail cell, and version ID
```

Every review-cell comment must begin exactly with `RC:待審` and include, in
this order, reason, audit ID(s), demand ID, entry ID, and source evidence. A
scheduled cell affected by unknown or seed data is invalid; it must first be
converted to `needs_review`.

API, UI, `RC_審核`, `RC_未分配`, `RC_變更摘要`, and `RC_meta` consume the same
serialized reconciliation report. They may format it differently but may not
recompute counts independently.

## 11. Publication state

`review_export_allowed=true` means only that a labelled review draft can be
written without corrupting the grid.

| State | Contract |
| --- | --- |
| `blocked` | any validator/export failure, conservation error, unassigned demand, pending blocking audit, or invalid provenance link |
| `draft` | no blockers, but at least one needs-review entry or pending non-blocking audit remains |
| `ready` | zero validator/export failures, zero conservation/link errors, zero unassigned demands, zero needs-review entries, and zero pending audits |

Publication state is recomputed after every decision/edit from the stored
current version. A separate final-publication action revalidates the exact
version/content hash, rejects every state except `ready`, freezes the published
version, and emits the staff-facing filename
`照顧員工作分工表_正式版.xlsx`. The existing review-draft download and filename
remain unchanged.

## 12. Reconciliation report

One report contains:

- weekly demand total and the five disposition counts;
- excluded source-record count by reason;
- active entry, review, unassigned, cancellation, and suppression IDs;
- pending/decided audit counts by blocking/severity/kind;
- placement and changed-cell counts;
- source-evidence/data-gap linkage errors;
- hard violations, export failures, publication state, version ID, and content
  hash.

Counts must reconcile before a review draft is offered and again before final
publication. Runtime benchmark timing is never written to
`data/benchmark_results.json`; use `/tmp`.

## 13. NGO-dependent gates

Engineering may provide onboarding validation, admin support, comparison
ledgers, and a two-week harness. It must not fill unknown gender, skills,
routes, availability, elder requirements, Saturday anchor, or duty semantics.

`ready for NGO parallel run` means the code and harness pass. It does not mean
`staff ready`. Staff readiness additionally requires NGO-confirmed master data,
two NGO-selected and roster-owner-signed parallel weeks, zero uncategorized
diffs, and every publication gate above.
