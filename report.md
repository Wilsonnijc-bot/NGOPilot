# NGOPilot Runtime Persistence and Data-Structure Investigation

Date: 2026-08-03  
Scope: `harness bone`, `algo-dependencies/CareFlow`, `algo-dependencies/RosterCopiilot`, and the MCP bridge that actually connects them at runtime.

## Executive conclusion

NGOPilot is not backed by one database or one shared domain model. A real workflow crosses four independent persistence domains:

```text
NGOPilot desktop / Goose harness
    |
    | stdio MCP calls and tool responses
    v
NGOPilot MCP host
    |
    | one-shot isolated Python worker, carrying a native object ID
    +--------------------------+
    |                          |
    v                          v
CareFlow native state          RosterCopiilot native state
```

The corresponding durable stores are:

1. Harness SQLite: `<goose-data-dir>/sessions/sessions.db`
2. MCP SQLite: `<mcp-state-root>/jobs.sqlite3`
3. CareFlow SQLite: `<mcp-state-root>/app-data/careflow/careflow.db`
4. Roster SQLite: `<mcp-state-root>/app-data/rostercopiilot/roster.db`

All four matter. The MCP database is authoritative for public job identity, current public result, idempotent operation replay, and promoted artifacts. The native database is authoritative for algorithm-specific follow-up operations. The harness database is authoritative for chat/session continuity. Files adjacent to the databases are also required; copying only the `.db` files is not a complete backup.

The most important findings are:

- A harness session is not relationally linked to an MCP job. The link survives only inside message JSON or optional extension JSON.
- Deleting a harness session does not delete its MCP jobs, native records, staged inputs, exports, or sensitive data.
- The MCP layer has no job retention, purge, or schema-migration mechanism.
- CareFlow declares foreign keys but does not enable SQLite foreign-key enforcement. A real runtime connection reported `PRAGMA foreign_keys=0` and accepted an orphan `volunteer_record`.
- CareFlow's transcript burn is local to the encrypted transcript file. It does not purge plaintext snippets or transcript-derived content already persisted by MCP or the harness.
- One representative roster run produced a 36.2 MB native database and a 10.1 MB worker status envelope. Its public result alone was about 9.56 MB. Every persisted status/review response can therefore add roughly another 9.6 MB to MCP operation history, plus another copy in the harness conversation.
- Roster enables SQLite foreign-key enforcement, but its schema declares zero foreign-key edges. Referential correctness is implemented only in Python reconstitution checks.
- CareFlow, Roster, and MCP use `create_all()` / `CREATE TABLE IF NOT EXISTS` without a real versioned database migration path. Only the harness has a schema version and ordered migrations.
- The packaged runtime executes pinned, vendored algorithm payloads from the MCP wheel. The inspected CareFlow 0.4.8 and RosterCopiilot 0.6.0 payloads match the algorithm source trees for runtime files.

## Investigation method

This report is based on both static tracing and real isolated execution.

Static tracing covered:

- harness path resolution, session storage, schema migrations, extension configuration, and session deletion;
- MCP path resolution, job/operation/artifact storage, file staging, artifact promotion, worker configuration, and bootstrap;
- CareFlow ORM models and paper-form, meeting-note, transcript-vault, template, and government-form services;
- Roster ORM models, weekly-run reconstitution, review, revalidation, export, publication, master-data, archive, and workspace services.

Runtime validation used disposable directories under `/tmp`; existing user databases were not changed. The representative runs were:

- CareFlow paper form: real managed worker, one bundled sample image, mock AI provider, then review and Excel export.
- CareFlow meeting note: real managed worker, sample MP3 and DOCX, mock AI path, then review, export, and transcript burn.
- Roster: real managed worker with representative HC and escort workbooks, creating a durable blocked weekly run.
- Foreign-key checks were executed through the applications' own SQLAlchemy engines, not inferred from a separate `sqlite3` connection.

The temporary evidence roots are listed in the appendix. They are disposable audit output, not part of the application.

## Runtime deployment boundary

The desktop enables a bundled stdio extension named `NGOPilot` with:

```text
ngopilot-mcp serve --transport stdio
```

See `harness bone/ui/desktop/src/components/settings/extensions/bundled-extensions.json`.

The launcher bootstraps two isolated virtual environments and then starts the MCP server. It defaults `NGOPILOT_MCP_STATE_DIR` to `~/.ngopilot-mcp`; see `harness bone/ui/desktop/src/bin/ngopilot-mcp`.

The managed workers do not normally import the sibling `algo-dependencies` checkout. `MCPcode/src/ngopilot_mcp/config.py` resolves CareFlow and Roster to payloads vendored inside the installed MCP package when those payloads exist. `vendor.lock.toml` pins:

