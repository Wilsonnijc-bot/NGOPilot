# NGOPilot Agent-MCP Architecture Design Plan

Status: proposed  
Date: 2026-08-02  
Product: NGOPilot, a tailored and renamed distribution of goose

## 1. Product Definition

NGOPilot is **goose renamed and tailored for NGO operations**. It is not a new
agent, an agent layered on top of goose, or an agent-to-agent system.

The existing goose agent runtime remains the foundation. We will change its
product identity, default behavior, enabled tools, and user experience so the
result behaves as NGOPilot. NGOPilotMCP is the domain capability dependency
that gives this tailored agent the CareFlow and Roster workflows.

The product equation is:

```text
NGOPilot = goose core
          + NGOPilot branding
          + NGO-specific system behavior
          + NGOPilotMCP enabled as the primary extension
          + NGO workflow UI and defaults
```

MCP installation and Python packaging are outside this architecture plan. The
runtime environment is assumed to provide a working `ngopilot-mcp` executable
and its algorithm dependencies.

## 2. Architecture Decision

Keep goose's existing architecture and use its existing stdio MCP extension
support. Do not introduce another service or protocol adapter between goose and
NGOPilotMCP.

```text
User
  |
  v
NGOPilot Desktop / CLI
(renamed and tailored goose interface)
  |
  v
NGOPilot Agent Runtime
(existing goose core)
  +- model provider
  +- conversation and session state
  +- planning and tool selection
  +- permissions and confirmations
  +- MCP extension manager
       |
       | MCP over stdio
       v
       NGOPilotMCP
         +- workflow routing and validation
         +- durable jobs and review state
         +- input staging and output artifacts
         +- CareFlow worker
         |    +- paper forms to Excel
         |    +- meeting notes
         |    +- government forms
         +- Roster worker
              +- weekly roster workflow
```

There is one user-facing agent: NGOPilot. The name `goose` may remain in
internal Rust crate names and low-level implementation paths to minimize fork
maintenance, but it should not remain in normal product-facing text.

## 3. Goals and Non-Goals

### 3.1 Goals

- Rename the goose product experience to NGOPilot.
- Tailor the general agent into an NGO operations assistant.
- Enable NGOPilotMCP as a first-party, default extension.
- Make the four NGO workflows easy for non-technical users to start, review,
  continue, and complete.
- Preserve goose's model-provider, session, permission, and extension systems.
- Preserve NGOPilotMCP's existing job, file, review, and algorithm boundaries.
- Make tool routing reliable from both natural-language requests and selected
  files.
- Keep human approval visible before important workflow mutations.
- Produce a maintainable custom distribution that can continue receiving
  upstream goose updates.

### 3.2 Non-goals

- Writing a new agent runtime.
- Wrapping goose with another agent.
- Reimplementing goose orchestration or MCP support.
- Moving the Python algorithms into Rust.
- Rewriting CareFlow or RosterCopiilot.
- Adding a network service between NGOPilot and NGOPilotMCP.
- Designing the MCP installer, Python runtime bundle, wheelhouse, or bootstrap
  process in this plan.
- Exposing the original CareFlow or Roster web applications.
- Changing the four native workflow algorithms.

## 4. Component Ownership

| Component | Owns | Does not own |
|---|---|---|
| NGOPilot UI | product identity, onboarding, chat, file selection, review presentation, artifact actions | algorithm logic or MCP job state |
| goose core under the NGOPilot brand | model calls, sessions, prompts, tool selection, permissions, MCP lifecycle | CareFlow/Roster workflow semantics |
| NGOPilotMCP | tool contracts, file validation, jobs, idempotency, review state, artifacts, worker dispatch | general conversation or model-provider UI |
| CareFlow | extraction, transcription, mapping, document rendering | agent behavior or MCP transport |
| RosterCopiilot | roster scheduling, validation, review export, publication | agent behavior or MCP transport |

