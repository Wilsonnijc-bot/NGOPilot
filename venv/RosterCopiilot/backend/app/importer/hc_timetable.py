"""Importer for the HC timetable workbook (2026_HC 時間表)."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any

from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from .base import ImportResult
from .models import CellRef, ImportAmbiguity, ImportBatchSummary, ParsedRecord, SourceRef
from .workbook_utils import load_workbook, require_sheet

DOC_REF = "docs/spec/excel_semantics.md §2; docs/spec/excel_io_contract.md §1"
MONTH_SHEET = "52026"
BLOCK_STARTS = (1, 8, 15, 22, 29)
DAY_MAP = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}
PERIOD_MAP = {"上": "AM", "下": "PM"}


def _normalize(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = unicodedata.normalize("NFKC", str(value))
    text = text.replace("：", ":").replace("（", "(").replace("）", ")")
    return re.sub(r"\s+", " ", text).strip()


def _source(path: Path | None, ws: Worksheet, row: int, col: int,
            value: object = None) -> SourceRef:
    return SourceRef(
        workbook_path=path,
        sheet_name=ws.title,
        cell=CellRef(sheet_name=ws.title, row=row, column=col),
        raw_value=value,
        doc_ref=DOC_REF,
    )


def _date_iso(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return None


def _parse_time_slot(raw: str) -> tuple[int | None, str | None]:
    text = _normalize(raw)
    if len(text) < 2:
        return None, None
    return DAY_MAP.get(text[0]), PERIOD_MAP.get(text[1])


def _week_pattern(
    value: object,
    *,
    worksheet: Worksheet,
    workbook_path: Path | None,
    row: int,
    col: int,
    ambiguities: list[ImportAmbiguity],
) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        # The real workbook has six cells where "1,5" was interpreted by Excel
        # as a date. Preserve the recovery as an ambiguity, not a silent fix.
        if (value.month, value.day) == (1, 5):
            ambiguities.append(ImportAmbiguity(
                code="MANGLED_WEEK_PATTERN_DATE",
                message="節數 cell was stored as an Excel date; recovered as '1,5'",
                source=_source(workbook_path, worksheet, row, col, value),
                severity="warning",
                raw_value=value.isoformat(),
                resolution_hint="confirm that this means weeks 1 and 5",
            ))
            return "1,5"
        ambiguities.append(ImportAmbiguity(
            code="UNPARSED_WEEK_PATTERN_DATE",
            message="節數 cell is an unexpected date value",
            source=_source(workbook_path, worksheet, row, col, value),
            severity="blocking",
            raw_value=value.isoformat(),
        ))
        return None
    return _normalize(value)


def parse_workbook(workbook: Workbook | Path) -> ImportResult[dict[str, Any]]:
    workbook_path = workbook if isinstance(workbook, Path) else None
    wb = load_workbook(workbook_path, data_only=False) if workbook_path else workbook
    return parse_month_sheet(require_sheet(wb, MONTH_SHEET), workbook_path=workbook_path)


def parse_month_sheet(
    worksheet: Worksheet,
    *,
    workbook_path: Path | None = None,
) -> ImportResult[dict[str, Any]]:
    records: list[ParsedRecord[dict[str, Any]]] = []
    ambiguities: list[ImportAmbiguity] = []
    inferred = 0

    for block_idx, start_col in enumerate(BLOCK_STARTS, start=1):
        header = [_normalize(worksheet.cell(3, start_col + i).value) for i in range(7)]
        if header[:6] != ["Case", "單位", "節數", "時間", "照顧員", "日期"]:
            ambiguities.append(ImportAmbiguity(
                code="HC_BLOCK_HEADER_UNEXPECTED",
                message=f"Week {block_idx} header is not the expected 7-column shape",
                source=_source(workbook_path, worksheet, 3, start_col,
                               worksheet.cell(3, start_col).value),
                severity="blocking",
                raw_value=" | ".join(header),
            ))
            continue

        section = "hc"
        for row in range(4, worksheet.max_row + 1):
            values = [worksheet.cell(row, start_col + i).value for i in range(7)]
            if not any(v not in (None, "") for v in values):
                continue
            case_raw = _normalize(values[0])
            if case_raw == "其他服務":
                section = "other_service"
                records.append(ParsedRecord(
                    record={
                        "source": "hc_timetable",
                        "source_ref": f"{worksheet.title}!{worksheet.cell(row, start_col).coordinate}",
                        "week": block_idx,
                        "section": "section_marker",
                        "label": case_raw,
                    },
                    source=_source(workbook_path, worksheet, row, start_col, values[0]),
                    raw={str(i): values[i] for i in range(7)},
                    parse_confidence="high",
                ))
                continue
            if not case_raw:
                ambiguities.append(ImportAmbiguity(
                    code="ORPHAN_HC_CELL",
                    message=f"Week {block_idx} row {row} has values but no case name",
                    source=_source(workbook_path, worksheet, row, start_col,
                                   values[0]),
                    severity="warning",
                    raw_value=" | ".join(_normalize(v) for v in values if _normalize(v)),
                ))
                continue
            if case_raw.startswith("**"):
                ambiguities.append(ImportAmbiguity(
                    code="HC_FREE_TEXT_NOTE",
                    message="free-text HC note needs human interpretation",
                    source=_source(workbook_path, worksheet, row, start_col, values[0]),
                    severity="warning",
                    raw_value=case_raw,
                ))
                continue

            pattern = _week_pattern(
                values[2], worksheet=worksheet, workbook_path=workbook_path,
                row=row, col=start_col + 2, ambiguities=ambiguities)
            if pattern == "1,5":
                inferred += 1
            weekday, period = _parse_time_slot(_normalize(values[3]))
            if weekday is None or period is None:
                ambiguities.append(ImportAmbiguity(
                    code="HC_TIME_SLOT_UNPARSED",
                    message="HC time slot does not match weekday+AM/PM grammar",
                    source=_source(workbook_path, worksheet, row, start_col + 3,
                                   values[3]),
                    severity="warning",
                    raw_value=_normalize(values[3]),
                ))
            service_code_raw = "HC"
            elder_alias = case_raw
            service_match = re.match(r"^(PC|B|Esc)\s*[:：]\s*(.+)$", case_raw,
                                     flags=re.IGNORECASE)
            if service_match:
                service_code_raw = service_match.group(1).upper()
                if service_code_raw == "ESC":
                    service_code_raw = "Esc"
                elder_alias = _normalize(service_match.group(2))
            service_date = _date_iso(values[5])
            if service_date is None:
                ambiguities.append(ImportAmbiguity(
                    code="HC_DATE_MISSING",
                    message="HC row has no concrete date; keep as template enrichment",
                    source=_source(workbook_path, worksheet, row, start_col + 5,
                                   values[5]),
                    severity="info",
                    raw_value=_normalize(values[5]),
                ))
            record = {
                "source": "hc_timetable",
                "source_ref": f"{worksheet.title}!{worksheet.cell(row, start_col).coordinate}",
                "week": block_idx,
                "section": section,
                "service_code_raw": service_code_raw,
                "elder_alias": elder_alias,
                "case_raw": case_raw,
                "unit": _normalize(values[1]) or None,
                "week_pattern_raw": pattern,
                "time_slot_raw": _normalize(values[3]) or None,
                "weekday": weekday,
                "period": period,
                "worker_alias": _normalize(values[4]) or None,
                "service_date": service_date,
                "date_raw": _normalize(values[5]) or None,
                "change_raw": _normalize(values[6]) or None,
            }
            records.append(ParsedRecord(
                record=record,
                source=_source(workbook_path, worksheet, row, start_col, values[0]),
                raw={str(i): values[i] for i in range(7)},
                parse_confidence="high" if weekday and period else "medium",
            ))

    summary = ImportBatchSummary(
        parser_name="hc_timetable_workbook",
        status="ok",
        parsed_count=sum(1 for r in records
                         if r.record and r.record.get("section") != "section_marker"),
        inferred_count=inferred,
        flagged_count=len(ambiguities),
        silently_dropped_cells=0,
        notes=(f"recovered {inferred} Excel-date-mangled 節數 cells",),
        doc_ref=DOC_REF,
    )
    return ImportResult(
        summary=summary,
        records=tuple(records),
        ambiguities=tuple(ambiguities),
        source_workbook=workbook_path,
    )
