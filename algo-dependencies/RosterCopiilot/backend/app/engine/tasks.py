"""Internal task representation: the unit of demand the scheduler places.

Tasks are built from FixedService occurrences, EscortRequests and
CenterDutyRequirements; they are not persisted — ScheduleEntry is the output.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time, timedelta

from ..domain import (
    CenterDutyRequirement,
    Elder,
    EscortRequest,
    FixedService,
    GENDER_SENSITIVE,
    GenderRequirement,
    Period,
    PRIORITY_TIER,
    ServiceCode,
    SourceEvidence,
    GapPolicy,
)


@dataclass(frozen=True)
class Task:
    key: str
    service_code: ServiceCode
    task_date: date
    weekday: int
    period: Period
    session_index: int | None  # None = occupies the whole half-day
    demand_id: str | None = None
    elder_id: str | None = None
    elder_name: str | None = None
    district: str | None = None
    center: str | None = None
    route: str | None = None
    destination: str | None = None
    start_time: time | None = None
    end_time: time | None = None
    pinned_worker_id: str | None = None
    is_exclusive: bool = False
    gender_requirement: GenderRequirement = GenderRequirement.ANY
    preferred_worker_id: str | None = None
    preference_strength: str | None = None  # "must" | "prefer" | None
    origin_fixed_service_id: str | None = None
    origin_escort_request_id: str | None = None
    notes: str | None = None
    source_refs: tuple[str, ...] = ()
    source_evidence: tuple[SourceEvidence, ...] = ()
    data_gap_ids: tuple[str, ...] = ()
    data_gap_policies: dict[str, GapPolicy] = field(default_factory=dict)
    gender_ok_unverified: bool = False
    assumptions: tuple[str, ...] = ()
    override_ids: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    priority: int = 0  # within-tier ordering

    @property
    def priority_tier(self) -> int:
        return PRIORITY_TIER[self.service_code]


def resolve_gender_requirement(
    service_code: ServiceCode,
    elder: Elder | None,
    explicit: GenderRequirement = GenderRequirement.ANY,
) -> GenderRequirement:
    """Rulebook RB-GEND-01/02: explicit requirement wins; otherwise
    gender-sensitive services default to same-gender-as-elder; unknown elder
    gender on a gender-sensitive service yields UNKNOWN (fail-safe -> review).
    """
    if explicit != GenderRequirement.ANY:
        return explicit
    if service_code in GENDER_SENSITIVE and service_code != ServiceCode.ESCORT:
        if elder is None or elder.gender is None:
            return GenderRequirement.UNKNOWN
        return GenderRequirement(elder.gender.value)
    return GenderRequirement.ANY


def task_from_fixed(fs: FixedService, on: date, elder: Elder | None) -> Task:
    return Task(
        key=fs.demand_id or f"fixed:{fs.id}:{on.isoformat()}",
        demand_id=fs.demand_id,
        service_code=fs.service_code,
        task_date=on,
        weekday=on.isoweekday(),
        period=fs.period,
        session_index=fs.session_index,
        elder_id=fs.elder_id,
        elder_name=elder.display_name if elder else None,
        district=fs.district or (elder.district if elder else None),
        route=fs.route,
        center=fs.center,
        start_time=fs.start_time,
        end_time=fs.end_time,
        pinned_worker_id=fs.assigned_worker_id,
        is_exclusive=fs.is_exclusive,
        gender_requirement=resolve_gender_requirement(
            fs.service_code, elder,
            elder.gender_requirement if elder else GenderRequirement.ANY),
        origin_fixed_service_id=fs.id,
        notes=fs.notes,
        source_refs=tuple(fs.source_refs),
        source_evidence=tuple(fs.source_evidence),
        data_gap_ids=tuple(fs.data_gap_ids),
        data_gap_policies=dict(fs.data_gap_policies),
        gender_ok_unverified=fs.gender_ok_unverified,
        assumptions=tuple(fs.assumptions),
        override_ids=tuple(fs.override_ids),
        depends_on=tuple(fs.depends_on),
        priority=fs.priority,
    )


def task_from_escort(req: EscortRequest, elder: Elder | None) -> Task:
    return Task(
        key=req.demand_id or f"escort:{req.id}",
        demand_id=req.demand_id,
        service_code=ServiceCode.ESCORT,
        task_date=req.service_date,
        weekday=req.service_date.isoweekday(),
        period=req.period,
        session_index=None,  # escorts occupy the whole half-day (Q-B5 assumption)
        elder_id=req.elder_id,
        elder_name=elder.display_name if elder else req.elder_id,
        district=elder.district if elder else None,
        destination=req.destination,
        start_time=req.appointment_time,
        gender_requirement=resolve_gender_requirement(
            ServiceCode.ESCORT, elder, req.gender_requirement),
        preferred_worker_id=req.preferred_worker_id,
        preference_strength=req.preference_strength,
        origin_escort_request_id=req.id,
        notes=req.notes or req.subject,
        source_refs=tuple(req.source_refs),
        source_evidence=tuple(req.source_evidence),
        data_gap_ids=tuple(req.data_gap_ids),
        data_gap_policies=dict(req.data_gap_policies),
        gender_ok_unverified=req.gender_ok_unverified,
        assumptions=tuple(req.assumptions),
        override_ids=tuple(req.override_ids),
        depends_on=tuple(req.depends_on),
    )


def duty_tasks(req: CenterDutyRequirement, week_start: date) -> list[Task]:
    on = week_start + timedelta(days=req.weekday - 1)
    return [
        Task(
            key=(req.demand_ids[i] if i < len(req.demand_ids) else
                 f"duty:{req.center}:{on.isoformat()}:{req.period.value}:{i + 1}"),
            demand_id=req.demand_ids[i] if i < len(req.demand_ids) else None,
            service_code=req.service_code,
            task_date=on,
            weekday=req.weekday,
            period=req.period,
            session_index=1,  # duty occupies one session; refined post-MVP
            center=req.center,
            district=req.center,
            priority=i,
            source_refs=tuple(req.source_refs),
            source_evidence=tuple(req.source_evidence),
            data_gap_ids=tuple(req.data_gap_ids),
            data_gap_policies=dict(req.data_gap_policies),
            assumptions=tuple(req.assumptions),
            override_ids=tuple(req.override_ids),
            depends_on=tuple(req.depends_on),
        )
        for i in range(req.required_count)
    ]