This ownership is the main architectural boundary. NGOPilot may guide and
present a workflow, but the MCP must continue to enforce its valid operations
and state transitions.

## 5. NGOPilot Tailoring Strategy

### 5.1 Product identity

Change all normal user-facing surfaces from goose to NGOPilot:

- desktop application name and window title;
- application icons and visual identity;
- onboarding text and settings labels;
- CLI display name, help text, and shell-facing documentation;
- about dialog, support links, update metadata, and artifact names;
- system prompt identity and session language.

Keep internal crate and module names where renaming would create a large,
permanent upstream merge burden without changing user experience.

### 5.2 Agent behavior

Replace the general-purpose default system behavior with an NGOPilot-specific
behavior layer. NGOPilot should:

1. identify the NGO workflow the user is trying to complete;
2. ask only for missing information required by that workflow;
3. distinguish file roles explicitly rather than guessing from extensions;
4. select the matching NGOPilotMCP tool;
5. preserve the returned `job_id` across follow-up turns;
6. present review results in plain operational language;
7. request confirmation before export, publish, or transcript burn;
8. surface the final verified artifact clearly.

The prompt should make the tool routing rules explicit, but MCP schemas and
controllers remain the source of truth. Prompt instructions must not replace
programmatic validation.

### 5.3 Default extension set

NGOPilotMCP is enabled by default and presented as a built-in product
capability, even though it remains a stdio MCP server internally.

The general developer extension should be disabled by default for the NGO user
experience unless it is required for a defined workflow. Other generic goose
extensions should be evaluated individually:

| Extension | Default | Reason |
|---|---|---|
| NGOPilotMCP | enabled | primary product capability |
| Memory | optional | useful for preferences, but needs a privacy decision |
| Developer tools | disabled | not part of normal NGO workflows |
| Computer controller | disabled | broad permissions and no current requirement |
| Tutorial | replace or tailor | generic goose onboarding does not fit NGOPilot |

### 5.4 Workflow entry points

The product should open directly into the working agent, not a marketing page.
The initial task surface can offer four concise workflow entry points:

- Paper forms to Excel
- Meeting notes
- Government forms
- Weekly roster

Selecting one preloads the correct workflow context and file-role controls, but
the same tasks remain available through normal conversation.

## 6. MCP Integration

### 6.1 Goose extension configuration

Use the existing goose `ExtensionConfig::Stdio` path. The conceptual bundled
configuration is:

```json
{
  "id": "ngopilot",
  "name": "ngopilot",
  "description": "CareFlow and roster workflows for NGO operations.",
  "enabled": true,
  "type": "stdio",
  "cmd": "ngopilot-mcp",
  "args": ["serve", "--transport", "stdio"],
  "env_keys": [
    "DEEPSEEK_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "DASHSCOPE_API_KEY"
  ],
  "timeout": 2100,
  "bundled": true
}
```

The final command path is supplied by the deployment environment. NGOPilot does
not need a new MCP client because goose already starts stdio extensions,
discovers their tools, supervises their processes, and routes tool calls.

### 6.2 Exposed tools

NGOPilotMCP continues to expose exactly four stateful tools:

| Tool | Primary inputs | Workflow operations |
|---|---|---|
| `careflow_paper_forms_to_excel` | volunteer-form images | `start`, `status`, `review`, `export` |
| `careflow_meeting_notes` | audio and DOCX template | `start`, `status`, `review`, `export`, `burn` |
| `careflow_government_forms` | elder information and template ID | `list_templates`, `start`, `status`, `review`, `export` |
| `roster_copilot` | HC and escort workbooks plus week | `start`, `status`, `review`, `revalidate`, `export`, `publish`, `get_published` |

The common MCP request shape remains:

```json
{
  "operation": "start",
  "job_id": null,
  "request_id": "optional-stable-idempotency-key",
  "input": {}
}
```

