from __future__ import annotations

import pytest

from app.importer.workbook_utils import load_workbook, require_sheet
from fixtures.paths import DIVISION_WORKBOOK_PATH

pytestmark = pytest.mark.skipif(
    not DIVISION_WORKBOOK_PATH.exists(),
    reason=f"real workbook not present: {DIVISION_WORKBOOK_PATH}",
)


@pytest.fixture(scope="module")
def division_workbook():
    return load_workbook(DIVISION_WORKBOOK_PATH)


def test_skills_importer_parses_six_new_staff_profiles(division_workbook):
    from app.importer.skills import parse_skills_sheet

    result = parse_skills_sheet(require_sheet(division_workbook, "新同工跟服務紀錄表"))
    profiles = [r.record for r in result.records if r.record]

    assert result.summary.status == "ok"
    assert result.summary.silently_dropped_cells == 0
    assert len(profiles) == 6
    assert {p["worker_alias"] for p in profiles} == {"業", "翠燕", "志豪", "雯", "添", "嫺"}
    assert sum(len(p["ticks"]) for p in profiles) == result.summary.inferred_count
    assert any("灣仔1" in p["routes"] for p in profiles)
    assert all(p["blank_semantics"] == "unknown" for p in profiles)


def test_transfer_importer_keeps_tbc_rows_as_ambiguities(division_workbook):
    from app.importer.transfers import parse_transfer_log

    result = parse_transfer_log(require_sheet(division_workbook, "個案轉移紀錄_2025"))

    assert result.summary.status == "ok"
    assert result.summary.silently_dropped_cells == 0
    assert result.summary.parsed_count == 9
    codes = {a.code for a in result.ambiguities}
    assert "TRANSFER_TBC" in codes
    assert "TRANSFER_EFFECTIVE_DATE_UNCLEAR" in codes
    assert "FULL_NAME_LEAK" in codes
