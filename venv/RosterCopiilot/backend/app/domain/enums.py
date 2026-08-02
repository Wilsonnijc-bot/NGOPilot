"""Enumerations for the RosterCopiilot canonical domain model.

Values mirror the vocabulary of the real NGO workbooks (see
docs/spec/data_dictionary.md §1) so exports stay readable to NGO staff.
"""
from __future__ import annotations

from enum import Enum


class Gender(str, Enum):
    MALE = "M"
    FEMALE = "F"


class GenderRequirement(str, Enum):
    MALE = "M"
    FEMALE = "F"
    ANY = "ANY"
    # Gender data is missing from the NGO files; UNKNOWN makes the gap explicit.
    # The scheduler treats UNKNOWN as "cannot verify" -> ineligible + data-gap flag.
    UNKNOWN = "UNKNOWN"


class Period(str, Enum):
    AM = "AM"
    PM = "PM"


class ServiceCode(str, Enum):
    """Canonical service codes. String values follow the Excel cell vocabulary."""

    EXERCISE = "E+RO"       # home exercise / rehab training (exclusive-bound)
    HOME_CLEAN = "HC"       # home cleaning (week-of-month patterns)
    PERSONAL_CARE = "PC"    # personal care (gender-sensitive)
    BATH = "B"              # bathing (gender-sensitive)
    ESCORT = "ESC"          # escort / accompany to appointment (floating demand)
    MEAL = "D"              # meal delivery (route-based, universal skill)
    DUTY_AMC = "AMC"        # centre duty
    DUTY_MRC = "MRC"
    DUTY_GC = "GC"
    KITCHEN = "KITCHEN"     # 執牌(柴灣廚房) style logistics duty
    OFF = "OFF"


class ServiceCategory(str, Enum):
    HOME_VISIT = "home_visit"
    ESCORT = "escort"
    CENTER_DUTY = "center_duty"
    LOGISTICS = "logistics"


SERVICE_CATEGORY: dict[ServiceCode, ServiceCategory] = {
    ServiceCode.EXERCISE: ServiceCategory.HOME_VISIT,
    ServiceCode.HOME_CLEAN: ServiceCategory.HOME_VISIT,
    ServiceCode.PERSONAL_CARE: ServiceCategory.HOME_VISIT,
    ServiceCode.BATH: ServiceCategory.HOME_VISIT,
    ServiceCode.ESCORT: ServiceCategory.ESCORT,
    ServiceCode.MEAL: ServiceCategory.LOGISTICS,
    ServiceCode.DUTY_AMC: ServiceCategory.CENTER_DUTY,
    ServiceCode.DUTY_MRC: ServiceCategory.CENTER_DUTY,
    ServiceCode.DUTY_GC: ServiceCategory.CENTER_DUTY,
    ServiceCode.KITCHEN: ServiceCategory.LOGISTICS,
    ServiceCode.OFF: ServiceCategory.LOGISTICS,
}

# Gender-sensitive services: worker gender must satisfy the elder's requirement
# (rulebook RB-GEND-01/02). Escort is gender-sensitive per case.
GENDER_SENSITIVE: set[ServiceCode] = {
    ServiceCode.BATH,
    ServiceCode.PERSONAL_CARE,
    ServiceCode.ESCORT,
}

# Skill-gated services. MEAL is deliberately absent (universal, RB-SKILL-02);
# route qualification is checked separately (RB-SKILL-03).
SKILL_GATED: set[ServiceCode] = {
    ServiceCode.EXERCISE,
    ServiceCode.HOME_CLEAN,
    ServiceCode.PERSONAL_CARE,
    ServiceCode.BATH,
    ServiceCode.ESCORT,
    ServiceCode.DUTY_AMC,
    ServiceCode.DUTY_MRC,
    ServiceCode.DUTY_GC,
    ServiceCode.KITCHEN,
}

