# Importer Implementation Notes

**Reference status:** current support-tooling notes; not a product specification.
Importers are support tooling for reverse-engineering
evidence, fixtures, and regression checks. They are not the product's normal
weekly input path.

## Current Implementation

`backend/app/importer/` contains parsers for the sample workbook families:

- `division.py`: `照顧員工作分工表2026(HKU).xlsx`, especially `恆常服務`.
- `transfers.py`: `個案轉移紀錄_*` sheets inside the division workbook.
- `skills.py`: `新同工跟服務紀錄表` inside the division workbook.
- `hc_timetable.py`: monthly HC timetable sheets such as `52026`.
- `escort.py`: monthly escort master sheets such as `1月`.
- `resolve.py`: conservative alias resolution and ambiguity generation.

Shared infrastructure:

- `base.py`: importer interfaces plus `ImportResult`.
- `models.py`: source refs, cell refs, ambiguity records, batch summaries, parsed records.
- `errors.py`: typed workbook/import errors.
- `workbook_utils.py`: openpyxl helpers.
- `serialization.py`: JSON-friendly conversion for parser outputs.
- `promotion.py`: conservative preview of parsed records, not live scheduler
  promotion.

## Fixture Expectations

Current sample expectations:

- division fixture: 46 worker columns, 370 fixed-service candidates, 0 silent drops;
- escort fixture: 111 schedulable requests, one blocking ambiguity for a missing
  period row;
- HC fixture: 57 parsed records and 6 Excel-date-mangled week-pattern cells
  recovered and flagged;
- skills fixture: 6 new-staff profiles;
- transfer fixture: 9 rows, TBC/effective-date/full-name issues as ambiguities.

## How To Use The Importers

Use them to:

- verify the strong-agent reverse-engineering documents against the samples;
- create golden tests and source-cell evidence;
- detect workbook pathologies;
- protect the division workbook exporter from accidental format drift.

Do not use them as the required runtime path for scheduling. The scheduler
should consume a `SchedulerSnapshot` or equivalent domain/config object.

## Mapping Into `app.domain`

Parsed records may inform canonical scheduler data, but only after source-of-
truth and ambiguity decisions are made. Keep source refs, raw values, confidence,
and ambiguity details attached so the scheduler never has to guess where a fact
came from.
