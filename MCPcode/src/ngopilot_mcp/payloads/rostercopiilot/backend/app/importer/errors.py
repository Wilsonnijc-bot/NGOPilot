"""Typed exceptions for Excel importer failures."""
from __future__ import annotations

from .models import SourceRef


class ImporterError(Exception):
    """Base class for importer errors that should be surfaced to callers."""

    def __init__(self, message: str, *, source: SourceRef | None = None) -> None:
        super().__init__(message)
        self.source = source


class WorkbookLoadError(ImporterError):
    """Raised when a workbook cannot be opened by openpyxl."""


class MissingSheetError(ImporterError):
    """Raised when a required sheet is absent from a workbook."""


class UnsupportedWorkbookError(ImporterError):
    """Raised when a workbook has an unsupported structure or extension."""


class WorkbookStructureError(ImporterError):
    """Raised when a workbook shape violates the importer contract."""


class ParseNotImplementedError(ImporterError):
    """Raised only when a caller explicitly requests unimplemented parsing."""


class CellParseError(ImporterError):
    """Raised when one cell fails a required grammar."""


class AmbiguousImportError(ImporterError):
    """Raised when ambiguity cannot be carried forward as an audit item."""
