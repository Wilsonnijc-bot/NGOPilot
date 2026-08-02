# CareFlow Government Forms MCP Implementation Plan

Status: implemented; five-template discovery and both PDF strategies verified  
Architecture: [MCP-pre-build algorithm design plan.md](../../MCP-pre-build%20algorithm%20design%20plan.md)  
Public tool: `careflow_government_forms`  
Pinned native dependency: CareFlow 0.4.8

NGOPilotMCP owns every accepted and staged input, intermediate and review
result, delivered output artifact, durable job record, and recovery decision
for this workflow. CareFlow 0.4.8 is a pinned application dependency in the
one managed CareFlow environment shared by all three CareFlow tools. CareFlow
owns all welfare-form extraction, mapping, template, and PDF-filling domain
logic; this independent MCP tool owns only the orchestration and tool-specific
logic around those native calls.

## Implementation Record

The independent eight-module package implements `list_templates`, `start`,
`status`, `review`, and `export`. Automated tests cover the strict three-source
union, stateless discovery, native readiness/capability data, immutable image
staging, exact extractor/mapper/filler boundaries, MCP-owned status and review,
complete replacement fields, export gating, PDF verification/promotion,
failure-state preservation, and import isolation. Real managed-CareFlow worker
smokes discovered all five bundled template IDs and exported both a
coordinate-anchor OALA PDF and an AcroForm JoyYou PDF. The full authored package
suite passes with `125 passed`. The same OALA `start -> review -> export`
lifecycle also passes from the clean installed wheel in an arbitrary working
directory.

Exhaustive concurrency and crash-boundary injection remain release-hardening
work and are not described as completed evidence below.

## 1. Purpose and Scope

`careflow_government_forms` extracts or accepts an elder profile, maps it into a
ready government-form template, records a complete human-reviewed field set,
and produces an immutable MCP-owned snapshot of the native filled PDF.

This plan defines only this tool's implementation. The architecture document
defines the shared host, envelope, job store, staging, artifact registry,
worker protocol, managed runtimes, failure-state checkpointing, and cross-tool rules.
This tool must call CareFlow's pinned implementation rather than reproduce or
modify its domain algorithms.

## 2. Independent Code Boundary

The complete implementation lives under one tool directory:

```text
src/ngopilot_mcp/tools/careflow_government_forms/
  __init__.py
  manifest.py
  schemas.py
  controller.py
  validation.py
  native_adapter.py
  state.py
  artifacts.py

tests/tools/careflow_government_forms/
  test_schemas.py
  test_validation.py
  test_controller.py
  test_artifacts.py
  test_native_adapter_contract.py
  test_import_boundary.py
```

| Module | Tool-owned responsibility |
|---|---|
| `manifest.py` | Host-safe public name, description, worker target, and operation list. It must not import CareFlow. |
| `schemas.py` | Strict `list_templates`, `start`, `status`, `review`, and `export` request variants; results use shared `ToolExecution`. |
| `controller.py` | Host-side operation ordering, state transitions, shared-worker requests, and artifact promotion. |
| `validation.py` | Government-template, source-union, image-capability, and complete-review validation. |
| `native_adapter.py` | Worker-only allow-listed CareFlow calls and transport translation; no copied algorithms. |
| `state.py` | Government-form job payload, review snapshot, native metadata, and status projection in the shared store. |
| `artifacts.py` | Filled-PDF verification and promotion semantics using the shared artifact service. |
| Tool tests | This tool's contract, controller lifecycle, native-call boundary, artifacts, validation, and independence; shared runtime tests own generic replay/failure-state behavior. |

### 2.1 Import and Ownership Rules

This directory must not import
`careflow_paper_forms_to_excel`, `careflow_meeting_notes`, or
`roster_copilot`; no other tool may import it. Shared infrastructure imports
are limited to the documented host interface, envelope, job repository and
lock, file staging, artifact service, worker client/protocol, logging, and
common errors.

An import-boundary test must enforce this rule. Removing this tool directory
may remove only its registration and tests; the other tool packages remain
importable. This package creates no private database, migrations, artifact
registry, worker, venv, app-data/resource root, or runtime bootstrap.

## 3. Ownership and Native Domain Boundary

NGOPilotMCP stages inputs, persists source metadata and native intermediate
results, stores review, promotes outputs, returns absolute MCP-owned paths, and
recovers jobs. Shared services supply the mechanisms; this package supplies
their tool-specific meaning.

CareFlow 0.4.8 owns ElderProfile extraction/post-processing, mapping decisions,
templates, both fill strategies, anchor/widget behavior, fill statistics, PDF
rendering, and native naming. MCP records native results and may reject invalid
input or an unavailable capability, but it must not invent profile fields,
mappings, confidence values, coordinates, or PDF content.