NGOPilot retains the opaque `job_id` in session workflow context and reuses it
for every later operation on the same job.

### 6.3 Tool routing rules

Routing must use semantic roles:

- images of completed volunteer forms go to Paper Forms to Excel;
- audio plus a report template goes to Meeting Notes;
- government forms use a listed template ID, not an arbitrary blank PDF;
- the two roster workbooks are different named roles even though both are Excel
  files.

When the role is ambiguous, NGOPilot asks a short clarification question before
calling a tool.

## 7. User Workflow Architecture

All four workflows follow the same user-facing pattern:

```text
Choose task or describe intent
  -> provide role-labelled input
  -> NGOPilot calls start
  -> show progress/current state
  -> present review data
  -> user confirms or corrects
  -> NGOPilot calls review/revalidate
  -> user confirms delivery action
  -> export/publish/burn as applicable
  -> show verified artifact or final state
```

### 7.1 File intake

The UI should provide file controls appropriate to the selected workflow rather
than one undifferentiated attachment bucket. Each selected file is represented
to the agent with its semantic role and absolute local path.

The MCP remains responsible for allowed roots, symlink rejection, file size,
extension, content signature, archive, and immutable staging checks.

### 7.2 Review

Review is a first-class workflow state, not another chat message. NGOPilot
should render the MCP's structured review result with:

- fields that require confirmation;
- validation warnings and blocked conditions;
- corrections the user can submit;
- valid next operations;
- the job ID in secondary diagnostic detail.

The agent must not claim that a workflow is complete while the MCP reports a
review or blocked state.

### 7.3 Artifacts

Render registered MCP artifacts with filename, kind, media type, size, and
actions to open or reveal the file. Only paths returned in verified MCP artifact
records receive artifact actions; paths mentioned only in model text do not.

## 8. Permissions and Human Control

For the first integration, set the four NGOPilot tools to `AskBefore`. This
works with goose's existing tool-level permission model and ensures that the
tailored agent does not mutate workflow state silently.

A later NGOPilot-specific permission rule may reduce prompts by inspecting the
`operation` argument:

- allow read-only `status`, `list_templates`, and `get_published`;
- ask before `start`, `review`, `revalidate`, and `export`;
- always require one-time confirmation for `publish` and `burn`;
- never allow permanent approval for transcript burn.

The MCP's native review and ready-only publication checks remain required even
when the UI has already asked for confirmation.

## 9. Configuration and Provider Boundaries

NGOPilot uses two provider layers:

1. the goose provider used by the agent for reasoning and conversation;
2. CareFlow's DeepSeek, Azure OpenAI, and DashScope providers used inside native
   workflows.

The onboarding/settings UI must distinguish them. Provider secrets should use
goose's existing secret storage and be passed to the MCP process as environment
values, never as tool arguments.

Production NGOPilot must not silently treat CareFlow mock output as real output.
Mock mode, if retained for demonstrations, must be an explicit visible mode.

## 10. State and Failure Behavior

goose/NGOPilot owns conversation and session history. NGOPilotMCP owns workflow
jobs and artifacts. A chat session may reference an MCP job, but closing or
renaming the chat must not delete that job.

Expected behavior:

- MCP startup failure disables the NGO tools and shows a concise diagnostic;
- a worker failure returns the MCP's normalized error and leaves the durable job
  inspectable;
- retryable mutations reuse a stable `request_id`;
- restarting NGOPilot reconnects to the same MCP state directory;
- a failed export or publication never becomes a reported success;
- tool stderr and logs never enter the MCP stdout protocol stream.

## 11. Security and Privacy

The tailored agent handles NGO documents, elder information, transcripts, and
staff rosters. The architecture must preserve:

- explicit allowed input roots;
- immutable file staging;
- file-content validation;
- owner-only MCP state permissions;
- secret storage outside prompts and tool inputs;
- redaction of secrets and document content from diagnostics;
- explicit human confirmation for publication and transcript destruction;
- disabled product telemetry by default unless a privacy-approved policy says
  otherwise.