| Dependency | Runtime version | Pinned source revision |
|---|---:|---|
| CareFlow | 0.4.8 | `50e0d2d3efa0662c5452fb5d6038f489fcd2bc7d` |
| RosterCopiilot | 0.6.0 | `312ac9a84968aef71a7180c3ea132fe628275177` |

Bootstrap verifies payload tree hashes, wheel hashes, lock-file hashes, and required resource hashes before running. A tree comparison found the runtime Python and required data files equal to the current algorithm dependency trees; differences were only development files, tests, logs, sample data, frontend content, and documentation excluded from the payload.

Each native call is a fresh subprocess. `MCPcode/src/ngopilot_mcp/workers/base.py` injects:

```text
CareFlow:
  DATA_DIR=<state>/app-data/careflow
  DATABASE_URL=sqlite:///<state>/app-data/careflow/careflow.db

Roster:
  ROSTER_DB_PATH=<state>/app-data/rostercopiilot/roster.db
  ROSTER_EXPORT_DIR=<state>/app-data/rostercopiilot/exports
```

Consequently, in-memory Python objects never bridge calls. A follow-up operation works only because MCP reloads a native ID from `jobs.sqlite3` and the worker reconstructs the domain object from the native database.

## Complete state layout

### Harness state

With an absolute `GOOSE_PATH_ROOT=/path/to/root`:

```text
/path/to/root/
  config/
  data/
    sessions/
      sessions.db
      sessions.db-wal        # while WAL contains uncheckpointed data
      sessions.db-shm
  state/
```

Without `GOOSE_PATH_ROOT`, the harness intentionally uses Goose's backward-compatible platform directory under the `Block/goose` application identity. On macOS this is normally beneath `~/Library/Application Support/Block/goose/`.

The desktop only forwards `GOOSE_PATH_ROOT` when the environment already supplies a valid absolute path. It does not automatically derive an NGOPilot-specific path. This creates a real collision risk with an existing Goose installation.

### MCP and native state

Default root:

```text
~/.ngopilot-mcp/
  jobs.sqlite3
  jobs.sqlite3-wal
  jobs.sqlite3-shm
  jobs/
    <tool_name>/
      <job_id>/
        manifest.json
        inputs/
        intermediate/
        outputs/
        logs/
  app-data/
    careflow/
      careflow.db
      uploads/
      exports/
      visit_sessions/
      transcripts/
      .transcript_key
      form_templates/
      templates/
      welfare_outputs/
    rostercopiilot/
      roster.db
      roster.db-wal
      roster.db-shm
      exports/
  runtimes/
    careflow/.venv/
    rostercopiilot/.venv/
  resources/
    careflow/
    rostercopiilot/
```

`NGOPILOT_MCP_STATE_DIR` can move this root. It is independent of `GOOSE_PATH_ROOT`, so the current product has two separately configured state roots.

## Authority by layer

| Layer | Authoritative for | Not authoritative for |
|---|---|---|
| Harness `sessions.db` | Session metadata, messages/tool responses, model usage, enabled extension snapshot | Native workflow state or artifact integrity |
| MCP `jobs.sqlite3` | Public job ID/state, request idempotency, current public result, operation replay, artifact registry | Native review/version state after a restart |
| MCP `jobs/...` files | Immutable staged inputs, promoted outputs, logs, manifest projection | CareFlow/Roster domain state |
| CareFlow `careflow.db` + files | Paper batches, records, corrections, meeting sessions, transcript vault references, native outputs | MCP job identity; government-form review state |
| Roster `roster.db` + files | Weekly-run snapshots, versions, decisions, overrides, publication records, master data | MCP job identity and promoted output paths |

There is no distributed transaction across these layers. A native commit can succeed before MCP commits its public projection, and a harness message can fail to persist after MCP completes an operation. Recovery therefore needs reconciliation, not just database restart.

## Harness database

Source of truth: `harness bone/crates/goose/src/session/session_manager.rs`.

The database uses WAL, a 30-second busy timeout, and foreign keys. Its current schema version is 15.

### Fresh schema tables

| Table | Runtime role | Essential to NGOPilot workflow recovery? |
|---|---|---|
| `schema_version` | Ordered harness migration ledger | Yes, for safe harness upgrades |
| `sessions` | One row per chat/agent session | Yes |
| `messages` | Structured user, assistant, and tool messages | Yes |
| `usage_ledger` | Append-only token/cost accounting | No for algorithm recovery; yes for accounting |
| `provider_inventory_entries` | Provider/model inventory cache header | No for algorithm recovery |
| `provider_inventory_models` | Cached models for an inventory entry | No for algorithm recovery |

An upgraded older database may also retain `threads` and `thread_messages`, created by migration 10. Fresh schema creation at version 15 does not create these tables, and later migrations do not remove them. They should be treated as legacy/migration residue, not a current NGOPilot runtime dependency.

### Important columns and structures

