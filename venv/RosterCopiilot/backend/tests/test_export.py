"""Excel export smoke tests."""
import openpyxl

from app.services.excel_export import build_workbook, save_workbook
from app.services.state import AppState

EXPECTED_SHEETS = ["總排班", "護送時間表", "人工審核", "未分配", "變更影響"]


def test_workbook_has_five_sheets_and_frozen_headers(dataset, baseline):
    wb = build_workbook(dataset, baseline)
    assert wb.sheetnames == EXPECTED_SHEETS
    assert wb["總排班"].freeze_panes == "C3"
    for name in EXPECTED_SHEETS[1:]:
        assert wb[name].freeze_panes == "A2"


def test_workbook_round_trips_through_openpyxl(tmp_path):
    st = AppState()
    version, reports = st.apply(st.example_events())
    path = save_workbook(st.dataset, version, reports, output_dir=tmp_path)
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == EXPECTED_SHEETS
    # master sheet: one row per (day, period) = 12 + 2 header rows
    assert wb["總排班"].max_row == 14
    # review sheet lists every audit item
    assert wb["人工審核"].max_row == len(version.audit_items) + 1
    # impact sheet mentions the trigger events
    impact_text = "\n".join(str(c.value) for row in wb["變更影響"].iter_rows()
                            for c in row if c.value)
    assert "leave" in impact_text and "指標摘要" in impact_text


def test_unassigned_sheet_carries_structured_reasons(dataset, baseline, tmp_path):
    path = save_workbook(dataset, baseline, output_dir=tmp_path)
    ws = openpyxl.load_workbook(path)["未分配"]
    assert ws.max_row >= 2
    reasons_col = [ws.cell(r, 6).value for r in range(2, ws.max_row + 1)]
    assert all(v and "[" in v for v in reasons_col), "reason codes must be visible"
