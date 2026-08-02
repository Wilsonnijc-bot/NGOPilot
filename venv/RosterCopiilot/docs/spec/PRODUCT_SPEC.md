# RosterCopiilot — Product Specification

**Version:** v0.6.0 stable baseline; Phase 1B engineering implemented and review workflow hardened, NGO validation pending · **Audience:** NGO staff,
product team, non-technical stakeholders.

## 1. What The System Does

每週排班由人手 Excel 變成「系統起草、人手審批、Excel 出表」。

The product goal is automatic roster drafting. The system uses the
reverse-engineered NGO rules to propose who should do what, shows risky or
uncertain choices for human review, then exports a familiar division workbook
for staff.

The system does **not** publish or distribute by itself. A named person must
finish review and explicitly publish an exact server-validated `ready` version.

## 2. What The Excel Files Mean

The sample Excel workbooks are evidence and fixtures:

| Workbook | Product role |
|---|---|
| `照顧員工作分工表2026(HKU).xlsx` | final staff-facing output format, current roster sample, slot geometry and colour vocabulary |
| `2026_HC 時間表(HKU).xlsx` | evidence for HC week-pattern rules and monthly service expansion |
| `護送個案總表(2026)(HKU).xlsx` | evidence for floating escort demand, appointment fields, and remark-based preferences |
| skill / transfer sheets | evidence for route skills, worker capability hints, and effective-dated changes |

They are not meant to define a long-term workflow where the NGO must upload
three separate workbooks every week.

Current demo shape: the division workbook is built into the system as the fixed
base and output template; the user uploads the HC timetable and escort workbook
for the target week, adds temporary changes, and downloads a generated division
workbook draft.

## 3. Real Product Inputs

| Input | Meaning |
|---|---|
| Roster rule set | reverse-engineered from `rulebook.md`, `excel_semantics.md`, and `data_dictionary.md` |
| Worker data | aliases, skills, routes, team/centre, availability, leave |
| Elder/service demand | fixed services, HC patterns, escort appointments, cancellations |
| Weekly changes | leave, hospitalisation, extra/cancelled escort, service cancellation |
| Config | centre duty counts, priority order, session definitions, Saturday A/B rules |
| Human decisions | approve/edit/reject, manual overrides, confirmed ambiguity resolutions |

## 4. Real Product Outputs

| Output | Meaning |
|---|---|
| Draft total roster | system-generated schedule version with entries, metrics, and review items |
| Review queue | blocking/warning/info items ordered for the roster owner |
| Final division workbook | `照顧員工作分工表`-style workbook showing staff daily duties |
| Change summary | what changed and why, tied to audit decisions |
| Unassigned list | tasks the system could not safely place |

## 5. What Is Automated

- Expand fixed services and HC week patterns into dated tasks.
- Allocate escort demand into worker half-day capacity.
- Fill centre duty and logistics tasks according to priority.
- Respect hard constraints: no double-booking, skill gates, gender-sensitive
  services, exclusive bindings, leave, Saturday availability.
- Repair the roster after changes with minimal churn.
- Explain each suggestion through rules and source assumptions.

## 6. What Still Requires A Human

| Situation | Why |
|---|---|
| exclusive-worker absence | relationship-sensitive service; the NGO decides communication and cancellation |
| unassigned task | requires operational trade-off |
| duty shortfall | high-priority centre risk |
| displacement chain | multiple staff/tasks affected |
| unknown gender/skill/route | the system must not guess |
| replacement suggestion | human approval remains part of the workflow |

## 7. Current Implementation Caveat

Version 0.4.0 established the demo bridge for the real NGO story. Version 0.5.0
is the stable release baseline. The current Phase 1B implementation adds
end-to-end provenance, durable weekly review, independent validator/preflight,
ready-only final publication, and a two-week comparison harness around that
baseline:

```text
built-in division workbook base/template
    + uploaded HC timetable
    + uploaded escort workbook
    + temporary changes
    -> generated division workbook review draft
    -> approve/edit/reject + revalidate
    -> explicit final publication only when ready
```

This is enough to demonstrate input-driven roster drafting, traceable review,
and the technical publication safety boundary. It is not evidence of staff
readiness. The next operational step is NGO-confirmed worker, elder, skill,
route, availability, and rule data followed by two NGO-selected,
roster-owner-signed parallel weeks with zero uncategorized or blocking
differences.

## 8. Success Measures

- weekly roster admin time reduced;
- hard-rule violations always zero;
- most suggestions approved unchanged during parallel runs;
- every changed cell has an explanation;
- unresolved data gaps are visible, not hidden.