## 4. Public MCP Tool Contract

Tool name: `careflow_government_forms`

The native welfare flow is stateless. NGOPilotMCP supplies the durable job,
review, idempotency, artifact, and recovery record without changing the native
extractor, mapper, template loader, or filler. All operations are strict
variants of the shared request envelope; unknown or cross-operation fields are
rejected before a native call.

### 4.1 Template Discovery

`operation="list_templates"` is read-only and needs no `job_id`. It calls the
original template loader and returns ready templates, field counts, fill
strategies, and supported source information. It creates no job or job files.

The five bundled ready IDs are:

| ID | Form | Strategy |
|---|---|---|
| `ccsv` | Community Care Service Voucher application | coordinate anchor |
| `cssa` | Comprehensive Social Security Assistance registration | coordinate anchor |
| `joyyou` | JoyYou / $2 transport concession application | AcroForm |
| `oala` | Old Age Living Allowance simplified form | coordinate anchor |
| `ssa_307` | Social Security Allowance Scheme application | coordinate anchor |

### 4.2 Start Input

Start requires `template_id`, `use_llm`, and exactly one profile source:

```json
{
  "operation": "start",
  "job_id": null,
  "input": {
    "template_id": "oala",
    "use_llm": false,
    "source_hint": "social worker note",
    "source": {
      "kind": "image",
      "image_path": "/absolute/elder-card.jpg"
    }
  }
}
```

Allowed source variants are exactly:

```json
{"kind": "text", "text": "non-empty source text"}
{"kind": "image", "image_path": "/absolute/source.jpg"}
{"kind": "elder_profile", "elder_profile": {}}
```

`.jpg`, `.jpeg`, and `.png` are guaranteed for image extraction. `.heic` and
`.heif` are enabled only when the shared CareFlow runtime capability probe
succeeds. Otherwise validation fails before the AI call with an explicit
supported-format list. An accepted image is copied into the job's immutable
`inputs/` directory; the worker never depends on the caller-owned file after
staging.

Start calls the matching original text/image extractor, or accepts the
structured profile, then calls `map_elder_to_template`. The result contains the
ElderProfile and every mapping with key, label, value, source (`direct`,
`default`, `llm`, or `missing`), confidence, reason when supplied by CareFlow,
and the native summary. The exact profile and preview are durable before the
job becomes `pending_review`; `status` never recomputes them.

### 4.3 Operations

| Operation | Required payload | Native/original effect | Result/next state |
|---|---|---|---|
| `list_templates` | none | list native templates and apply readiness checks | available ready templates |
| `start` | template, source union, `use_llm` | extract/accept profile and preview native mapping | `pending_review` |
| `status` | `job_id` | none; read MCP job | profile, preview, reviewed values, artifacts |
| `review` | complete `field_values`, optional `reviewer` | none; persist reviewed field set | `reviewed` |
| `export` | `job_id` | call native `fill_form` with reviewed values | absolute MCP-owned filled `.pdf` artifact |

### 4.4 Review, Export, and Theta Invariants

Review persists the complete effective `field_values`, not only changed
overrides. Completeness is checked against the keys in the persisted preview.
Export reads that stored set and ElderProfile; it must not rerun extraction or
mapping or substitute the unreviewed preview.

CareFlow retains its strategy, coordinate checks, widget behavior, fill
statistics, and native path naming:

```text
data/welfare_outputs/<elder_id>_<template_id>_<timestamp>.pdf
```

The resolved native path is metadata only. MCP structurally validates the PDF,
snapshots it into the job's `outputs/`, registers it, and returns the registered
absolute path as the delivered artifact.

Theta is not a first-class operation. An existing ready Theta template may be
listed only when its JSON definition and source PDF both exist and are
fillable. CareFlow currently publishes its PDF basename while leaving the file
under `theta_pdfs`, although the filler looks under `templates`; the readiness
probe must hide that broken entry. Fixing or adding Theta authoring requires a
separate approved change.

## 5. Runtime State

This tool uses the architecture-owned shared state:

```text
<state>/
  jobs.sqlite3
  jobs/
    careflow_government_forms/<job_id>/
      manifest.json
      inputs/
      intermediate/
      outputs/
      logs/
  app-data/
    careflow/
      careflow.db
      templates/
      form_templates/
      welfare_outputs/
  runtimes/
    careflow/.venv/
  resources/
    careflow/
```

`jobs.sqlite3` is the shared authority. Government-form job, operation,
intermediate, and artifact rows are namespaced by tool name and `job_id`;
per-process locks, request-hash replay, and failure-state checkpointing remain
shared. Cross-process leases and automatic crash reconciliation are not part of
the current implementation.
`manifest.json` is an atomic host projection, not a second database.

