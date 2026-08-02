"""A representative scheduler fixture derived from the reverse-engineered rules.

This snapshot is hand-authored from the semantics in ``docs/spec/rulebook.md``
and ``docs/spec/excel_semantics.md`` — **not** from a live workbook import. It
is deliberately small but exercises every Phase 1 rule surface:

* 7 workers (incl. an exclusive E+RO specialist, the only male bath worker, and
  a new joiner with unknown gender — a worker-level data gap);
* 11 fixed / HC template tasks that fire in the target week (plus one HC task
  gated *out* by its week-of-month pattern, to prove RB-FIX-02 expansion);
* 3 escort requests (one with an unverifiable gender requirement — a data gap);
* 3 centre duty requirements (AMC / MRC / GC);
* a worker-leave change event that cancels two exclusive services (RB-EXCL-02).

The target week is Mon 2026-01-05 … Sat 2026-01-10. In that week Mon–Thu are the
1st weekday-occurrence of the month and Fri–Sat the 2nd, which is what makes the
``1,3`` vs ``2,4`` HC patterns resolve differently.
"""
from __future__ import annotations

from datetime import date, time

from ..domain import (
    ChangeEvent,
    ChangeType,
    DataGap,
    Elder,
    Employee,
    Gender,
    GenderRequirement,
    Period,
    SchedulerConfig,
    SchedulerSnapshot,
    ServiceCode,
    TaskDemand,
    TaskKind,
    TaskSource,
    WeekPattern,
    WorkerAvailability,
)

WEEK_START = date(2026, 1, 5)  # Monday


def _workers() -> list[Employee]:
    return [
        Employee(
            id="W1", display_name="娥", gender=Gender.FEMALE, home_team="IH",
            skills=[ServiceCode.EXERCISE, ServiceCode.HOME_CLEAN,
                    ServiceCode.MEAL, ServiceCode.ESCORT],
            routes=["灣仔"], saturday_team="A",
            notes="運動訓練專屬同工",
        ),
        Employee(
            id="W2", display_name="志明", gender=Gender.MALE, home_team="IH",
            skills=[ServiceCode.BATH, ServiceCode.PERSONAL_CARE,
                    ServiceCode.HOME_CLEAN, ServiceCode.MEAL, ServiceCode.ESCORT],
            routes=["北角"], saturday_team="B",
            notes="唯一男性沖涼/個人護理同工",
        ),
        Employee(
            id="W3", display_name="嘉偉", gender=Gender.MALE, home_team="MRC",
            skills=[ServiceCode.ESCORT, ServiceCode.MEAL, ServiceCode.DUTY_MRC],
            routes=["灣仔", "銅鑼灣"], saturday_team="A",
            notes="護送主力",
        ),
        Employee(
            id="W4", display_name="美紅", gender=Gender.FEMALE, home_team="AMC",
            skills=[ServiceCode.HOME_CLEAN, ServiceCode.MEAL,
                    ServiceCode.ESCORT, ServiceCode.DUTY_AMC],
            routes=["柴灣"], saturday_team="B",
        ),
        Employee(
            id="W5", display_name="秀英", gender=Gender.FEMALE, home_team="GC",
            skills=[ServiceCode.EXERCISE, ServiceCode.PERSONAL_CARE,
                    ServiceCode.MEAL, ServiceCode.DUTY_GC],
            routes=["筲箕灣"], saturday_team="A",
        ),
        Employee(
            id="W6", display_name="強", gender=Gender.MALE, home_team="AMC",
            skills=[ServiceCode.MEAL, ServiceCode.ESCORT, ServiceCode.DUTY_AMC],
            routes=["北角"], saturday_team="B",
        ),
        Employee(
            id="W7", display_name="新丁", gender=None, home_team="EH",
            skills=[ServiceCode.MEAL, ServiceCode.ESCORT],
            routes=["柴灣"], saturday_team="A",
            notes="新同工，性別及技能表未齊（data gap）",
        ),
    ]