# Unassigned-penalty tiers (rulebook RB-PRIO-01): lower number = higher priority.
PRIORITY_TIER: dict[ServiceCode, int] = {
    ServiceCode.DUTY_AMC: 1,
    ServiceCode.DUTY_MRC: 1,
    ServiceCode.DUTY_GC: 1,
    ServiceCode.ESCORT: 2,
    ServiceCode.EXERCISE: 3,
    ServiceCode.HOME_CLEAN: 3,
    ServiceCode.PERSONAL_CARE: 3,
    ServiceCode.BATH: 3,
    ServiceCode.MEAL: 4,
    ServiceCode.KITCHEN: 5,
    ServiceCode.OFF: 9,
}


class EntryStatus(str, Enum):
    SCHEDULED = "scheduled"
    NEEDS_REVIEW = "needs_review"
    AFFECTED = "affected"
    CANCELLED = "cancelled"
    UNASSIGNED = "unassigned"


class EntrySource(str, Enum):
    TEMPLATE = "template"            # from a FixedService with its template worker
    WEEKLY_FILL = "weekly_fill"      # weekly floating fill (escort, duty)
    SYSTEM_REASSIGNED = "system_reassigned"
    MANUAL = "manual"


class ChangeType(str, Enum):
    LEAVE = "leave"
    ELDER_CANCELLATION = "elder_cancellation"
    ESCORT_NEW = "escort_new"
    ESCORT_CANCELLED = "escort_cancelled"


class AuditKind(str, Enum):
    EXCLUSIVE_CANCELLATION = "exclusive_cancellation"
    UNASSIGNED_TASK = "unassigned_task"
    DUTY_UNDER_COVERAGE = "duty_under_coverage"
    DISPLACEMENT_CHAIN = "displacement_chain"
    REPLACEMENT_SUGGESTION = "replacement_suggestion"
    ESCORT_ADJUSTMENT = "escort_adjustment"
    SERVICE_CANCELLATION = "service_cancellation"
    REFILL = "refill"
    DATA_GAP = "data_gap"
    TEMPLATE_ISSUE = "template_issue"


class Severity(str, Enum):
    HIGH = "high"
    WARNING = "warning"
    INFO = "info"


class AuditStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"


class ReviewReasonCode(str, Enum):
    """Structured reasons for human review (never bare free text)."""

    NO_QUALIFIED_WORKER = "no_qualified_worker"
    SKILL_MISMATCH = "skill_mismatch"
    ROUTE_UNQUALIFIED = "route_unqualified"
    GENDER_MISMATCH = "gender_mismatch"
    GENDER_UNKNOWN = "gender_unknown"
    EXCLUSIVE_WORKER_ABSENT = "exclusive_worker_absent"
    EXCLUSIVE_BINDING = "exclusive_binding"
    TIME_CONFLICT = "time_conflict"
    WORKER_ON_LEAVE = "worker_on_leave"
    NOT_WORKING_DAY = "not_working_day"
    DUTY_SHORTFALL = "duty_shortfall"
    REPLACEMENT_PROPOSED = "replacement_proposed"
    ESCORT_OVER_BASELINE = "escort_over_baseline"
    DISPLACEMENT_REQUIRED = "displacement_required"
    WORKER_RELEASED = "worker_released"
    PREFERENCE_UNMET = "preference_unmet"
    TEMPLATE_WORKER_INELIGIBLE = "template_worker_ineligible"
    ELDER_CANCELLED = "elder_cancelled"
    FORBIDDEN_ASSIGNMENT = "forbidden_assignment"
    EXPORT_PLACEMENT_FAILURE = "export_placement_failure"


class VersionKind(str, Enum):
    BASELINE = "baseline"
    REPAIR = "repair"
    MANUAL_EDIT = "manual_edit"


# Which weekday (ISO, 1=Mon) each centre operates. Saturday: MRC only
# (observed in the Saturday block of the division sheet; unconfirmed by NGO).
CENTER_CODES = ("AMC", "MRC", "GC")
