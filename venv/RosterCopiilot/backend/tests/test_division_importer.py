"""Golden tests: division importer vs the real 照顧員工作分工表2026(HKU).xlsx.

These assert the structural facts recorded in
docs/records/fact_check_report_2026-07-01.md
(E1, E4, E5) directly against the actual workbook, so a spec/file drift breaks
loudly here first.
"""
from __future__ import annotations

import json

import pytest

from fixtures.paths import DIVISION_WORKBOOK_PATH

pytestmark = pytest.mark.skipif(
    not DIVISION_WORKBOOK_PATH.exists(),
    reason=f"real workbook not present: {DIVISION_WORKBOOK_PATH}",
)

LATE_WORKERS = ["志豪", "香", "秀英", "娥", "嘉文", "熙仔", "梅欽", "奕倫", "炎萍"]


@pytest.fixture(scope="module")
def result():
    from app.importer import parse_division_workbook

    return parse_division_workbook(DIVISION_WORKBOOK_PATH)


# ---------------------------------------------------------------- workbook
def test_workbook_opens_and_sheet_found(result):
    assert result.sheet_name == "恆常服務"
    assert result.workbook_path.endswith("照顧員工作分工表2026(HKU).xlsx")


def test_effective_range_ignores_inflated_max_row(result):
    assert result.declared_max_row == 981          # what openpyxl claims
    assert 110 <= result.used_range["max_row"] <= 115  # what is actually there
    assert result.used_range["max_column"] == 53   # BA


# ----------------------------------------------------------------- headers
def test_exactly_46_worker_columns(result):
    assert len(result.workers) == 46


def test_gap_columns_g_and_aq(result):
    assert result.gap_columns == ("G", "AQ")


def test_counter_columns_are_not_workers(result):
    assert result.counter_columns == ("AY", "AZ", "BA")
    worker_letters = {w.column_letter for w in result.workers}
    assert not worker_letters & {"AY", "AZ", "BA"}


def test_late_worker_columns_detected(result):
    """The 9 workers missed by the original 37-column extraction (E1)."""
    names = {w.display_name for w in result.workers}
    for name in LATE_WORKERS:
        assert name in names, f"missing late-column worker {name}"
    by_name = {w.display_name: w for w in result.workers}
    assert "MRC" in by_name["熙仔"].tags
    assert "PT" in by_name["梅欽"].tags


def test_header_fill_status_is_inferred_not_asserted(result):
    by_name = {w.display_name: w for w in result.workers}
    # gray transition columns (excel_semantics.md): inferred only
    for name in ("文健", "添", "健忠", "安妮"):
        assert by_name[name].status_inferred == "departed_inferred"
    assert by_name["娥"].status_inferred == "active"
    # every worker keeps the raw header + fill for later human review
    assert all(w.raw_header for w in result.workers)


def test_working_hours_parsed_from_hours_row(result):
    assert result.summary["hours_row"] == 108
    by_name = {w.display_name: w for w in result.workers}
    assert by_name["家偉"].work_start == "08:30"
    assert by_name["家偉"].work_end == "17:30"
    assert by_name["輝"].work_hours_raw == "9:00-17:00"


# ------------------------------------------------------------------ blocks
def test_weekday_and_period_blocks_detected(result):
    assert len(result.weekday_blocks) == 6
    assert [b.weekday for b in result.weekday_blocks] == [1, 2, 3, 4, 5, 6]
    sat = result.weekday_blocks[-1]
    assert "更新版" in sat.label_raw
    for block in result.weekday_blocks:
        assert [p.period for p in block.periods] == ["AM", "PM"]
        for p in block.periods:
            assert len(p.assignment_rows) == 2  # two session slots per half-day
            assert len(p.detail_rows) == 2


def test_saturday_team_row_structured(result):
    assert result.summary["saturday_row"] == 93
    teams = {w.display_name: w.saturday_team for w in result.workers
             if w.saturday_team}
    assert teams["志豪"] == "A"
    assert teams["娥"] == "B"
    # appended names are preserved raw and flagged, not interpreted
    with_names = [w for w in result.workers if w.saturday_names_raw]
    assert with_names
    assert any(a.code == "SATURDAY_NAMES_UNCONFIRMED" for a in result.ambiguities)


# ------------------------------------------------------------- assignments
def test_assignments_are_produced_in_volume(result):
    assert result.summary["assignment_count"] > 900
    kinds = {a.kind for a in result.assignments}
    assert {"field_service", "center_duty", "escort_slot", "meal",
            "kitchen", "off"} <= kinds