def _elders() -> list[Elder]:
    return [
        Elder(id="EL1", display_name="陳伯", gender=Gender.MALE, district="灣仔",
              owning_unit="IH", exclusive_worker_id="W1", notes="只要娥姐"),
        Elder(id="EL2", display_name="李婆婆", gender=Gender.FEMALE, district="灣仔",
              owning_unit="IH", exclusive_worker_id="W1", notes="只要娥姐"),
        Elder(id="EL3", display_name="黃伯", gender=Gender.MALE, district="北角",
              owning_unit="IH", gender_requirement=GenderRequirement.MALE,
              notes="要求男同工沖涼"),
        Elder(id="EL4", display_name="周婆婆", gender=Gender.FEMALE, district="柴灣",
              owning_unit="EH"),
        Elder(id="EL5", display_name="吳婆婆", gender=Gender.FEMALE, district="筲箕灣",
              owning_unit="IH"),
        Elder(id="EL6", display_name="鄭婆婆", gender=Gender.FEMALE, district="銅鑼灣",
              owning_unit="EH"),
        Elder(id="EL7", display_name="謝長者", gender=None, district="灣仔",
              owning_unit="ED", gender_requirement=GenderRequirement.UNKNOWN,
              notes="性別資料缺失（data gap）"),
        Elder(id="EL8", display_name="馮婆婆", gender=Gender.FEMALE, district="筲箕灣",
              owning_unit="EH"),
        Elder(id="EL9", display_name="盧婆婆", gender=Gender.FEMALE, district="北角",
              owning_unit="IH", gender_requirement=GenderRequirement.FEMALE),
        Elder(id="EL10", display_name="何婆婆", gender=Gender.FEMALE, district="柴灣",
              owning_unit="EH"),
        Elder(id="EL11", display_name="麥婆婆", gender=Gender.FEMALE, district="筲箕灣",
              owning_unit="IH"),
        Elder(id="EL12", display_name="蕭婆婆", gender=Gender.FEMALE, district="北角",
              owning_unit="EH"),
    ]


def _demands() -> list[TaskDemand]:
    def fixed(id_, code, weekday, period, session, elder, worker, **kw):
        return TaskDemand(
            id=id_, kind=TaskKind.FIXED_SERVICE, source=TaskSource.OPERATOR_INPUT,
            service_code=code, weekday=weekday, period=period, session_index=session,
            elder_id=elder, pinned_worker_id=worker, **kw)

    def hc(id_, weekday, period, session, elder, worker, pattern):
        return TaskDemand(
            id=id_, kind=TaskKind.HC_PATTERN, source=TaskSource.OPERATOR_INPUT,
            service_code=ServiceCode.HOME_CLEAN, weekday=weekday, period=period,
            session_index=session, elder_id=elder, pinned_worker_id=worker,
            week_pattern=WeekPattern.parse(pattern))

    return [
        # -- exclusive E+RO bound to 娥 (W1); Monday, so the leave event bites --
        fixed("FS-ERO-1", ServiceCode.EXERCISE, 1, Period.AM, 1, "EL1", None,
              exclusive_worker_id="W1", start_time=time(9, 0), end_time=time(10, 30)),
        fixed("FS-ERO-2", ServiceCode.EXERCISE, 1, Period.AM, 2, "EL2", None,
              exclusive_worker_id="W1", start_time=time(11, 0), end_time=time(12, 30)),
        fixed("FS-ERO-3", ServiceCode.EXERCISE, 2, Period.AM, 1, "EL8", "W5"),
        # -- gender-sensitive services --
        fixed("FS-BATH-1", ServiceCode.BATH, 3, Period.AM, 1, "EL3", "W2"),
        fixed("FS-PC-1", ServiceCode.PERSONAL_CARE, 4, Period.AM, 1, "EL9", "W5"),
        fixed("FS-PC-2", ServiceCode.PERSONAL_CARE, 3, Period.PM, 1, "EL5", "W5"),
        fixed("FS-ERO-4", ServiceCode.EXERCISE, 2, Period.PM, 1, "EL11", "W5"),
        # -- home cleaning: weekly + week-of-month patterns --
        fixed("FS-HC-weekly", ServiceCode.HOME_CLEAN, 2, Period.PM, 1, "EL4", "W2"),
        hc("FS-HC-13", 1, Period.PM, 1, "EL5", "W4", "1,3"),   # fires in wk-1
        hc("FS-HC-24", 1, Period.PM, 2, "EL6", "W4", "2,4"),   # gated OUT of wk-1
        hc("FS-HC-w1", 4, Period.PM, 1, "EL10", "W4", "weekly"),
        hc("FS-HC-w2", 4, Period.PM, 1, "EL12", "W2", "weekly"),
        # -- meal / logistics routes (universal skill) --
        _meal("FS-MEAL-1", 1, Period.PM, 2, "W1", "灣仔1", "灣仔"),
        _meal("FS-MEAL-2", 2, Period.AM, 2, "W6", "北角1", "北角"),
        _meal("FS-MEAL-3", 4, Period.AM, 2, "W7", "柴灣1", "柴灣"),
        # -- escorts (whole half-day occupancy) --
        TaskDemand(
            id="ESC-1", kind=TaskKind.ESCORT, source=TaskSource.WEEKLY_CHANGE,
            service_code=ServiceCode.ESCORT, task_date=date(2026, 1, 8),  # Thu
            period=Period.AM, session_index=None, occupies_full_period=True,
            elder_id="EL7", destination="RH", gender_requirement=GenderRequirement.UNKNOWN,
            data_gaps=[DataGap(kind="gender", entity_id="EL7",
                               message="長者性別資料缺失，護送性別要求無法核實")],
            notes="要求同性別同工，但長者性別未知"),
        TaskDemand(
            id="ESC-2", kind=TaskKind.ESCORT, source=TaskSource.WEEKLY_CHANGE,
            service_code=ServiceCode.ESCORT, task_date=date(2026, 1, 7),  # Wed
            period=Period.AM, session_index=None, occupies_full_period=True,
            elder_id="EL9", destination="PY", preferred_worker_id="W3",
            preference_strength="prefer", notes="建議嘉偉陪診"),
        TaskDemand(
            id="ESC-3", kind=TaskKind.ESCORT, source=TaskSource.WEEKLY_CHANGE,
            service_code=ServiceCode.ESCORT, task_date=date(2026, 1, 9),  # Fri
            period=Period.AM, session_index=None, occupies_full_period=True,
            elder_id="EL4", destination="QM", notes="覆診"),
        # -- centre duty requirements --
        _duty("DUTY-AMC", ServiceCode.DUTY_AMC, "AMC", 1, Period.AM),
        _duty("DUTY-MRC", ServiceCode.DUTY_MRC, "MRC", 2, Period.AM),
        _duty("DUTY-GC", ServiceCode.DUTY_GC, "GC", 3, Period.AM),
    ]


