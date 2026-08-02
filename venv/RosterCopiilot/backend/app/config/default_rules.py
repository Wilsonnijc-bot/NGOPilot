"""Default scheduler rules for Phase 1 scaffolding.

These values are derived from ``docs/spec/rulebook.md`` and related spec files.
Unconfirmed assumptions are kept explicit so the scheduler bridge can surface
them instead of burying them in parser code.
"""
from __future__ import annotations

from ..domain import Period, ServiceCode
from ..domain.snapshot import (
    CentreDutyPlaceholderRequirement,
    EscortOccupancyRule,
    SchedulerConfig,
    SessionDefinition,
    TaskKind,
    UnknownDataPolicy,
)


SESSION_TIME_ASSUMPTION = (
    "Exact clock windows for each half-day session are unconfirmed; use "
    "weekday/period/session slots until the NGO confirms service windows."
)

DEFAULT_SCHEDULER_CONFIG = SchedulerConfig(
    version="phase1-rulebook-defaults",
    sessions=[
        SessionDefinition(
            id="AM-1",
            period=Period.AM,
            session_index=1,
            label="AM session 1",
            assumption=SESSION_TIME_ASSUMPTION,
        ),
        SessionDefinition(
            id="AM-2",
            period=Period.AM,
            session_index=2,
            label="AM session 2",
            assumption=SESSION_TIME_ASSUMPTION,
        ),
        SessionDefinition(
            id="PM-1",
            period=Period.PM,
            session_index=1,
            label="PM session 1",
            assumption=SESSION_TIME_ASSUMPTION,
        ),
        SessionDefinition(
            id="PM-2",
            period=Period.PM,
            session_index=2,
            label="PM session 2",
            assumption=SESSION_TIME_ASSUMPTION,
        ),
    ],
    service_priority_order=[
        TaskKind.CENTRE_DUTY,
        TaskKind.ESCORT,
        TaskKind.FIXED_SERVICE,
        TaskKind.HC_PATTERN,
        TaskKind.MEAL_LOGISTICS,
    ],
    service_code_priority_order=[
        ServiceCode.DUTY_AMC,
        ServiceCode.DUTY_MRC,
        ServiceCode.DUTY_GC,
        ServiceCode.ESCORT,
        ServiceCode.EXERCISE,
        ServiceCode.HOME_CLEAN,
        ServiceCode.PERSONAL_CARE,
        ServiceCode.BATH,
        ServiceCode.MEAL,
        ServiceCode.KITCHEN,
    ],
    escort_occupancy=EscortOccupancyRule(
        occupies_full_half_day=True,
        max_requests_per_worker_per_half_day=1,
        baseline_reserved_workers_per_half_day=4,
        assumption=(
            "Escort requests conservatively occupy the full AM/PM period; "
            "same-half-day escort chaining is unconfirmed."
        ),
    ),
    centre_duty_placeholders=[
        CentreDutyPlaceholderRequirement(
            centre="AMC",
            weekdays=[1, 2, 3, 4, 5],
            periods=[Period.AM, Period.PM],
            required_count=1,
            assumption=(
                "Placeholder count only; required duty count and role mix "
                "must be confirmed with the NGO."
            ),
        ),
        CentreDutyPlaceholderRequirement(
            centre="MRC",
            weekdays=[1, 2, 3, 4, 5, 6],
            periods=[Period.AM, Period.PM],
            required_count=1,
            assumption=(
                "Saturday MRC operation is observed in fixtures but still "
                "needs confirmation for production rules."
            ),
        ),
        CentreDutyPlaceholderRequirement(
            centre="GC",
            weekdays=[1, 2, 3, 4, 5],
            periods=[Period.AM, Period.PM],
            required_count=1,
            assumption=(
                "Placeholder count only; required duty count and role mix "
                "must be confirmed with the NGO."
            ),
        ),
    ],
    unknown_data_policy=UnknownDataPolicy(
        unknown_gender="ineligible_and_data_gap",
        unknown_skill="ineligible_and_data_gap",
        unknown_route="manual_review_required",
        unknown_week_pattern="manual_review_required",
        note=(
            "The scheduler should fail safe on eligibility gaps and emit "
            "reviewable data gaps rather than guessing."
        ),
    ),
    assumptions=[
        "Within-tier priority for HC versus other fixed home services is unconfirmed.",
        "Meal/logistics time windows are unconfirmed; default to session slots.",
        "Centre duty role certifications are unconfirmed.",
        "Week-of-month semantics for HC patterns require NGO confirmation.",
    ],
)
