from __future__ import annotations

from collections import Counter

import pytest

from fixtures.paths import ESCORT_WORKBOOK_PATH

pytestmark = pytest.mark.skipif(
    not ESCORT_WORKBOOK_PATH.exists(),
    reason=f"real workbook not present: {ESCORT_WORKBOOK_PATH}",
)


def test_escort_importer_parses_real_month_sheet():
    from app.importer.escort import parse_workbook

    result = parse_workbook(ESCORT_WORKBOOK_PATH)
    requests = [r.record for r in result.records
                if r.record and r.record["status"] == "requested"]

    assert result.summary.status == "ok"
    assert result.summary.silently_dropped_cells == 0
    assert len(requests) == result.summary.parsed_count == 111
    histogram = Counter((r["service_date"], r["period"]) for r in requests)
    assert sorted(set(histogram.values())) == [1, 2, 3, 4, 5, 6]
    assert sum(1 for r in requests if r["appointment_time"]) / len(requests) >= 0.90
    prefs = {r["row"]: r["preferred_worker_alias"] for r in requests
             if r.get("preferred_worker_alias")}
    assert prefs[23] == "菲菲"
    assert prefs[49] == "嫦"
    assert any(a.code == "MISSING_PERIOD" for a in result.ambiguities)
