"""Result models for the division-workbook (分工表) importer.

Everything is a JSON-friendly frozen dataclass. These models describe what the
Excel file *says*, mapped toward — but not forced into — the canonical domain:
aliases instead of entity ids, raw text always preserved, inferred facts
labelled as inferred. Promotion into ``app.domain`` objects happens later,
after entity resolution and NGO confirmation of the data gaps.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from .models import CellRef, Confidence, ImportAmbiguity

AssignmentKind = Literal[
    "field_service",   # CODE:Elder(UNIT) home visits incl. named escorts (Esc:)
    "escort_slot",     # bare ESC capacity reservation (yellow cells)
    "center_duty",     # AMC / MRC / GC (+roles)
    "meal",            # D meal delivery (route-level)
    "kitchen",         # 執牌(柴灣廚房) etc.
    "logistics",       # 跟車 / 特別探訪服務 / 康雲計劃 / phone duty / ...
    "off",             # OFF
]

WorkerStatus = Literal["active", "departed_inferred", "unknown"]

# Fill tokens observed on worker headers (docs/spec/excel_semantics.md §1.1).
ACTIVE_HEADER_FILLS = {"FFFFFF00"}
DEPARTED_HEADER_FILLS = {"FFD8D8D8", "FF999999", "FFD9D9D9", "FFBFBFBF"}


@dataclass(frozen=True, slots=True)
class WorkerColumn:
    """One worker column from header row 2 (+ later-row attributes)."""

    column: int
    column_letter: str
    raw_header: str
    display_name: str
    tags: tuple[str, ...] = ()
    header_fill: str | None = None
    # Inferred from header fill colour only — NOT confirmed business truth
    # docs/records/fact_check_report_2026-07-01.md §3.7: gray columns carry
    # handover notes, but the NGO never stated the colour convention.
    status_inferred: WorkerStatus = "unknown"
    work_hours_raw: str | None = None
    work_start: str | None = None
    work_end: str | None = None
    saturday_raw: str | None = None       # raw R93 cell text, structured below
    saturday_team: Literal["A", "B"] | None = None
    saturday_names_raw: str | None = None  # appended names; semantics unknown


@dataclass(frozen=True, slots=True)
class ParsedDetail:
    """The detail cell paired under an assignment cell."""

    cell: CellRef
    raw_text: str
    start_time: str | None = None   # "HH:MM"
    end_time: str | None = None
    district: str | None = None
    role_note: str | None = None            # (帶活動) / (派藥) / (協) ...
    trailing_label: str | None = None       # likely case manager — not asserted


@dataclass(frozen=True, slots=True)
class ParsedAssignment:
    """One assignment cell (or stacked/overflow assignment) in the grid."""

    cell: CellRef
    worker_column: int
    worker_alias: str
    weekday: int                      # 1=Mon .. 6=Sat
    period: str                       # "AM" | "PM"
    session_index: int | None         # 1 | 2 | None (overflow row)
    kind: AssignmentKind
    raw_text: str
    service_code_raw: str | None = None    # as written: E+RO / HC / Esc / D / AMC ...
    service_code: str | None = None        # canonical domain value where clean
    elder_alias: str | None = None
    unit: str | None = None                # (EH)/(IH)/(HSS)/(MRCV)...
    week_pattern_raw: str | None = None    # "(1,3)" suffix content, verbatim
    week_pattern_weeks: tuple[int, ...] | None = None  # parsed only when pure digits
    duty_center: str | None = None
    duty_role: str | None = None           # lead/assist/activity/medication/cleaning
    route_or_place: str | None = None      # D(明華) / 執牌(柴灣廚房)
    inline_note: str | None = None         # transfer notes, trailing names, times
    detail: ParsedDetail | None = None
    stacked: bool = False   # parsed out of a detail-row position, sharing the slot
    overflow: bool = False  # parsed out of an extra row beyond the two slot pairs
    fill: str | None = None
    confidence: Confidence = "high"
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FixedServiceCandidate:
    """A field-service assignment mapped toward domain FixedService.

    Aliases, not ids; missing gender/skills/addresses are NOT invented.
    """

    service_code: str | None          # canonical ServiceCode value or None
    service_code_raw: str
    weekday: int
    period: str
    session_index: int | None
    worker_alias: str
    worker_column_letter: str
    elder_alias: str | None
    unit: str | None
    week_pattern_raw: str | None
    week_pattern_weeks: tuple[int, ...] | None
    start_time: str | None
    end_time: str | None
    district: str | None
    case_manager_candidate: str | None
    inline_note: str | None
    stacked: bool
    source_ref: str                   # sheet!cell label
    confidence: Confidence
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CounterObservation:
    """AY/AZ/BA aggregate counters for one session row (validation data)."""

    row: int
    weekday: int
    period: str
    session_index: int
    ero_expected: int | None
    other_label: str | None           # "Esc" | "D" (from the label row below)
    other_expected: int | None
    total_expected: int | None
    ero_counted: int = 0
    esc_counted: int = 0
    d_counted: int = 0
    matches: bool | None = None       # None when nothing to compare


@dataclass(frozen=True, slots=True)
class RawScheduleCell:
    """Every non-empty cell in the used range, with its classification.

    The reconciliation guarantee: every non-empty cell appears here exactly
    once, so `silently_dropped == 0` is verifiable, not asserted.
    """

    cell: CellRef
    raw_text: str
    category: str   # header/structural/assignment/detail/counter/counter_label/
                    # work_hours/saturday_team/extra_note/out_of_block/ambiguous
    fill: str | None = None


@dataclass(frozen=True, slots=True)
class PeriodBlock:
    period: str
    rows: tuple[int, ...]
    assignment_rows: tuple[int, ...]
    detail_rows: tuple[int, ...]
    extra_rows: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class WeekdayBlock:
    weekday: int
    label_raw: str
    row_start: int
    row_end: int
    periods: tuple[PeriodBlock, ...] = ()


@dataclass(frozen=True, slots=True)
class DivisionImportResult:
    workbook_path: str
    sheet_name: str
    imported_at: str
    declared_max_row: int
    declared_max_column: int
    used_range: dict
    workers: tuple[WorkerColumn, ...] = ()
    gap_columns: tuple[str, ...] = ()
    counter_columns: tuple[str, ...] = ()
    weekday_blocks: tuple[WeekdayBlock, ...] = ()
    assignments: tuple[ParsedAssignment, ...] = ()
    fixed_service_candidates: tuple[FixedServiceCandidate, ...] = ()
    counters: tuple[CounterObservation, ...] = ()
    raw_cells: tuple[RawScheduleCell, ...] = ()
    ambiguities: tuple[ImportAmbiguity, ...] = ()
    summary: dict = field(default_factory=dict)

    def to_json_dict(self) -> dict:
        """Plain JSON-friendly dict (Paths and other objects stringified)."""

        def _factory(pairs):
            out = {}
            for k, v in pairs:
                if v is not None and not isinstance(v, (str, int, float, bool,
                                                        list, tuple, dict)):
                    v = str(v)
                out[k] = v
            return out

        return asdict(self, dict_factory=_factory)
