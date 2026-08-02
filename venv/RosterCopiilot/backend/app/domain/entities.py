"""Master-data entities: workers, elders, recurring services, escort demand.

Field names deliberately keep the mock-MVP vocabulary (`display_name`,
`schedule_date`, `fixed_services`, ...) because the existing frontend reads
those keys. See docs/spec/canonical_schema.md for the full provenance of
each field.
"""
from __future__ import annotations

from datetime import date, time
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .enums import (
    Gender,
    GenderRequirement,
    Period,
    PRIORITY_TIER,
    ServiceCode,
)
from .provenance import (
    GapPolicy,
    SourceEvidence,
    merge_source_evidence,
    normalize_identity_string,
)

Weekday = Literal[1, 2, 3, 4, 5, 6]  # 1=Mon ... 6=Sat; Sunday not scheduled


class WeekPattern(BaseModel):
    """Week-of-month recurrence (rulebook RB-FIX-02).

    ``weeks`` uses "k-th occurrence of the weekday in the month" semantics
    (working assumption Q-A4 — requires NGO confirmation). ``weekly`` matches
    every week; odd/even month patterns gate whole months.
    """

    kind: Literal["weekly", "weeks_of_month", "odd_month", "even_month"] = "weekly"
    weeks: list[int] = Field(default_factory=list)
    raw: str = "weekly"

    @field_validator("weeks")
    @classmethod
    def _weeks_in_range(cls, v: list[int]) -> list[int]:
        if any(w < 1 or w > 5 for w in v):
            raise ValueError("weeks of month must be within 1..5")
        return sorted(set(v))

    @classmethod
    def parse(cls, raw: str) -> "WeekPattern":
        text = str(raw).strip()
        if text in ("", "weekly", "逢週", "每週"):
            return cls(kind="weekly", raw="weekly")
        if text in ("單月", "odd_month"):
            return cls(kind="odd_month", raw=text)
        if text in ("雙月", "even_month"):
            return cls(kind="even_month", raw=text)
        weeks = [int(p) for p in text.replace("，", ",").split(",") if p.strip().isdigit()]
        if not weeks:
            raise ValueError(f"unparseable week pattern: {raw!r}")
        return cls(kind="weeks_of_month", weeks=weeks, raw=text)

    def matches(self, on: date) -> bool:
        if self.kind == "weekly":
            return True
        if self.kind == "odd_month":
            return on.month % 2 == 1
        if self.kind == "even_month":
            return on.month % 2 == 0
        occurrence = (on.day - 1) // 7 + 1  # k-th occurrence of this weekday
        return occurrence in self.weeks

    def overlaps(self, other: "WeekPattern") -> bool:
        """True if two patterns can ever fire in the same week (slot conflict)."""
        if self.kind == "weekly" or other.kind == "weekly":
            return True
        if {self.kind, other.kind} == {"odd_month", "even_month"}:
            return False
        if self.kind == "weeks_of_month" and other.kind == "weeks_of_month":
            return bool(set(self.weeks) & set(other.weeks))
        return True  # month-parity vs weeks-of-month: conservative


