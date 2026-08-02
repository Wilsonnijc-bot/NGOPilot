"""Smoke tests for the Excel importer scaffold."""
from app.importer import division, escort, hc_timetable, skills, transfers
from app.importer.resolve import resolve_import_batch
from app.importer.workbook_utils import (
    effective_used_range,
    load_workbook,
    merged_cell_range,
    read_cell_value,
    read_fill_color,
    require_sheet,
    resolve_merged_cell,
)
from fixtures.paths import (
    DIVISION_WORKBOOK_PATH,
    ESCORT_WORKBOOK_PATH,
    HC_TIMETABLE_WORKBOOK_PATH,
    WORKBOOK_PATHS,
)


def test_real_workbook_files_exist():
    for path in WORKBOOK_PATHS:
        assert path.exists(), path
        assert path.stat().st_size > 0


def test_workbook_utils_can_open_each_real_workbook():
    workbooks = [load_workbook(path) for path in WORKBOOK_PATHS]

    assert workbooks[0].sheetnames == [
        "恆常服務",
        "個案轉移紀錄_2025",
        "新同工跟服務紀錄表",
    ]
    assert workbooks[1].sheetnames == ["52026"]
    assert workbooks[2].sheetnames == ["1月"]


def test_regular_services_sheet_loads_with_reasonable_effective_range():
    workbook = load_workbook(DIVISION_WORKBOOK_PATH)
    worksheet = require_sheet(workbook, "恆常服務")

    used_range = effective_used_range(worksheet)

    assert worksheet.max_row > used_range.max_row
    assert used_range.min_row == 1
    assert used_range.min_column == 1
    assert used_range.max_row == 113
    assert used_range.max_column == 53
    assert used_range.max_column_letter == "BA"
    assert used_range.value_count > 1800


def test_other_workbooks_have_reasonable_effective_ranges():
    hc_workbook = load_workbook(HC_TIMETABLE_WORKBOOK_PATH)
    hc_range = effective_used_range(require_sheet(hc_workbook, "52026"))
    assert hc_range.max_row == 28
    assert hc_range.max_column == 35
    assert hc_range.value_count > 300

    escort_workbook = load_workbook(ESCORT_WORKBOOK_PATH)
    escort_range = effective_used_range(require_sheet(escort_workbook, "1月"))
    assert escort_range.max_row == 151
    assert escort_range.max_column == 13
    assert escort_range.value_count > 1000


def test_merged_cell_helper_resolves_known_division_weekday_block():
    workbook = load_workbook(DIVISION_WORKBOOK_PATH)
    worksheet = require_sheet(workbook, "恆常服務")

    cell_range = merged_cell_range(worksheet, "A4")
    resolved = resolve_merged_cell(worksheet, "A4")

    assert cell_range is not None
    assert cell_range.coord == "A3:A19"
    assert resolved.coordinate == "A3"
    assert read_cell_value(worksheet, "A4") == "一"


def test_fill_color_helper_returns_stable_argb_for_colored_cells():
    division_workbook = load_workbook(DIVISION_WORKBOOK_PATH)
    regular_services = require_sheet(division_workbook, "恆常服務")
    assert read_fill_color(regular_services["D12"]) == "FFF4CCCC"
    assert read_fill_color(regular_services["C3"]) == "FFFFE599"

    hc_workbook = load_workbook(HC_TIMETABLE_WORKBOOK_PATH)
    hc_sheet = require_sheet(hc_workbook, "52026")
    assert read_fill_color(hc_sheet["F4"]) == "FFFFE599"

    escort_workbook = load_workbook(ESCORT_WORKBOOK_PATH)
    escort_sheet = require_sheet(escort_workbook, "1月")
    assert read_fill_color(escort_sheet["J3"]) == "FFFFFF00"


def test_division_parser_is_implemented():
    """Division graduated from stub to real parser (test_division_importer.py
    holds the golden assertions; this is the wiring check)."""
    result = division.parse_division_workbook(DIVISION_WORKBOOK_PATH)
    assert result.summary["status"] == "ok"
    assert result.summary["silently_dropped_cells"] == 0
    assert result.summary["worker_count"] == 46


def test_remaining_importers_are_implemented_with_structured_results():
    division_workbook = load_workbook(DIVISION_WORKBOOK_PATH)
    transfer_sheet = require_sheet(division_workbook, "個案轉移紀錄_2025")
    skills_sheet = require_sheet(division_workbook, "新同工跟服務紀錄表")

    hc_workbook = load_workbook(HC_TIMETABLE_WORKBOOK_PATH)
    hc_sheet = require_sheet(hc_workbook, "52026")

    escort_workbook = load_workbook(ESCORT_WORKBOOK_PATH)
    escort_sheet = require_sheet(escort_workbook, "1月")

    results = [
        transfers.parse_transfer_log(transfer_sheet),
        skills.parse_skills_sheet(skills_sheet),
        hc_timetable.parse_workbook(HC_TIMETABLE_WORKBOOK_PATH),
        hc_timetable.parse_month_sheet(hc_sheet),
        escort.parse_workbook(ESCORT_WORKBOOK_PATH),
        escort.parse_month_sheet(escort_sheet),
    ]
    results.append(resolve_import_batch(*results))

    for result in results:
        assert result.summary.status in {"ok", "empty"}
        assert result.summary.parser_name
        assert result.summary.doc_ref
        assert result.summary.silently_dropped_cells == 0
        assert result.implemented
