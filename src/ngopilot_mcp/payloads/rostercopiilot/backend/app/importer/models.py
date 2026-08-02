"""Lightweight importer data models.

These models describe what was seen in Excel before it is promoted into the
canonical ``app.domain`` objects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Generic, Literal, Mapping, TypeVar

from openpyxl.cell.cell import Cell, MergedCell
from openpyxl.utils import get_column_letter

if TYPE_CHECKING:
    from app.domain import (
        CenterDutyRequirement,
        Elder,
        Employee,
        EscortRequest,
        FixedService,
    )

Confidence = Literal["high", "medium", "low", "unknown"]
ImportStatus = Literal["empty", "not_implemented", "ok", "partial"]
Severity = Literal["info", "warning", "blocking"]
RecordT = TypeVar("RecordT")


@dataclass(frozen=True, slots=True)
class CellRef:
    sheet_name: str
    row: int
    column: int

    @classmethod
    def from_cell(cls, cell: Cell | MergedCell) -> "CellRef":
        return cls(sheet_name=cell.parent.title, row=cell.row, column=cell.column)

    @property
    def coordinate(self) -> str:
        return f"{get_column_letter(self.column)}{self.row}"

    @property
    def label(self) -> str:
        return f"{self.sheet_name}!{self.coordinate}"


@dataclass(frozen=True, slots=True)
class SourceRef:
    workbook_path: Path | None = None
    sheet_name: str | None = None
    cell: CellRef | None = None
    range_ref: str | None = None
    raw_value: object | None = None
    doc_ref: str | None = None

    @property
    def label(self) -> str:
        parts: list[str] = []
        if self.workbook_path is not None:
            parts.append(str(self.workbook_path))
        if self.cell is not None:
            parts.append(self.cell.label)
        elif self.sheet_name and self.range_ref:
            parts.append(f"{self.sheet_name}!{self.range_ref}")
        elif self.sheet_name:
            parts.append(self.sheet_name)
        if self.doc_ref:
            parts.append(self.doc_ref)
        return " :: ".join(parts)


@dataclass(frozen=True, slots=True)
class ImportAmbiguity:
    code: str
    message: str
    source: SourceRef | None = None
    severity: Severity = "warning"
    candidates: tuple[str, ...] = ()
    raw_value: str | None = None
    resolution_hint: str | None = None

    @property
    def blocking(self) -> bool:
        return self.severity == "blocking"


@dataclass(frozen=True, slots=True)
class ImportBatchSummary:
    parser_name: str
    status: ImportStatus
    parsed_count: int = 0
    inferred_count: int = 0
    flagged_count: int = 0
    ignored_sheets: tuple[str, ...] = ()
    silently_dropped_cells: int = 0
    notes: tuple[str, ...] = ()
    doc_ref: str | None = None

    @classmethod
    def empty(
        cls,
        *,
        parser_name: str,
        ignored_sheets: tuple[str, ...] = (),
        notes: tuple[str, ...] = (),
    ) -> "ImportBatchSummary":
        return cls(
            parser_name=parser_name,
            status="empty",
            ignored_sheets=ignored_sheets,
            notes=notes,
        )

    @classmethod
    def not_implemented(
        cls,
        *,
        parser_name: str,
        doc_ref: str | None = None,
        notes: tuple[str, ...] = (),
    ) -> "ImportBatchSummary":
        default_note = "Parser scaffold exists; core Excel parsing is not implemented yet."
        return cls(
            parser_name=parser_name,
            status="not_implemented",
            notes=(default_note, *notes),
            doc_ref=doc_ref,
        )


@dataclass(frozen=True, slots=True)
class ParsedRecord(Generic[RecordT]):
    record: RecordT | None
    source: SourceRef
    raw: Mapping[str, object] = field(default_factory=dict)
    parse_confidence: Confidence = "unknown"
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ParsedEmployee(ParsedRecord["Employee"]):
    pass


@dataclass(frozen=True, slots=True)
class ParsedElder(ParsedRecord["Elder"]):
    pass


@dataclass(frozen=True, slots=True)
class ParsedFixedService(ParsedRecord["FixedService"]):
    pass


@dataclass(frozen=True, slots=True)
class ParsedEscortRequest(ParsedRecord["EscortRequest"]):
    pass


@dataclass(frozen=True, slots=True)
class ParsedCenterDutyRequirement(ParsedRecord["CenterDutyRequirement"]):
    pass
