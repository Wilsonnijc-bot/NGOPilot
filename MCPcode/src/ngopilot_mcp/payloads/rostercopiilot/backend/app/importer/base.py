"""Shared importer interfaces and result containers."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Protocol, TypeVar, runtime_checkable

from openpyxl.workbook.workbook import Workbook

from .models import ImportAmbiguity, ImportBatchSummary, ParsedRecord

RecordT = TypeVar("RecordT")


@dataclass(frozen=True, slots=True)
class ImportResult(Generic[RecordT]):
    """Structured output from one parser pass.

    A parser that has not been implemented yet should return
    ``ImportResult.not_implemented(...)`` instead of raising a placeholder
    exception. Real parser failures should use the typed exceptions in
    ``app.importer.errors``.
    """

    summary: ImportBatchSummary
    records: tuple[ParsedRecord[RecordT], ...] = ()
    ambiguities: tuple[ImportAmbiguity, ...] = ()
    source_workbook: Path | None = None

    @property
    def ok(self) -> bool:
        return (
            self.summary.status in {"ok", "empty"}
            and not self.ambiguities
            and self.summary.silently_dropped_cells == 0
        )

    @property
    def implemented(self) -> bool:
        return self.summary.status != "not_implemented"

    @classmethod
    def empty(
        cls,
        *,
        parser_name: str,
        workbook_path: Path | None = None,
        ignored_sheets: tuple[str, ...] = (),
        notes: tuple[str, ...] = (),
    ) -> "ImportResult[RecordT]":
        return cls(
            summary=ImportBatchSummary.empty(
                parser_name=parser_name,
                ignored_sheets=ignored_sheets,
                notes=notes,
            ),
            source_workbook=workbook_path,
        )

    @classmethod
    def not_implemented(
        cls,
        *,
        parser_name: str,
        workbook_path: Path | None = None,
        doc_ref: str | None = None,
        notes: tuple[str, ...] = (),
    ) -> "ImportResult[RecordT]":
        return cls(
            summary=ImportBatchSummary.not_implemented(
                parser_name=parser_name,
                doc_ref=doc_ref,
                notes=notes,
            ),
            source_workbook=workbook_path,
        )


@runtime_checkable
class WorkbookImporter(Protocol[RecordT]):
    parser_name: str
    doc_ref: str

    def parse(self, workbook: Workbook | Path) -> ImportResult[RecordT]:
        """Parse a workbook or workbook path into structured import records."""


@dataclass(frozen=True, slots=True)
class BaseWorkbookImporter(Generic[RecordT]):
    """Minimal base for parser stubs.

    Concrete importers should override ``parse`` when parser logic is added.
    Until then, this base returns an explicit not-implemented result that tests
    and API code can inspect safely.
    """

    parser_name: str
    doc_ref: str

    def parse(self, workbook: Workbook | Path) -> ImportResult[RecordT]:
        workbook_path = workbook if isinstance(workbook, Path) else None
        return ImportResult.not_implemented(
            parser_name=self.parser_name,
            workbook_path=workbook_path,
            doc_ref=self.doc_ref,
        )