`sessions` contains:

- identity and UI metadata: `id`, `name`, `description`, `session_type`, timestamps, archive/project/parent fields;
- execution context: `working_dir`, `provider_name`, `model_config_json`, `goose_mode`;
- recipes and schedule metadata;
- current and accumulated usage counters;
- `extension_data`, a JSON string.

`extension_data` is a flattened map keyed as `<extension>.<version>`. Enabled extensions are stored under `enabled_extensions.v0` as serialized extension configurations. This can preserve the fact that NGOPilot MCP was enabled for a session, but there is no built-in `ngopilot_job` record and no normalized foreign key to an MCP job.

`messages.content_json` is a JSON array of structured message parts. MCP tool requests and responses, including `job_id`, returned domain data, and potentially sensitive snippets, are persisted here as conversation content. This is the only reliable harness-side place where a job ID currently appears.

### Deletion behavior

`delete_session()` explicitly deletes `messages`, then `usage_ledger`, then `sessions` in one immediate transaction. It does not notify MCP and cannot delete any MCP or native state. Provider inventory is global and unaffected.

This creates both orphaning directions:

- deleting a harness session leaves its jobs and algorithm data indefinitely;
- deleting or losing MCP/native state leaves an apparently valid harness conversation whose follow-up tool calls cannot be completed.

## MCP job database and file store

Source of truth: `MCPcode/src/ngopilot_mcp/shared/jobs/store.py`, `shared/runtime.py`, and `shared/files/`.

The database uses WAL, foreign keys, and a 30-second busy timeout.

### Tables

#### `jobs`

One mutable public projection per workflow:

- `job_id`, `tool_name`, public `state`, and `native_status`;
- `input_json` and its canonical hash;
- latest `result_json`;
- `native_refs_json`, such as CareFlow batch/session IDs or Roster run/version IDs;
- warnings, next operations, and error JSON;
- optional start request ID and timestamps.

`UNIQUE(tool_name, start_request_id)` provides idempotent start behavior.

#### `operations`

One append-only row per operation attempt:

- operation identity, job ID, operation name, and request ID;
- canonical request hash;
- `running`, `succeeded`, or `failed` status;
- full `response_json` and error JSON.

`UNIQUE(job_id, request_id)` prevents a request ID from being reused inside one job. A successful or failed operation can be replayed without invoking the native worker again.

#### `artifacts`

Metadata for each promoted output:

- owning job and artifact kind;
- promoted path and original native path;
- media type, byte size, SHA-256, and timestamp.

Artifact access rechecks that the file remains below the job's `outputs/` directory and still matches the recorded size and hash.

### File structures

Input staging copies every accepted input into a per-job `inputs/` directory with a content-derived name and mode `0600`. Native algorithms often copy the same file again into their own data tree.

Artifact promotion copies every native output into a per-job `outputs/` directory, also mode `0600`. Native exports remain in their native output directories, producing another duplicate.

`manifest.json` is an atomic, mode-`0600` projection containing job identity, current state, native references, artifact metadata, warnings, and errors. It intentionally omits the full result and input. It is useful for inspection but is not sufficient to reconstruct the job store.

### Missing lifecycle and migration support

There is no job-delete API, retention policy, garbage collector, or purge routine in the MCP package. There is also no database schema version. Startup only runs `CREATE TABLE IF NOT EXISTS`, which cannot safely add/change columns or rebuild constraints in future releases.

The foreign keys from `operations` and `artifacts` to `jobs` do not specify `ON DELETE CASCADE`. A future job-deletion feature must explicitly order deletions or migrate these constraints.

### Multiplication of sensitive data

For a typical operation, the same logical result may exist in all of:

1. `jobs.result_json` as the latest projection;
2. `operations.response_json` as an immutable replay snapshot;
3. harness `messages.content_json` as the tool response;
4. native JSON columns;
5. `manifest.json` for selected metadata;
6. source/native/promoted file copies.

This is especially costly for Roster and especially sensitive for CareFlow.

## CareFlow native state

Source of truth: `algo-dependencies/CareFlow/backend/app/models.py`, `app/db.py`, and `app/services/`.

CareFlow has seven SQLModel tables. It runs `SQLModel.metadata.create_all()` and one silently ignored `ALTER TABLE theta_field ADD COLUMN bbox_llm JSON`. It has no schema-version table and no ordered migration ledger. Historical README references to Alembic do not match the active code.

### Table inventory

| Table | Important data | Used by exposed MCP workflow? |
|---|---|---|
| `volunteer_batch` | Batch metadata, state, photo/review counts, export path | Yes: paper forms |
| `volunteer_record` | Photo path, AI extraction/confidence/bboxes/raw response, reviewed values | Yes: paper forms |
| `field_correction` | Per-field AI value, final value, confidence, reviewer | Yes: paper forms |
| `visit_session` | Meeting inputs, parsed template, slots, transcript vault reference, output | Yes: meeting notes |
| `elder` | Standalone elder profile | No in current MCP tools |
| `theta_template` | Native custom-PDF template analysis | No in current MCP tools |
| `theta_field` | Analyzed fields and bounding boxes | No in current MCP tools |