`inputs/` holds immutable accepted source snapshots. `intermediate/` or the
shared job record holds the exact native profile/mapping and review snapshots
needed to continue review without repeating domain computation. `outputs/`
holds only verified, immutable MCP-delivered PDFs. `logs/` is access-restricted
and size-bounded, but general redaction and automated retention remain open.

All three CareFlow tools share `<state>/app-data/careflow/`,
`<state>/runtimes/careflow/.venv/`, the CareFlow worker, and the CareFlow
resource payload. This tool creates no `<state>/tools/...` runtime and no
private copy of those facilities.

Durable tool data includes the template, `use_llm`, `source_hint`, staged-source
kind/path/hash, exact profile/preview, complete review, native fill metadata,
and registered output path/size/media type/SHA-256. Runtime payload/lock
fingerprints are maintained by bootstrap rather than copied into every job.

## 6. Native Application Integration

The host process never imports CareFlow's top-level `app` package.
`controller.py` sends a validated command through the shared worker client.
The shared CareFlow worker, running from
`<state>/runtimes/careflow/.venv/` with
`<state>/app-data/careflow/` configured before import, loads this tool's
worker-only `native_adapter.py` and calls CareFlow directly.

| MCP need | CareFlow-owned entry point |
|---|---|
| Discover templates | `app.services.welfare_form.list_form_templates()` / original template loader |
| Load definition | `app.services.welfare_form_templates.load_template(template_id)` |
| Extract text | `app.services.welfare_form_extractor.extract_elder_profile_from_text(text, source_hint=...)` |
| Extract image | `app.services.welfare_form_extractor.extract_elder_profile_from_image(image_bytes, ext=..., source_hint=...)` |
| Map preview | `app.services.welfare_form_mapping.map_elder_to_template(template, elder, use_llm=...)` |
| Fill reviewed PDF | `app.services.welfare_form_filler.fill_form(template_id, elder_profile=profile, field_values=reviewed_values)` |

The adapter preserves CareFlow's runtime `today` injection used by mapped form
fields. It returns native profile, mapping, and fill-statistic values unchanged
apart from transport-safe serialization and separate MCP metadata.

Start persists text/profile or stages an image, calls the matching extractor
only when needed, loads the template, calls native mapping, snapshots the exact
result, and only then commits `pending_review`.

Export is:

```text
load reviewed job under shared lock
  -> native fill_form with persisted field_values
  -> resolve returned native file within CareFlow app-data
  -> verify readable PDF and expected page structure
  -> atomically snapshot into job outputs
  -> checksum/register artifact and commit operation result
  -> return registered absolute output path
```

Structural verification must not reinterpret semantic field placement; native
fill statistics remain the evidence for anchor and widget outcomes.

## 7. Operation-by-Operation Implementation Tasks

### 7.1 `list_templates`

1. Implement its strict no-job discovery schema in `schemas.py`.
2. Invoke native listing through the shared worker and worker-only adapter.
3. Require a valid definition, `ready` status, source PDF, and supported fill
   strategy; apply the Theta rule.
4. Return native metadata and actual source-format capabilities without writing
   job state.

### 7.2 `start`

1. Validate the ready `template_id`, explicit boolean `use_llm`, optional
   `source_hint`, and exact source union.
2. Allocate/lock the namespaced job through shared services; serialize accepted
   text/profile input or validate, hash, and stage the image.
3. Persist the mutation before dispatch, then invoke exactly one extractor for
   text/image or accept the structured profile without extraction.
4. Load the native template and call `map_elder_to_template` with `use_llm`.
5. Snapshot the exact native profile and preview before committing
   `pending_review`; return the shared job envelope.

No `pending_review` job may exist without its durable profile and preview. A
recovery path uses a captured native result when available rather than silently
repeating a completed AI call.

### 7.3 `status`

1. Resolve `job_id` only in the `careflow_government_forms` namespace.
2. Read job and artifact state without invoking CareFlow.
3. Return persisted profile, preview, reviewed values, lifecycle data, and only
   registered MCP-owned artifact paths as authoritative outputs.

### 7.4 `review`

1. Lock a review-eligible job and load the persisted preview key set.
2. Validate complete effective `field_values` and optional `reviewer`.
3. Atomically persist the full replacement set and review metadata, snapshot
   required audit material under `intermediate/`, and commit `reviewed`.
4. Return stored review state without invoking CareFlow.

### 7.5 `export`

1. Lock the reviewed job and apply the shared request-hash/idempotent-replay
   rule.
2. Pass the persisted template ID, ElderProfile, and complete reviewed values
   to native `fill_form`; never pass an unreviewed mapping as an override.
3. Record the native response, fill statistics, and native path as metadata.
4. Validate and atomically promote the PDF through the shared artifact service,
   then register and transactionally commit it.