The MCP worker should run from a controlled private cwd and must not load an
unrelated `.env` from the user's working directory. This is an integration
hardening item, not a new agent feature.

## 12. Implementation Plan

### Phase 1: Rename goose to NGOPilot

- change user-facing product names, icons, titles, metadata, and help text;
- set a branded config/data root so NGOPilot does not collide with an existing
  goose installation;
- update the main system identity from general goose to NGOPilot;
- keep internal Rust crate names unchanged unless a name is user-visible.

Exit: users launch and interact with NGOPilot without seeing goose branding in
the normal product flow.

### Phase 2: Add NGOPilotMCP as the primary capability

- add NGOPilotMCP to bundled extensions and enable it by default;
- pass required provider configuration through goose's existing secret system;
- verify startup and discovery of exactly four tools;
- disable irrelevant generic extensions by default;
- add an NGOPilot-specific routing/system prompt;
- prove one complete workflow through the NGOPilot conversation.

Exit: NGOPilot starts with the MCP available and reliably selects the correct
tool.

### Phase 3: Tailor the workflow experience

- add the four task entry points;
- add role-specific file selectors;
- retain active `job_id` values in session workflow state;
- render structured review states and corrections;
- render verified artifacts with open/reveal actions;
- add explicit export, publish, and burn confirmations.

Exit: a non-technical NGO user can complete all four workflows without writing
MCP JSON or manually managing file paths and job IDs.

### Phase 4: Verify the tailored product

- run the existing NGOPilotMCP test suite;
- add goose-to-MCP discovery and process lifecycle tests;
- test each workflow through NGOPilot using representative files;
- test ambiguous file roles and clarification behavior;
- test review, failure, retry, restart, export, publish, and burn paths;
- verify that normal product surfaces use NGOPilot branding.

Exit: the renamed and tailored goose product passes all four end-to-end NGO
workflows.

## 13. Expected Code Change Map

```text
harness bone/
  ui/desktop/package.json                         # product name/metadata
  ui/desktop/forge.config.ts                      # desktop identity
  ui/desktop/src/images/                          # NGOPilot icons/assets
  ui/desktop/src/built-in-extensions.json         # visible extension list
  ui/desktop/src/components/settings/extensions/
    bundled-extensions.json                      # NGOPilotMCP enabled by default
  ui/desktop/src/...                             # task, file, review, artifact UI
  crates/goose/src/prompts/system.md              # NGOPilot behavior
  crates/goose/src/agents/prompt_manager.rs       # only if a product prompt layer is needed

NGOPilotMCP/
  src/ngopilot_mcp/shared/workers/client.py       # controlled cwd/env hardening
  tests/integration/                              # goose/MCP contract fixtures as needed
```

The default is to customize product-facing seams and keep the goose core intact.

## 14. Definition of Done

- the product is visibly and behaviorally NGOPilot, not generic goose;
- there is only one user-facing agent runtime;
- NGOPilotMCP is enabled as the primary extension;
- discovery returns exactly the four expected NGO tools;
- the system prompt routes the four workflows by semantic file role;
- irrelevant general-purpose extensions are disabled by default;
- job IDs survive follow-up turns and app restarts;
- review and blocked states are presented accurately;
- export, publish, and burn require explicit user control;
- verified output artifacts are easy to open or reveal;
- provider secrets never enter prompts or tool arguments;
- all four workflows pass end to end through the renamed NGOPilot interface.

## 15. Immediate Next Step

Implement the minimal vertical slice: rename the visible goose product to
NGOPilot, register the existing `ngopilot-mcp` executable as an enabled bundled
stdio extension, add the NGOPilot system behavior, and verify tool discovery
plus one complete workflow. This proves the tailored-product direction without
changing the underlying agent architecture.