The government-form MCP workflow intentionally creates no CareFlow database row.

### Foreign-key behavior

The schema declares:

```text
volunteer_record.batch_id -> volunteer_batch.id
field_correction.record_id -> volunteer_record.id
field_correction.batch_id -> volunteer_batch.id
theta_field.template_id -> theta_template.id
```

None has an explicit delete action. More importantly, CareFlow's engine does not enable `PRAGMA foreign_keys=ON`. An application-engine test reported `0`, and an orphan `volunteer_record(batch_id=999, ...)` was accepted. The declared relationships therefore do not protect production data today.

### Paper-form workflow

#### Start

The MCP source image is copied to:

```text
jobs/careflow_paper_forms_to_excel/<job_id>/inputs/...
```

CareFlow then copies its bytes to:

```text
app-data/careflow/uploads/batch_<batch_id>/<uuid>_<original_name>
```

Native mutations:

- one `volunteer_batch` row;
- one `volunteer_record` row per image;
- batch state progresses through uploaded/extracting to pending review or failed;
- the record stores extracted fields, confidence, bounding boxes, provider/model, latency/error, and `ai_raw_response`.

The MCP job stores the native `batch_id`, record IDs, and staged source paths. Follow-up status and review use the native batch ID.

#### Review

Review updates `volunteer_record.final_fields`, reviewer metadata, and reviewed state. It also creates a `field_correction` row for every schema field, not only changed fields. In the representative run, one record produced 13 correction rows even though only four submitted values differed from or replaced AI values.

When all records are reviewed, `volunteer_batch` becomes confirmed and receives confirmation metadata.

#### Export

Export reads the reviewed native rows and the active Excel template, then writes:

```text
app-data/careflow/exports/batch_<id>_<timestamp>.xlsx
```

The batch records this relative path and exported state. MCP then copies the workbook into the job's `outputs/` directory and records its hash.

#### Observed paper-form result

One image, one review, and one export populated:

| Table | Rows |
|---|---:|
| `volunteer_batch` | 1 |
| `volunteer_record` | 1 |
| `field_correction` | 13 |
| all other CareFlow tables | 0 |

The native data tree contained the database, copied image, generated/default Excel template, and native exported workbook. The database was 49,152 bytes and the complete native data tree was about 164 KB for this one-record mock run.

### Meeting-note workflow

#### Start / phase 1

MCP first stages the audio and DOC/DOCX template. CareFlow then copies them again to:

```text
visit_sessions/session_<id>/audio_<uuid>.<ext>
visit_sessions/session_<id>/template_<uuid>.<ext>
```

It creates one `visit_session` row, normalizes the template to:

```text
visit_sessions/session_<id>/work/normalized_template.docx
```

and persists the complete parsed template contract, draft slot content, and initial final slot content as JSON columns.

The transcript is encrypted with Fernet and stored at:

```text
transcripts/session_<id>.enc
```

The key is generated once and stored at:

```text
.transcript_key
```

The database stores only the transcript file's relative path and burn flag. The key is mode `0600`; other native files rely on protection of the mode-`0700` MCP state-root directories.

#### Review / phase 2

Review replaces `slot_content_final`, renders a DOCX, and records reviewer/timestamp and the relative generated path:

```text
exports/visit_notes/visit_note_<id>_<timestamp>.docx
```

MCP promotes another copy into the job output directory.

#### Export

The MCP `export` operation does not ask CareFlow to render again. It validates and returns the already promoted artifact created during review.

#### Burn

Native burn overwrites the encrypted transcript with at least 1,024 random bytes, fsyncs it, unlinks it, clears `transcript_vault_path`, and sets `transcript_burned=true`.

It does not delete:

- the staged or native audio;
- uploaded and normalized templates;
- generated notes;
- template/slot JSON in `visit_session`;
- previous MCP operation responses;
- the current or previous harness messages;
- the transcript key.

Although the enum defines `BURNED`, burn leaves a confirmed session in `CONFIRMED`. The representative run showed this exact behavior.

#### Observed meeting result

The representative start created one `visit_session` and no rows in any paper-form table. After review/export/burn, the native tree retained:

- `careflow.db`;
- `.transcript_key`;
- original audio copy;
- original template copy;
- normalized working DOCX;
- generated DOCX.

The encrypted transcript was gone. The database retained the complete template contract and slot documents. The mock path was incorrectly labeled `deepseek_official` / `deepseek-v4-flash` because the adapter did not pass `force_mock`; this makes persisted AI lineage inaccurate.

