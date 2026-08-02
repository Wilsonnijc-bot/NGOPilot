"""Stable paths to the real Excel workbooks used by importer smoke tests."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS_DIR = REPO_ROOT / "docs"

DIVISION_WORKBOOK_PATH = DOCS_DIR / "照顧員工作分工表2026(HKU).xlsx"
HC_TIMETABLE_WORKBOOK_PATH = DOCS_DIR / "2026_HC 時間表(HKU).xlsx"
ESCORT_WORKBOOK_PATH = DOCS_DIR / "護送個案總表(2026)(HKU).xlsx"

WORKBOOK_PATHS = (
    DIVISION_WORKBOOK_PATH,
    HC_TIMETABLE_WORKBOOK_PATH,
    ESCORT_WORKBOOK_PATH,
)
