from __future__ import annotations

import pytest

from fixtures.paths import HC_TIMETABLE_WORKBOOK_PATH

pytestmark = pytest.mark.skipif(
    not HC_TIMETABLE_WORKBOOK_PATH.exists(),
    reason=f"real workbook not present: {HC_TIMETABLE_WORKBOOK_PATH}",
)


def test_hc_importer_recovers_excel_date_corrupted_week_patterns():
    from app.importer.hc_timetable import parse_workbook

    result = parse_workbook(HC_TIMETABLE_WORKBOOK_PATH)
    mangled = [a for a in result.ambiguities
               if a.code == "MANGLED_WEEK_PATTERN_DATE"]

    assert result.summary.status == "ok"
    assert result.summary.silently_dropped_cells == 0
    assert result.summary.parsed_count >= 50
    assert len(mangled) == 6
    recovered = [r.record for r in result.records
                 if r.record and r.record.get("week_pattern_raw") == "1,5"]
    assert len(recovered) >= 6
    assert any(r["section"] == "other_service" for r in recovered)