def test_known_assignment_cell_parses_exactly(result):
    """Golden cell H3: `E+RO:Y容(EH)` with detail `8:30-10:00(柴灣)Tiffany`."""
    a = next(x for x in result.assignments if x.cell.coordinate == "H3")
    assert a.kind == "field_service"
    assert a.service_code_raw == "E+RO"
    assert a.service_code == "E+RO"
    assert a.elder_alias == "Y容"
    assert a.unit == "EH"
    assert a.weekday == 1 and a.period == "AM" and a.session_index == 1
    assert a.detail is not None
    assert a.detail.start_time == "08:30" and a.detail.end_time == "10:00"
    assert a.detail.district == "柴灣"
    assert a.detail.trailing_label == "Tiffany"  # case-manager *candidate*


def test_stacked_alternating_week_case_not_collapsed(result):
    """Fact-check E5: 炎萍 Mon AM slot holds HC week-1 AND week-3 cases."""
    ax_mon_am = [a for a in result.assignments
                 if a.worker_alias == "炎萍" and a.weekday == 1
                 and a.period == "AM" and a.session_index == 1
                 and a.kind == "field_service"]
    assert len(ax_mon_am) >= 2, "stacked cases must stay separate records"
    stacked = [a for a in ax_mon_am if a.stacked]
    assert stacked, "the detail-row case must be marked stacked"
    patterns = {a.week_pattern_weeks for a in ax_mon_am}
    assert len(patterns) >= 2, "stacked cases carry different week patterns"


def test_week_pattern_suffixes_parsed(result):
    pats = {c.week_pattern_raw: c.week_pattern_weeks
            for c in result.fixed_service_candidates if c.week_pattern_raw}
    assert pats, "week-pattern suffixes must be captured"
    assert (1, 3) in pats.values()
    assert (2, 4) in pats.values()
    # 長周 is NOT interpreted — raw kept, weeks None, ambiguity raised
    unknown = [raw for raw, weeks in pats.items()
               if "長周" in raw and weeks is None]
    assert unknown
    assert any(a.code == "UNKNOWN_WEEK_PATTERN" for a in result.ambiguities)


def test_escort_slots_and_duty_cells_recognised(result):
    esc = [a for a in result.assignments if a.kind == "escort_slot"]
    assert len(esc) >= 40                       # yellow ESC reservations
    mon_am_s1 = [a for a in esc if a.weekday == 1 and a.period == "AM"
                 and a.session_index == 1]
    assert len(mon_am_s1) == 4                  # the "baseline 4" morning
    duty = [a for a in result.assignments if a.kind == "center_duty"]
    assert {a.duty_center for a in duty} == {"AMC", "MRC", "GC"}


# ------------------------------------------------------- candidates mapping
def test_fixed_service_candidates_map_toward_domain(result):
    cands = result.fixed_service_candidates
    assert len(cands) > 300
    for c in cands[:50]:
        assert 1 <= c.weekday <= 6
        assert c.period in ("AM", "PM")
        assert c.worker_alias
        assert c.source_ref.startswith("恆常服務!")
    # canonical codes only where clean; unclear codes stay raw with None
    canon = {c.service_code for c in cands}
    assert canon <= {"E+RO", "HC", "PC", "B", "ESC", None}
    # no invented data: importer result carries no gender/skills fields at all
    assert not hasattr(cands[0], "gender")
    assert not hasattr(cands[0], "skills")


# ---------------------------------------------------------------- counters
def test_counters_parsed_and_reconciled(result):
    assert len(result.counters) == 24  # 6 days x 2 periods x 2 sessions
    mon_s1 = next(c for c in result.counters
                  if c.weekday == 1 and c.period == "AM" and c.session_index == 1)
    assert mon_s1.ero_expected == 14
    assert mon_s1.other_label == "Esc"
    assert mon_s1.other_expected == 4
    assert mon_s1.total_expected == 18
    assert mon_s1.ero_counted == 14 and mon_s1.esc_counted == 4
    # the whole sheet reconciles — importer grammar matches the NGO's own tally
    assert result.summary["counter_mismatch_count"] == 0


# -------------------------------------------------------------- ambiguities
def test_unparsed_cells_become_ambiguities(result):
    codes = {a.code for a in result.ambiguities}
    assert "BARE_NAME" in codes                # T3 `嘉偉`
    assert "INCOMPLETE_ASSIGNMENT" in codes    # H57 `HC:` (cyan cell)
    assert "CELL_COMMENT" in codes             # F48 comment `6/3 開始改時間`
    for a in result.ambiguities:
        assert a.message
        assert a.source is not None and a.source.cell is not None


def test_zero_silently_dropped_cells(result):
    s = result.summary
    assert s["silently_dropped_cells"] == 0
    assert s["nonempty_cells"] == s["classified_cells"]
    assert s["status"] == "ok"
    # reconciliation is structural: every non-empty cell appears in raw_cells
    assert len(result.raw_cells) == s["nonempty_cells"]


def test_result_is_json_serializable(result):
    payload = json.dumps(result.to_json_dict(), ensure_ascii=False)
    assert "恆常服務" in payload
    round_tripped = json.loads(payload)
    assert round_tripped["summary"]["worker_count"] == 46
