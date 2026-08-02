"""Workbook cell-diff harness for no-edit import/export checks."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook

RC_PREFIX = "RC_"


@dataclass(frozen=True, slots=True)
class WorkbookCellDiff:
    sheet: str
    coordinate: str
    field: str
    before: object
    after: object


def _fill(cell) -> str | None:
    fill = cell.fill
    if fill.fill_type is None:
        return None
    color = fill.fgColor
    if color.type == "rgb":
        return str(color.rgb).upper()
    if color.type == "theme":
        return f"theme:{color.theme}:{color.tint}"
    if color.type == "indexed":
        return f"indexed:{color.indexed}"
    return str(color.value) if color.value is not None else None


def compare_workbook_cells(
    original_path: Path,
    exported_path: Path,
    *,
    check_fills: bool = True,
) -> list[WorkbookCellDiff]:
    original = load_workbook(original_path, data_only=False)
    exported = load_workbook(exported_path, data_only=False)
    diffs: list[WorkbookCellDiff] = []
    original_sheets = [s for s in original.sheetnames if not s.startswith(RC_PREFIX)]
    exported_business_sheets = [s for s in exported.sheetnames if not s.startswith(RC_PREFIX)]
    if original_sheets != exported_business_sheets:
        diffs.append(WorkbookCellDiff(
            sheet="__workbook__",
            coordinate="",
            field="sheetnames",
            before=original_sheets,
            after=exported_business_sheets,
        ))
        return diffs

    for sheet_name in original_sheets:
        left = original[sheet_name]
        right = exported[sheet_name]
        if sorted(r.coord for r in left.merged_cells.ranges) != sorted(
                r.coord for r in right.merged_cells.ranges):
            diffs.append(WorkbookCellDiff(
                sheet=sheet_name,
                coordinate="",
                field="merged_ranges",
                before=sorted(r.coord for r in left.merged_cells.ranges),
                after=sorted(r.coord for r in right.merged_cells.ranges),
            ))
        max_row = max(left.max_row, right.max_row)
        max_col = max(left.max_column, right.max_column)
        for row in range(1, max_row + 1):
            for col in range(1, max_col + 1):
                lcell = left.cell(row, col)
                rcell = right.cell(row, col)
                if lcell.value != rcell.value:
                    diffs.append(WorkbookCellDiff(
                        sheet=sheet_name,
                        coordinate=lcell.coordinate,
                        field="value",
                        before=lcell.value,
                        after=rcell.value,
                    ))
                if check_fills and _fill(lcell) != _fill(rcell):
                    diffs.append(WorkbookCellDiff(
                        sheet=sheet_name,
                        coordinate=lcell.coordinate,
                        field="fill",
                        before=_fill(lcell),
                        after=_fill(rcell),
                    ))
    return diffs