class Employee(BaseModel):
    id: str
    display_name: str
    gender: Gender | None = None  # None = unknown (data gap, see RB-GEND-01)
    home_team: str = "EH"         # AMC/MRC/GC/EH/IH
    skills: list[ServiceCode] = Field(default_factory=list)
    routes: list[str] = Field(default_factory=list)  # districts / meal routes known
    seed_skills: list[ServiceCode] = Field(default_factory=list)
    seed_routes: list[str] = Field(default_factory=list)
    seed_skill_gap_ids: dict[ServiceCode, str] = Field(default_factory=dict)
    route_gap_ids: dict[str, str] = Field(default_factory=dict)
    source_evidence: list[SourceEvidence] = Field(default_factory=list)
    data_gap_ids: list[str] = Field(default_factory=list)
    data_gap_policies: dict[str, GapPolicy] = Field(default_factory=dict)
    data_gap_fields: dict[str, str] = Field(default_factory=dict)
    saturday_team: Literal["A", "B"] | None = None
    employment_type: Literal["full", "part"] = "full"
    work_start: time = time(8, 30)
    work_end: time = time(17, 30)
    notes: str | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _normalize_required_id(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = normalize_identity_string(value)
        if not normalized:
            raise ValueError("employee id must not be blank")
        return normalized

    @field_validator("routes", "seed_routes", mode="before")
    @classmethod
    def _normalize_routes(cls, value: object) -> object:
        if not isinstance(value, (list, tuple)):
            return value
        normalized = [
            normalize_identity_string(item) for item in value
            if isinstance(item, str) and normalize_identity_string(item)
        ]
        return sorted(set(normalized))

    def has_skill(self, code: ServiceCode) -> bool:
        return code in self.skills

    @model_validator(mode="after")
    def _canonical_evidence(self) -> "Employee":
        self.source_evidence = merge_source_evidence(self.source_evidence)
        return self


class Elder(BaseModel):
    id: str
    display_name: str
    gender: Gender | None = None  # None = unknown (data gap)
    district: str
    owning_unit: str = "EH"       # EH/IH/ED/AMC/MRC/GC/HSS
    gender_requirement: GenderRequirement = GenderRequirement.ANY
    exclusive_worker_id: str | None = None
    status: Literal["active", "hospitalised", "exited"] = "active"
    notes: str | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _normalize_required_id(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = normalize_identity_string(value)
        if not normalized:
            raise ValueError("elder id must not be blank")
        return normalized

    @field_validator("exclusive_worker_id", mode="before")
    @classmethod
    def _normalize_optional_worker_id(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return normalize_identity_string(value) or None


class FixedService(BaseModel):
    """A recurring weekly/patterned commitment (division-sheet template cell)."""

    id: str
    elder_id: str | None = None          # None for route-level tasks (meal routes)
    service_code: ServiceCode
    weekday: Weekday
    period: Period
    session_index: Literal[1, 2] = 1
    start_time: time | None = None
    end_time: time | None = None
    week_pattern: WeekPattern = Field(default_factory=WeekPattern)
    assigned_worker_id: str | None = None
    is_exclusive: bool = False
    district: str | None = None
    route: str | None = None             # meal route name for MEAL tasks
    center: str | None = None            # for template duty cells, if any
    priority: int = 0                    # within-tier ordering (lower = first)
    demand_id: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    source_evidence: list[SourceEvidence] = Field(default_factory=list)
    data_gap_ids: list[str] = Field(default_factory=list)
    data_gap_policies: dict[str, GapPolicy] = Field(default_factory=dict)
    gender_ok_unverified: bool = False
    assumptions: list[str] = Field(default_factory=list)
    override_ids: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    notes: str | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _normalize_required_id(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = normalize_identity_string(value)
        if not normalized:
            raise ValueError("fixed service id must not be blank")
        return normalized

    @field_validator(
        "elder_id", "assigned_worker_id", "district", "route", "center",
        "demand_id", mode="before",
    )
    @classmethod
    def _normalize_optional_identities(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return normalize_identity_string(value) or None

    @model_validator(mode="after")
    def _canonical_provenance(self) -> "FixedService":
        self.source_evidence = merge_source_evidence(self.source_evidence)
        self.override_ids = sorted(set(self.override_ids))
        self.depends_on = sorted(set(self.depends_on))
        return self

    @property
    def priority_tier(self) -> int:
        return PRIORITY_TIER[self.service_code]


class EscortRequest(BaseModel):
    """One escort appointment (護送個案總表 row). Occupies the whole half-day
    (working assumption Q-B5 — requires NGO confirmation)."""

    id: str
    service_date: date
    period: Period
    elder_id: str
    appointment_time: time | None = None
    destination: str
    subject: str | None = None
    transport: str | None = None
    gender_requirement: GenderRequirement = GenderRequirement.ANY
    preferred_worker_id: str | None = None
    preference_strength: Literal["must", "prefer"] | None = None
    status: Literal["requested", "cancelled"] = "requested"
    demand_id: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    source_evidence: list[SourceEvidence] = Field(default_factory=list)
    data_gap_ids: list[str] = Field(default_factory=list)
    data_gap_policies: dict[str, GapPolicy] = Field(default_factory=dict)
    gender_ok_unverified: bool = False
    assumptions: list[str] = Field(default_factory=list)
    override_ids: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    notes: str | None = None

    @field_validator("id", "elder_id", "destination", mode="before")
    @classmethod
    def _normalize_required_identities(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = normalize_identity_string(value)
        if not normalized:
            raise ValueError("escort identity fields must not be blank")
        return normalized

    @field_validator(
        "preferred_worker_id", "demand_id", mode="before"
    )
    @classmethod
    def _normalize_optional_identities(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return normalize_identity_string(value) or None

    @model_validator(mode="after")
    def _canonical_provenance(self) -> "EscortRequest":
        self.source_evidence = merge_source_evidence(self.source_evidence)
        self.override_ids = sorted(set(self.override_ids))
        self.depends_on = sorted(set(self.depends_on))
        return self


class CenterDutyRequirement(BaseModel):
    """Required duty headcount per (centre, weekday, period).

    Counts in the mock are modelled on the observed division sheet; real
    values require NGO confirmation (clarification Q-A3).
    """

    center: str
    weekday: Weekday
    period: Period
    required_count: int = 1
    demand_ids: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    source_evidence: list[SourceEvidence] = Field(default_factory=list)
    data_gap_ids: list[str] = Field(default_factory=list)
    data_gap_policies: dict[str, GapPolicy] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    override_ids: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _canonical_evidence(self) -> "CenterDutyRequirement":
        self.source_evidence = merge_source_evidence(self.source_evidence)
        self.override_ids = sorted(set(self.override_ids))
        self.depends_on = sorted(set(self.depends_on))
        return self

    @property
    def service_code(self) -> ServiceCode:
        return ServiceCode(self.center)


class ScheduleParams(BaseModel):
    week_start: date  # must be a Monday
    escort_baseline: int = 4  # nominal reserved escorts per half-day (RB-ESC-01)
    districts: list[str] = Field(default_factory=list)

    @field_validator("week_start")
    @classmethod
    def _must_be_monday(cls, v: date) -> date:
        if v.weekday() != 0:
            raise ValueError("week_start must be a Monday")
        return v