### Transcript privacy boundary is incomplete

`read_transcript_snippet()` decrypts and returns up to 200 characters. The MCP `public_session()` explicitly whitelists `transcript_snippet`, so it is persisted in `jobs.result_json`, each operation's `response_json`, and normally the harness tool message. Tests explicitly assert that this snippet is public.

The representative slot content also embedded longer transcript-derived excerpts. Those values are stored in CareFlow's `slot_content`/`slot_content_final`, copied to MCP JSON, and returned to the harness.

Therefore, “burn transcript” currently means “destroy the native encrypted full-transcript file.” It does not mean “erase transcript plaintext or derived personal data across NGOPilot.” This distinction must be explicit in product behavior and retention policy.

### Government-form workflow

The native database is not involved.

At bootstrap, MCP copies five pinned JSON form definitions and five source PDFs into CareFlow's data root. The available templates and observed field counts are:

| Template | Fields |
|---|---:|
| `ccsv` | 6 |
| `cssa` | 11 |
| `joyyou` | 20 |
| `oala` | 14 |
| `ssa_307` | 14 |

Start extracts or accepts an elder profile and maps it to a template. The elder profile, mapping preview, source metadata, and later reviewed values exist only in MCP `jobs` and `operations`. Status is an MCP database read; review is an MCP-only update. Export invokes CareFlow with the stored profile and values, writes a native PDF under `welfare_outputs/`, and promotes a second copy to the MCP job output directory.

This has a sharp recovery consequence: losing `jobs.sqlite3` loses the editable/reviewable government-form state even when native PDFs survive. There is no native row from which to reconstruct it.

## RosterCopiilot native state

Source of truth: `algo-dependencies/RosterCopiilot/backend/app/store/sqlite.py` and `backend/app/domain/`.

Roster creates 14 SQLModel tables. It uses WAL, `synchronous=NORMAL`, a 30-second busy timeout, and enables foreign-key enforcement on each application connection. However, `PRAGMA foreign_key_list` across all 14 emitted tables returns zero edges: no model declares a SQL foreign key.

Roster also has no database schema-version table or migration runner. `MasterDataVersionRecord.schema_version` versions the JSON document format, not the SQL schema.

### Table groups

#### Compatibility / generic scheduler state

| Table | Role | Required by current MCP weekly-run follow-ups? |
|---|---|---|
| `storemeta` | Current generic app-state pointers | No |
| `datasetsnapshot` | Generic current mock dataset JSON | No |
| `storedscheduleversion` | Generic scheduler version JSON | No |

These tables are populated by service-state initialization and support the native app's older/general scheduler surface. `get_weekly_run()` does not read them.

#### Import and alias review

| Table | Role | Used by the tested MCP start? |
|---|---|---|
| `importbatchrecord` | Imported batch summary and payload | No |
| `importambiguityrecord` | Ambiguities and resolutions | No |
| `aliasresolutionrecord` | Manual alias to canonical entity mappings | No |

The weekly demo imports the submitted workbooks into its durable weekly-run document instead of using these generic import-review tables.

#### Master data

| Table | Role | Runtime requirement |
|---|---|---|
| `masterdataversionrecord` | Append-only complete master-data JSON and issues | Required to seed future runs; current run stores its own snapshot |

The payload contains workers, elders, fixed services, availability, leave/temporary changes, rules, and manual overrides. A first weekly run bootstraps version 1 from the division workbook if no current master data exists.

#### Weekly-run core

| Table | Role | Required when populated? |
|---|---|---|
| `weeklyrundocument` | Mutable run envelope and current pointer | Yes |
| `weeklyrunscheduleversion` | Immutable schedule-version JSON and content hash | Yes |
| `weeklyrundecision` | Immutable review decisions and idempotency | Yes after review |
| `weeklyrunmanualoverride` | Overrides tied to decisions | Yes when an override exists |
| `weeklyrunpublication` | Published artifact identity/path/hash | Yes after publication |

`weeklyrundocument` is the largest and most duplicated structure. It stores:

- `snapshot_json`: normalized scheduler input;
- `dataset_json`: workers, elders, fixed services, escorts, duties, and other entities;
- `generated_json`: generated demands, source evidence, and data gaps;
- `scheduler_result_json`: baseline/current versions, reports, and violation/audit structures;
- `latest_export_report_json`;
- `latest_export_plan_json`, including a duplicate review version, report, placements, and changed-cell map;
- run context, master-data version reference, and latest content hash.

`weeklyrunscheduleversion.payload_json` stores another immutable full schedule version. Decisions and overrides create additional immutable versions and update the run's current pointer with a compare-and-swap.

The decision schema declares a globally unique `idempotency_key`, while application code stores it as `<run_id>:<client_key>`. This currently provides per-run behavior, but that scope is a Python convention rather than a relational composite constraint.