5. Return the promoted absolute path. A replay returns the committed artifact
   and never overwrites output or remaps reviewed data.

## 8. Validation, Concurrency, and Recovery

Validation rejects malformed variants, invalid `job_id` use, invalid sources,
unsafe/unsupported images, unavailable templates/PDFs/fill strategies,
incomplete reviews, review without a preview, and export without review. File
and capability failures occur before extraction or AI calls.

Within one host process, mutations use the router's per-job lock plus SQLite
request hashes and unique operation/artifact rows. Tests cover strict state
gates, replay primitives, export failure preserving the reviewed state, and
status remaining MCP-owned. Multi-host races, review/export interleavings, and
promotion-window crash injection are not yet automated.

On an observed failure, the shared runtime checkpoints the error while
preserving the last successful job state. A file becomes public only after
structural verification, atomic promotion, and artifact registration. The
current runtime does not keep native commit receipts or automatically reconcile
an ambiguous worker crash; those cases remain the partial recovery criterion
CGF-09.

## 9. Ordered Milestones

| Milestone | Status | Completion evidence / remaining gate |
|---|---|---|
| 1. Package and contract | Complete | Eight modules exist; all five strict operation variants and import-boundary tests pass. |
| 2. Discovery and capabilities | Complete | Stateless discovery, native readiness/capabilities, five bundled IDs, and broken-entry filtering are tested and real-worker verified. |
| 3. Start and preview | Complete for principal paths | Text, image, and structured-profile native routing are tested; status is MCP-owned and makes no native call. Exhaustive golden profile/mapping comparison remains hardening. |
| 4. Review | Complete | Exact preview-key replacement, no-native review, durable state projection, and export gating pass. |
| 5. Export | Complete | Exact reviewed values reach native fill; structural verification/promotion passes; real OALA coordinate and JoyYou AcroForm exports pass. |
| 6. Recovery and release | Partial | Failed export preserves reviewed state; the full suite, clean-wheel audit, and installed OALA lifecycle pass. Race and crash-boundary fault injection remain open. |

## 10. Acceptance Matrix and Current Evidence

| ID | Acceptance criterion | Status | Current evidence / missing evidence |
|---|---|---|---|
| CGF-01 | Registry exposes one implementation; all five operation variants are strict; no cross-tool or host-side CareFlow import exists. | Verified | Schema, import-boundary, and package-contract integration tests. |
| CGF-02 | Discovery is stateless, returns the five ready bundled templates with native metadata, and hides unusable entries. | Verified | Controller/native readiness tests and real-worker discovery. |
| CGF-03 | Text, image, and structured sources invoke only the appropriate native extraction path and preserve native mapping data. | Verified for call boundary | Native adapter tests cover all three variants. Exhaustive normalized golden profile/mapping fixtures are not automated. |
| CGF-04 | Status never recomputes; review atomically stores the exact complete key set; export before review never calls fill. | Verified | Controller and validation tests. |
| CGF-05 | Export passes exactly the persisted reviewed values and never reruns extraction/mapping. | Verified | Native adapter/controller call assertions. |
| CGF-06 | AcroForm and coordinate-anchor outputs retain native strategy, page behavior, and fill metadata. | Verified for principal strategies | Real JoyYou and OALA worker exports plus PDF page/structure checks. Pixel/text-placement golden comparison remains open. |
| CGF-07 | Caller images are immutable after staging and unsupported formats fail before AI invocation. | Verified for supported role rules | Shared staging plus image capability/absolute-path tests. Post-staging caller mutation is guaranteed by copying but lacks a dedicated deletion test. |
| CGF-08 | Invalid PDFs are never registered; valid PDFs are absolute, namespaced, checksummed, structurally verified, and promoted once. | Verified | Artifact/controller/shared-runtime tests. |
| CGF-09 | Failed export preserves reviewed state and completed calls replay without duplicating public artifacts. | Partial | Failure-state preservation and shared idempotent replay pass; exhaustive fault injection at every native/promotion boundary is open. |
| CGF-10 | All three tools share one CareFlow venv/worker/app-data while jobs and imports remain isolated. | Verified | Package-contract and worker-isolation tests, configured routing, clean installed-wheel bootstrap, discovery, and OALA lifecycle. |

## 11. Release Exit Criteria

Tool implementation is complete: the module boundary, all five operations,
three source variants, both fill strategies, review-only export source, output
ownership, and full package suite pass. Release closure still requires the
partial CGF-09 fault/concurrency evidence and the architecture's cleaned-wheel
gate.

## 12. Deferred and Out of Scope

Theta authoring and its current PDF-path fix remain separate work. Also out of
scope are changes to ElderProfile extraction, mapping heuristics, LLM prompts
or model selection, template coordinates, widget behavior, fill statistics,
PDF rendering, native output naming, and shared host/runtime architecture.