def _meal(id_, weekday, period, session, worker, route, district) -> TaskDemand:
    return TaskDemand(
        id=id_, kind=TaskKind.MEAL_LOGISTICS, source=TaskSource.OPERATOR_INPUT,
        service_code=ServiceCode.MEAL, weekday=weekday, period=period,
        session_index=session, pinned_worker_id=worker, route=route, district=district)


def _duty(id_, code, centre, weekday, period) -> TaskDemand:
    return TaskDemand(
        id=id_, kind=TaskKind.CENTRE_DUTY, source=TaskSource.RULEBOOK,
        service_code=code, weekday=weekday, period=period, required_count=1,
        centre=centre)


def _change_events() -> list[ChangeEvent]:
    return [
        ChangeEvent(
            id="EV-LEAVE-1", type=ChangeType.LEAVE, change_date=WEEK_START,
            period=Period.AM, worker_id="W1",
            reason="娥上午請假（專屬運動訓練同工）"),
    ]


def representative_snapshot() -> SchedulerSnapshot:
    """The canonical Phase 1 scheduler fixture (no Excel required)."""
    return SchedulerSnapshot(
        week_start=WEEK_START,
        # Empty duty placeholders: this fixture states duty needs explicitly so
        # task counts stay predictable (placeholders are unconfirmed assumptions).
        config=SchedulerConfig(version="fixture-representative", centre_duty_placeholders=[]),
        workers=_workers(),
        elders=_elders(),
        availability=[
            WorkerAvailability(worker_id="W1", available_date=WEEK_START,
                               period=Period.AM, is_available=False, reason="leave",
                               notes="娥上午請假"),
        ],
        demands=_demands(),
        change_events=_change_events(),
        data_gaps=[
            DataGap(kind="gender", entity_id="W7",
                    message="新同工 W7 性別資料未提供，性別敏感服務暫不可派"),
        ],
        source=TaskSource.FIXTURE,
        source_note="Derived from rulebook.md / excel_semantics.md, not a live import.",
    )