#### Workspace and archives

| Table | Role | Used by exposed MCP operations? |
|---|---|---|
| `weeklyworkspacestatedocument` | Single current-run pointer for browser restore | Written at start, not needed by MCP follow-ups |
| `weeklyrunarchivedocument` | Immutable browser-safe archived snapshot | No; archive operations are native-web only |

### Domain object reconstruction

Roster's relational rows are envelopes around Pydantic documents. The essential runtime structures are defined in:

- `backend/app/domain/entities.py`: workers, elders, services, duties, demands, and related entities;
- `backend/app/domain/snapshot.py`: scheduler input, availability, constraints, and weekly context;
- `backend/app/domain/schedule.py`: schedule entries, audit items, versions, reconciliation, and provenance;
- `backend/app/domain/master_data.py`: canonical versioned master data;
- `backend/app/domain/persistence.py`: decisions, overrides, publications, and complete weekly-run record.

On every status/review/revalidate/export call, Roster parses JSON back into these models and performs logical integrity checks:

- every stored schedule version's content hash is recomputed;
- the current version must exist and match `latest_content_hash`;
- decision/override/publication identities must match their payloads;
- the cached export report and export plan must match the current version and reconciliation hash;
- publication artifacts must exist and match SHA-256.

These checks are strong application-level defenses, but SQLite itself cannot prevent orphan run IDs, orphan decision IDs, duplicate logical relationships, or malformed JSON.

### Observed representative run

The real managed worker produced:

| Metric | Value |
|---|---:|
| Native status | `blocked` |
| Run ID | `edefdd779479` |
| Master-data version | 1 |
| Schedule entries/tasks | 831 |
| Audit items | 296 |
| Snapshot demands | 852 |
| Data gaps | 420 |
| Source evidence records | 1,245 |

Populated tables:

| Table | Rows |
|---|---:|
| `masterdataversionrecord` | 1 |
| `weeklyrundocument` | 1 |
| `weeklyrunscheduleversion` | 1 |
| `weeklyworkspacestatedocument` | 1 |
| `storemeta` | 1 |
| `datasetsnapshot` | 1 |
| `storedscheduleversion` | 1 |
| all other Roster tables | 0 |

The database occupied 36,204,544 bytes. Approximate JSON column sizes were:

| Document | Bytes |
|---|---:|
| Master-data payload + issues | 505,091 |
| Weekly snapshot | 1,786,610 |
| Weekly dataset | 793,015 |
| Generated payload | 1,767,473 |
| Scheduler result | 12,111,096 |
| Latest export report | 1,220,389 |
| Latest export plan | 11,239,435 |
| Immutable weekly schedule version | 5,912,217 |
| Compatibility dataset/schedule snapshots | 675,437 |

A compact native `status` worker envelope for this single run was 10,101,249 UTF-8 bytes. Its compact public result was 9,561,406 bytes.

Because MCP replaces `jobs.result_json` but appends a full `operations.response_json`, the first stored status requires roughly two 9.6 MB JSON copies in MCP. Each further uniquely identified status/review/revalidate call appends another full response. The harness normally persists another copy as a tool result. This growth is unbounded because none of the stores has a retention policy.

### Files required outside `roster.db`

The original HC and escort workbooks are preserved in MCP job inputs, not in Roster's native data directory. The normalized snapshot in `weeklyrundocument` is sufficient for current reconstitution.

Draft and published exports live under the native export root. Published records store an absolute `artifact_path` and require that exact file to remain present and hash-valid. MCP promotes another copy and stores another absolute path.

Roster export/reconstitution also reads the division template from the installed, vendored dependency:

```text
docs/照顧員工作分工表2026(HKU).xlsx
```

MCP records its path and hash but does not copy a versioned template into the native run. An upgrade that replaces or relocates this template can make an old run fail reconstitution or export even when its database is intact.

## Operation-level recovery requirements

| Workflow / operation | Minimum durable state needed after restart |
|---|---|
| Any MCP follow-up | MCP `jobs` row with native reference; operation ledger for idempotent replay |
| Return an existing promoted artifact | MCP `artifacts` row and exact job `outputs/` file |
| Paper status | MCP job + CareFlow batch/record rows |
| Paper review | Above; staged/native image needed for human evidence but not by the update query itself |
| Paper export | Reviewed CareFlow rows + active Excel template + writable exports directory |
| Meeting status | MCP job + `visit_session`; vault file and key are needed to return a snippet |
| Meeting review/render | `visit_session.template_contract` + `slot_content_final` + working normalized DOCX |
| Meeting burn | `visit_session` + vault file; key is not needed to overwrite/unlink but is needed for prior reading |
| Government-form status/review | MCP `jobs.sqlite3` only |
| Government-form export | MCP reviewed result + seeded JSON definition and source PDF |
| Roster status/review/revalidate | MCP job + `weeklyrundocument` + all run versions/decisions/overrides that have been created |
| Roster draft export | Above + the matching installed division template + native export directory |
| Roster publish/get published | Above + publication row + exact native published file; MCP copy for MCP artifact return |
| Resume from harness UI | Harness session/messages + all relevant MCP/native state above |

