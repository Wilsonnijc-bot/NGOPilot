# Current Specification Index

This folder contains the current product, engineering, scheduling, review, and
Excel contracts. See [the documentation map](../README.md) for records, NGO
working documents, future designs, and archived audits.

## Current Product / Engineering Specs

- `PRODUCT_SPEC.md` — user-facing product intent and current demo shape.
- `ENGINEERING_SPEC.md` — implementation boundaries and scheduler-first
  architecture.
- `MASTER_DATA_AND_VALIDATOR_SPEC.md` — Phase 1A implementation spec:
  master data entities, missing-field/gap policy, hard-vs-soft rule map,
  and required validator test cases.
- [`../records/validator_test_matrix.md`](../records/validator_test_matrix.md)
  — living hard/soft/data-gap test coverage record
  with audit-item expectations, current coverage status, and the
  implementation priority order for the coding agent.
- `PROVENANCE_AND_PUBLICATION_SPEC.md` — implemented Phase 1B identity, demand
  conservation, review persistence, exact-cell traceability, and ready-only
  publication contract; NGO evidence gate remains pending.
- `PHASE_1B_ACCEPTANCE_MATRIX.md` — implemented Agent A-E engineering package
  boundaries and automated evidence, distinct from NGO sign-off.
- `api_contract.md` — current demo endpoints plus target production API shape.
- `roadmap.md` — staged path from demo bridge to production scheduler.
- [`../reference/importer_implementation_notes.md`](../reference/importer_implementation_notes.md)
  — support-parser implementation notes.

## Reverse-Engineering Assets

- `excel_semantics.md`
- `data_dictionary.md`
- `rulebook.md`
- `canonical_schema.md`
- `schema.json` — v0.1 conceptual reference, not generated runtime schema
- `rescheduling_algorithm.md`
- `human_review_policy.md`
- `audit_item_schema.json` — v0.1 design reference; runtime model is Pydantic
- `excel_io_contract.md`
- [`../records/fact_check_report_2026-07-01.md`](../records/fact_check_report_2026-07-01.md)

These documents should be reused. Do not re-extract the same rules unless a new
NGO workbook or correction contradicts them.

## NGO Working Documents

- [`../ngo/clarification_packet.md`](../ngo/clarification_packet.md)
- [`../ngo/data_request_templates.md`](../ngo/data_request_templates.md)

## Evaluation, Future, And Historical Material

- [`../evaluation/mock_data_spec.md`](../evaluation/mock_data_spec.md)
- [`../evaluation/evaluation_metrics.md`](../evaluation/evaluation_metrics.md)
- [`../evaluation/PARALLEL_RUN_GUIDE.md`](../evaluation/PARALLEL_RUN_GUIDE.md)
  — executable two-week generated/manual comparison workflow and gate meanings
- [`../future/optimization_model.md`](../future/optimization_model.md) — future
  CP-SAT design, not current runtime behaviour
- [`../future/target_benchmark_cases.json`](../future/target_benchmark_cases.json)
  — aspirational cases, not the executable benchmark suite
- [`../legacy/export_and_review_audit_2026-07-09.md`](../legacy/export_and_review_audit_2026-07-09.md)
  — archived pre-v0.5.0 findings and remediation record

## Removed Historical Files

The old Phase 1 task list, wrap-up report, MVP validation report, broad
technical-spec bundle, and duplicate system-architecture note were removed after
the v0.4.0 weekly roster demo. Their content was either stale or superseded by
the files listed above.
