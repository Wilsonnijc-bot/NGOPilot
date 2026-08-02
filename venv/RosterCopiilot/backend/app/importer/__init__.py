"""Excel importers for RosterCopiilot support tooling.

Implemented: division workbook ``恆常服務`` sheet, escort workbook, HC
timetable, new-staff skills sheet, transfer log and conservative alias
resolution.

These importers are for fixtures, regression checks, and source-cell evidence.
The product scheduler path should consume ``SchedulerSnapshot`` data rather
than treating workbook upload as the normal runtime workflow.
"""
from .base import BaseWorkbookImporter, ImportResult, WorkbookImporter
from .division import parse_division_workbook, parse_regular_services_sheet
from .division_models import (
    CounterObservation,
    DivisionImportResult,
    FixedServiceCandidate,
    ParsedAssignment,
    ParsedDetail,
    RawScheduleCell,
    WorkerColumn,
)
from .escort import parse_workbook as parse_escort_workbook
from .hc_timetable import parse_workbook as parse_hc_timetable_workbook
from .models import (
    CellRef,
    ImportAmbiguity,
    ImportBatchSummary,
    ParsedCenterDutyRequirement,
    ParsedElder,
    ParsedEmployee,
    ParsedEscortRequest,
    ParsedFixedService,
    ParsedRecord,
    SourceRef,
)
from .resolve import resolve_import_batch
from .skills import parse_skills_sheet
from .transfers import parse_transfer_log

__all__ = [
    "BaseWorkbookImporter",
    "CellRef",
    "CounterObservation",
    "DivisionImportResult",
    "FixedServiceCandidate",
    "ImportAmbiguity",
    "ImportBatchSummary",
    "ImportResult",
    "ParsedAssignment",
    "ParsedCenterDutyRequirement",
    "ParsedDetail",
    "ParsedElder",
    "ParsedEmployee",
    "ParsedEscortRequest",
    "ParsedFixedService",
    "ParsedRecord",
    "RawScheduleCell",
    "SourceRef",
    "WorkbookImporter",
    "WorkerColumn",
    "parse_division_workbook",
    "parse_escort_workbook",
    "parse_hc_timetable_workbook",
    "parse_regular_services_sheet",
    "parse_skills_sheet",
    "parse_transfer_log",
    "resolve_import_batch",
]