## Backup and restore requirements

### What must be backed up

A complete operational backup needs:

1. harness `sessions.db`;
2. MCP `jobs.sqlite3`;
3. the entire MCP `jobs/` tree;
4. CareFlow `careflow.db` and the entire CareFlow data tree;
5. Roster `roster.db` and the entire Roster export tree;
6. the exact vendored algorithm/template version, or immutable copies of runtime templates;
7. CareFlow `.transcript_key` whenever any unburned transcript must remain recoverable.

Backing up `careflow.db` without `.transcript_key` makes encrypted transcripts unrecoverable. Backing up the key without the vault files is also insufficient. Co-locating the key and ciphertext means the encryption mainly prevents casual plaintext inspection; it does not protect against compromise of the complete state directory.

### Snapshot consistency

Harness, MCP, and Roster use WAL. Copying only the main `.db` file while the application is running can omit committed pages still in `-wal`. Use SQLite's online backup API, `VACUUM INTO`, or a coordinated stop/checkpoint before copying.

Files and database rows are not committed atomically together. A defensible backup procedure should:

1. quiesce new operations;
2. checkpoint or online-backup all databases;
3. snapshot file trees while quiesced;
4. record hashes and dependency/template versions in a backup manifest;
5. restore into a temporary root and run integrity/reconstitution checks before accepting it.

### Relocation problems

CareFlow stores most native paths relative to `DATA_DIR`, which is relocation-friendly.

MCP artifact rows, job results, staged-source references, and native-source references contain absolute paths. Roster publication payloads also require absolute paths. Moving a restored state root will therefore break artifact verification and publication loading unless paths happen to remain identical.

The backup format should store root-relative paths and rebase them on restore. Absolute external source paths may remain only as non-authoritative provenance metadata.

## Data sensitivity

The stores contain plaintext personally identifiable and operational data:

- names, addresses, phone numbers, ages, gender, health concerns, living status, and follow-up notes;
- uploaded form images, audio recordings, templates, and generated documents;
- meeting template slots and transcript-derived draft text;
- workers, elders, availability, services, duties, assignments, schedule conflicts, audit evidence, and reviewer decisions;
- AI raw responses and provider errors;
- absolute local paths revealing usernames and directory layout.

Directory mode `0700` and staged/promoted file mode `0600` are useful controls, but the SQLite databases are not application-encrypted. Native files are generally created with normal umask permissions and rely on the protected ancestor directory.

`volunteer_record.ai_raw_response` is particularly risky because it can preserve provider output beyond the structured fields actually needed for the workflow. Its retention should be opt-in, time-limited, redacted, or moved to an encrypted audit store.

## Prioritized production changes

### P0: required before treating persistence as production-ready

1. **Define one product state root and wire it automatically.** Derive both `GOOSE_PATH_ROOT` and `NGOPILOT_MCP_STATE_DIR` from the desktop application's private user-data directory. Do not default NGOPilot harness data into the legacy Goose namespace.

2. **Implement versioned migrations for MCP, CareFlow, and Roster.** Add a schema-version ledger, ordered transactional migrations, compatibility checks, and migration/rollback fixtures from every released version. `create_all()` is initialization, not migration.

3. **Fix CareFlow referential integrity.** Enable `PRAGMA foreign_keys=ON` on every connection and add explicit delete policies. Test parent deletion, failed extraction, partial review, and restore with `PRAGMA foreign_key_check`.

4. **Define cross-store lifecycle ownership.** Introduce a durable link containing at least harness session ID, MCP job ID, tool, native ID, sensitivity class, retention policy, and timestamps. Session deletion must either cascade through an audited purge service or clearly transfer the job to a retained-record policy.

5. **Make transcript burn end-to-end or rename it.** Do not persist `transcript_snippet` in the MCP operation ledger or harness. Decide which derived slot content is subject to erasure. A true burn must purge/redact current job JSON, prior operation responses, harness message content, staged/native audio according to policy, and all transcript-derived caches. Record only a non-sensitive burn audit event.

6. **Stop returning full Roster documents on every operation.** Return a bounded summary, version/hash, counts, blocking items page, and references to paginated/queryable details. Store large immutable documents once, preferably as content-addressed compressed blobs. Do not append a 9.6 MB replay response for every status call.

7. **Add retention and garbage collection.** Cover database rows, job inputs, native copies, delivery copies, promoted outputs, logs, failed operations, old schedule versions, and unpublished exports. Retention must be sensitivity-aware and crash-safe.

8. **Build and test one coordinated backup/restore command.** It must include SQLite online snapshots, all required files and keys, dependency/template versions, hashes, and relocation rebasing.

### P1: integrity and operability

9. **Replace absolute authoritative paths with root-relative paths.** This applies to MCP artifacts/native paths, Roster publication paths, and template references. Validate all rebased paths remain within the expected root.

10. **Add relational constraints to Roster's headers.** At minimum, connect schedule versions, decisions, overrides, publications, workspace state, and archives to their weekly run; connect overrides to decisions and publications to versions. Define cascade/restrict behavior. Keep Python content-hash validation as defense in depth.

11. **Version and validate every JSON document.** Add explicit document schema versions and `CHECK(json_valid(...))` where JSON remains in SQLite. Validate on write and read. Consider normalized tables for query-heavy review/audit items and content-addressed blobs for large immutable documents.

12. **Correct AI lineage.** Persist the provider/model actually used. The meeting mock run being labeled as DeepSeek is an auditability defect. Limit or redact raw model responses.

13. **Make CareFlow's burn state machine coherent.** Either transition to `BURNED` and define which operations remain valid, or remove the unused enum and model burn as an independent transcript-retention state.

14. **Preserve immutable runtime templates per run.** Store a versioned copy or content-addressed resource for the Roster division template and CareFlow forms. Do not make old runs depend solely on the currently installed wheel's resource path.

15. **Add reconciliation tooling.** Detect MCP jobs with missing native rows, native rows with no MCP owner, missing files, hash mismatches, stuck `running` operations, invalid foreign keys, and harness messages referring to unknown jobs.

### P2: security and product completeness

16. **Provide secure provider configuration for the bundled MCP extension.** The bundled extension currently declares `env_keys: []`, while real CareFlow execution needs Azure OpenAI, DeepSeek, and DashScope credentials unless mock behavior is intended. Store secrets in the harness keychain and pass only the required environment keys to the MCP process.

17. **Encrypt sensitive databases or require an encrypted volume.** Use a documented key-management and recovery policy. Encryption keys should not simply live beside all protected data without a separate trust boundary.

18. **Minimize duplicate inputs and outputs.** A content-addressed private object store can let MCP and native workflows reference one immutable object while retaining hashes and provenance. If hard links are used, verify filesystem and deletion semantics.

19. **Add storage quotas and observability.** Track bytes by job/run, operation-response growth, artifact count, old failed jobs, and backup freshness. Warn or compact before the unbounded JSON ledgers exhaust disk.

## Recommended target persistence model

A conservative evolution can keep SQLite while making ownership explicit:

```text
product_state/
  harness/
    sessions.db
  workflow/
    workflow.db
      workflow(session_id, job_id, tool, native_type, native_id, state,
               sensitivity, retention_class, created_at, updated_at)
      operation(... bounded response summary/reference ...)
      object(... relative_path, sha256, size, encryption metadata ...)
      artifact(... object_id, kind, media type ...)
  objects/
    sha256/<digest>
  careflow/
    careflow.db
    ... relative native state ...
  roster/
    roster.db
    ... relative native state ...
  migrations/
  backup-manifests/
```

The workflow store should not replace native correctness rules. It should own cross-layer identity, lifecycle, idempotency, bounded public projections, and retention. Native databases should continue to own their domain models. Large immutable Roster snapshots should be referenced by content hash instead of copied into every response. Sensitive transient fields should be marked non-persistable at the tool boundary.

## Final assessment

The current system is restart-capable only when all four databases and their adjacent file trees survive at their original paths. Within that constraint, the MCP/native ID boundary is sound and the Roster application performs substantial content-hash and reconstitution validation.

It is not yet a coherent production persistence system. The missing cross-store lifecycle, incomplete transcript erasure, unbounded JSON duplication, absent migrations in three stores, CareFlow's disabled foreign keys, and absolute-path coupling are material data-loss, privacy, and operability risks. These should be resolved before relying on the current stores for regulated NGO case records or long-lived scheduling history.

## Appendix: runtime evidence

Disposable schema catalog:

```text
/tmp/ngopilot-db-audit.VzNz9A
```

Representative Roster run:

```text
/tmp/ngopilot-roster-run.ZRq9qr
```

Representative CareFlow paper workflow:

```text
/tmp/ngopilot-careflow-paper.LGMrEi
```

Representative CareFlow meeting workflow:

```text
/tmp/ngopilot-careflow-meeting.AACVXW
```

The foreign-key probes used separate disposable roots under `/tmp/ngopilot-careflow-fk*` and `/tmp/ngopilot-roster-fk*`.

No pre-existing repository or `~/.ngopilot-mcp` database was modified during these runs. The only repository change made for this investigation is this report.
