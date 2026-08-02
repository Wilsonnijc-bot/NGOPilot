"""Deterministic mock dataset generator.

Produces a dataset with the statistical shape of the real NGO workbooks
(docs/evaluation/mock_data_spec.md): 52 workers, 320 elders, patterned fixed
services, an escort week with over-/under-baseline days, and named edge cases
with **stable IDs** so tests and demo scripts can reference them.

Everything is driven by ``random.Random(seed)`` — same seed, same dataset.
"""
from __future__ import annotations

import random
from datetime import date, time, timedelta

from ..domain import (
    CenterDutyRequirement,
    ChangeEvent,
    ChangeType,
    Elder,
    Employee,
    EscortRequest,
    FixedService,
    Gender,
    GenderRequirement,
    MockDataset,
    Period,
    ScheduleParams,
    ServiceCode,
    WeekPattern,
)

DEFAULT_SEED = 2026
DEFAULT_WEEK_START = date(2026, 6, 8)  # a Monday

# Ordered west→east so adjacent picks simulate geographic clustering.
DISTRICTS = [
    "灣仔", "銅鑼灣", "跑馬地", "天后", "炮台山", "北角", "鰂魚涌",
    "太古", "西灣河", "筲箕灣", "杏花邨", "柴灣", "小西灣",
]

MEAL_ROUTES = [
    "灣仔1", "灣仔2", "灣仔3", "鰂+西+太古", "筲箕灣",
    "柴灣1", "柴灣2", "小西灣", "勵德", "北角1", "北角2",
]
ROUTE_DISTRICT = {
    "灣仔1": "灣仔", "灣仔2": "灣仔", "灣仔3": "灣仔",
    "鰂+西+太古": "鰂魚涌", "筲箕灣": "筲箕灣", "柴灣1": "柴灣",
    "柴灣2": "柴灣", "小西灣": "小西灣", "勵德": "天后",
    "北角1": "北角", "北角2": "北角",
}

DESTINATIONS = [
    ("PY", "內科"), ("PY", "骨科"), ("RH", "老人科"), ("RH", "抽血"),
    ("QM", "心臟科"), ("東華東院", "眼科"), ("東區醫院", "精神科"),
    ("鄧肇堅醫院", "物理治療"), ("貝夫人", "普通科"), ("西灣河普通科門診", "抽血"),
    ("灣仔診所", "普通科"), ("中信銀行", "銀行事務"), ("灣仔區內超市", None),
]
TRANSPORTS = ["的士來回", "巴士來回", "小巴來回", "步行來回", "愛心小巴", "MTR"]

WORKER_NAMES = [
    "娥", "炎萍", "寶芝", "康", "嘉偉", "鳳", "強", "美紅", "秀英", "匯珠",
    "少芬", "菲菲", "洁麗", "樹芬", "燕", "玲", "薇", "美蓮", "志明", "璐霖",
    "云", "蘇", "芝", "嫦", "偉業", "翠燕", "淑嫺", "美健", "金", "美儀",
    "翠君", "栢如", "仲坪", "茵", "志豪", "香", "嘉文", "熙仔", "奕倫", "梅欽",
    "春", "偉", "家偉", "玉", "文偉", "倩雯", "小金", "阿珍", "阿蓮", "阿好",
    "阿彩", "月娥", "麗華", "惠芳",
]

ELDER_SURNAME_LETTERS = list("YLCHWFTKMNABPS")
ELDER_GIVEN = list("珍玲明蓮娟雄娥美芬華貞棠顏姿芳嫻蘇森槐惠基安霖卿容儀傑坤光燕璋葉全鈴梅荷湖京禮蘭儂鳴金好彩弟妹嫦銀鳳翠雲柱")

CENTERS = ("AMC", "MRC", "GC")


class _Ids:
    def __init__(self) -> None:
        self.counters: dict[str, int] = {}

    def next(self, prefix: str) -> str:
        self.counters[prefix] = self.counters.get(prefix, 0) + 1
        return f"{prefix}{self.counters[prefix]:04d}"


def _pick_routes(rng: random.Random, k: int) -> list[str]:
    start = rng.randrange(0, len(DISTRICTS) - k)
    return DISTRICTS[start:start + k]


def _session_time(period: Period, session: int) -> tuple[time, time]:
    table = {
        (Period.AM, 1): (time(9, 0), time(10, 30)),
        (Period.AM, 2): (time(11, 0), time(12, 30)),
        (Period.PM, 1): (time(14, 0), time(15, 30)),
        (Period.PM, 2): (time(16, 0), time(17, 30)),
    }
    return table[(period, session)]


def _build_employees(rng: random.Random) -> list[Employee]:
    """52 workers in the segments documented in evaluation/mock_data_spec.md §1.1."""
    names = list(WORKER_NAMES)
    rng.shuffle(names)
    # Reserve stable names for edge-case actors (readability of demos/tests).
    for reserved in ("娥", "嘉偉", "志明"):
        names.remove(reserved)

    employees: list[Employee] = []
    male_budget = 10
    n = 0

    def make(name: str, *, gender: Gender | None, skills: list[ServiceCode],
             home_team: str, routes: list[str], notes: str | None = None,
             employment_type: str = "full") -> Employee:
        nonlocal n
        n += 1
        return Employee(
            id=f"W{n:03d}", display_name=name, gender=gender, home_team=home_team,
            skills=skills, routes=routes,
            saturday_team="A" if n % 2 == 1 else "B",
            employment_type=employment_type,  # type: ignore[arg-type]
            notes=notes,
        )

    def next_gender() -> Gender:
        nonlocal male_budget
        # keep ~10 male workers overall, deterministically spread
        if male_budget > 0 and rng.random() < 0.18:
            male_budget -= 1
            return Gender.MALE
        return Gender.FEMALE

    # --- Edge-case actors (stable ids W001-W003) -------------------------
    # W001 娥: exclusive E+RO specialist (rulebook RB-EXCL-01 demo).
    employees.append(make(
        "娥", gender=Gender.FEMALE,
        skills=[ServiceCode.EXERCISE, ServiceCode.HOME_CLEAN, ServiceCode.MEAL,
                ServiceCode.ESCORT],
        home_team="IH", routes=["柴灣", "小西灣", "筲箕灣"],
        notes="運動訓練專屬同工（多名長者只接受佢）",
    ))
    # W002 嘉偉: escort-heavy male generalist with duty skill.
    employees.append(make(
        "嘉偉", gender=Gender.MALE,
        skills=[ServiceCode.ESCORT, ServiceCode.MEAL, ServiceCode.DUTY_MRC],
        home_team="MRC", routes=["灣仔", "銅鑼灣", "跑馬地"],
        notes="護送主力",
    ))
    male_budget -= 1
    # W003 志明: the ONLY male bath/PC specialist (gender-scarcity edge case).
    employees.append(make(
        "志明", gender=Gender.MALE,
        skills=[ServiceCode.BATH, ServiceCode.PERSONAL_CARE, ServiceCode.HOME_CLEAN,
                ServiceCode.MEAL, ServiceCode.ESCORT],
        home_team="IH", routes=["北角", "鰂魚涌", "太古"],
        notes="唯一男性沖涼/PC同工",
    ))
    male_budget -= 1

    # --- 19 home-visit generalists ---------------------------------------
    for i in range(19):
        skills = [ServiceCode.MEAL, ServiceCode.ESCORT]
        if i % 10 < 7:
            skills.append(ServiceCode.EXERCISE)
        if i % 2 == 0:
            skills.append(ServiceCode.HOME_CLEAN)
        if i % 3 == 0:
            skills.append(ServiceCode(CENTERS[(i // 3) % 3]))
        employees.append(make(
            names.pop(), gender=next_gender(), skills=skills,
            home_team="EH" if i % 2 == 0 else "IH",
            routes=_pick_routes(rng, 3),
        ))

    # --- 12 centre-attached (4 per centre) --------------------------------
    for i in range(12):
        center = CENTERS[i % 3]
        skills = [ServiceCode(center), ServiceCode.MEAL]
        if i % 2 == 0:
            skills.append(ServiceCode.ESCORT)
        if i >= 10:
            skills.append(ServiceCode.KITCHEN)
        employees.append(make(
            names.pop(), gender=next_gender(), skills=skills,
            home_team=center, routes=_pick_routes(rng, 2),
        ))

    # --- 5 more escort-heavy ----------------------------------------------
    for i in range(5):
        employees.append(make(
            names.pop(), gender=next_gender(),
            skills=[ServiceCode.ESCORT, ServiceCode.MEAL, ServiceCode(CENTERS[i % 3])],
            home_team="EH", routes=_pick_routes(rng, 3),
        ))

    # --- 3 more bath/PC specialists (all female) --------------------------
    for _ in range(3):
        employees.append(make(
            names.pop(), gender=Gender.FEMALE,
            skills=[ServiceCode.BATH, ServiceCode.PERSONAL_CARE,
                    ServiceCode.HOME_CLEAN, ServiceCode.MEAL],
            home_team="IH", routes=_pick_routes(rng, 3),
        ))

    # --- 4 kitchen / logistics --------------------------------------------
    for _ in range(4):
        employees.append(make(
            names.pop(), gender=next_gender(),
            skills=[ServiceCode.KITCHEN, ServiceCode.MEAL],
            home_team="EH", routes=["柴灣", "小西灣"],
        ))

    # --- 4 new joiners (thin skills — data-gap realism) --------------------
    for _ in range(4):
        employees.append(make(
            names.pop(), gender=next_gender(),
            skills=[ServiceCode.MEAL, ServiceCode.ESCORT],
            home_team="EH", routes=_pick_routes(rng, 2),
            notes="新同工，技能表未齊",
        ))

    # --- 1 extra generalist + 1 part-timer = 52 ---------------------------
    for _ in range(1):
        employees.append(make(
            names.pop(), gender=next_gender(),
            skills=[ServiceCode.EXERCISE, ServiceCode.HOME_CLEAN,
                    ServiceCode.ESCORT, ServiceCode.MEAL],
            home_team="IH", routes=_pick_routes(rng, 3),
        ))
    employees.append(make(
        names.pop(), gender=next_gender(),
        skills=[ServiceCode.MEAL], home_team="EH",
        routes=_pick_routes(rng, 2), notes="兼職（PT）",
        employment_type="part",
    ))
    assert len(employees) == 52
    return employees


def _build_elders_and_services(
    rng: random.Random, employees: list[Employee], ids: _Ids,
) -> tuple[list[Elder], list[FixedService]]:
    elders: list[Elder] = []
    services: list[FixedService] = []

    # slot occupancy: (worker_id, weekday, period, session) -> list[WeekPattern]
    occupancy: dict[tuple[str, int, str, int], list[WeekPattern]] = {}
    # escort-heavy workers keep free capacity: no fixed home visits for them
    escort_pool_ids = {w.id for w in employees
                       if ServiceCode.ESCORT in w.skills
                       and ServiceCode.EXERCISE not in w.skills
                       and ServiceCode.BATH not in w.skills
                       and ServiceCode.HOME_CLEAN not in w.skills}

    def qualified(code: ServiceCode, district: str,
                  gender_req: GenderRequirement) -> list[Employee]:
        out = []
        for w in employees:
            if w.id in escort_pool_ids:
                continue
            if code not in w.skills:
                continue
            if gender_req in (GenderRequirement.MALE, GenderRequirement.FEMALE):
                if w.gender is None or w.gender.value != gender_req.value:
                    continue
            out.append(w)
        # same-district workers first, stable order for determinism
        out.sort(key=lambda w: (district not in w.routes, w.id))
        return out

    def place(worker: Employee, pattern: WeekPattern) -> tuple[int, str, int] | None:
        """Find a free (weekday, period, session) slot compatible with pattern."""
        days = list(range(1, 6))
        rng.shuffle(days)
        for weekday in days:
            for period in (Period.AM, Period.PM):
                for session in (1, 2):
                    key = (worker.id, weekday, period.value, session)
                    existing = occupancy.get(key, [])
                    if all(not pattern.overlaps(p) for p in existing):
                        occupancy.setdefault(key, []).append(pattern)
                        return weekday, period.value, session
        return None

    def add_service(elder: Elder, code: ServiceCode, pattern: WeekPattern,
                    *, exclusive: bool = False, worker: Employee | None = None,
                    notes: str | None = None) -> FixedService | None:
        pool = [worker] if worker else qualified(code, elder.district,
                                                 elder.gender_requirement)
        for cand in pool[:8]:
            if cand is None:
                continue
            slot = place(cand, pattern)
            if slot:
                weekday, period, session = slot
                st, et = _session_time(Period(period), session)
                fs = FixedService(
                    id=ids.next("FS"), elder_id=elder.id, service_code=code,
                    weekday=weekday, period=Period(period), session_index=session,  # type: ignore[arg-type]
                    start_time=st, end_time=et, week_pattern=pattern,
                    assigned_worker_id=cand.id, is_exclusive=exclusive,
                    district=elder.district, notes=notes,
                )
                services.append(fs)
                return fs
        return None

    def new_elder(*, district: str | None = None, gender: Gender | None = "auto",
                  gender_req: GenderRequirement = GenderRequirement.ANY,
                  unit: str = "EH", name: str | None = None,
                  exclusive_worker: str | None = None,
                  notes: str | None = None) -> Elder:
        if gender == "auto":
            gender = Gender.FEMALE if rng.random() < 0.7 else Gender.MALE
        elder = Elder(
            id=ids.next("E"),
            display_name=name or (rng.choice(ELDER_SURNAME_LETTERS) + rng.choice(ELDER_GIVEN)),
            gender=gender,  # type: ignore[arg-type]
            district=district or rng.choice(DISTRICTS),
            owning_unit=unit,
            gender_requirement=gender_req,
            exclusive_worker_id=exclusive_worker,
            notes=notes,
        )
        elders.append(elder)
        return elder

    def add_service_at(elder: Elder, code: ServiceCode, worker: Employee,
                       weekday: int, period: Period, session: int,
                       *, exclusive: bool = False,
                       notes: str | None = None) -> FixedService:
        """Deterministic slot placement for edge-case scenarios."""
        pattern = WeekPattern()
        key = (worker.id, weekday, period.value, session)
        occupancy.setdefault(key, []).append(pattern)
        st, et = _session_time(period, session)
        fs = FixedService(
            id=ids.next("FS"), elder_id=elder.id, service_code=code,
            weekday=weekday, period=period, session_index=session,  # type: ignore[arg-type]
            start_time=st, end_time=et, week_pattern=pattern,
            assigned_worker_id=worker.id, is_exclusive=exclusive,
            district=elder.district, notes=notes,
        )
        services.append(fs)
        return fs

    # --- Edge cases with stable ids ---------------------------------------
    # E0001-E0003: exclusive to 娥 (W001), pinned to Monday so the demo leave
    # event (W001 Monday AM) predictably cancels E0001+E0002.
    w001 = next(w for w in employees if w.id == "W001")
    edge_slots = [(1, Period.AM, 1), (1, Period.AM, 2), (1, Period.PM, 1)]
    for i in range(3):
        e = new_elder(district="柴灣", unit="IH", exclusive_worker="W001",
                      notes="只要娥姐")
        weekday, period, session = edge_slots[i]
        add_service_at(e, ServiceCode.EXERCISE, w001, weekday, period, session,
                       exclusive=True, notes="只要娥姐")
    # E0004: male-required bath, only 志明 (W003) qualifies.
    e_male_bath = new_elder(district="北角", gender=Gender.MALE,
                            gender_req=GenderRequirement.MALE, unit="IH",
                            notes="要求男同工沖涼")
    add_service(e_male_bath, ServiceCode.BATH, WeekPattern(),
                worker=next(w for w in employees if w.id == "W003"))
    # E0005: unknown gender (data gap) — escorts for them trigger review.
    new_elder(district="灣仔", gender=None, unit="ED", notes="性別資料缺失")
    # E0006/E0007: alias collision (same display name, different districts).
    new_elder(district="灣仔", name="C蓮", unit="EH")
    new_elder(district="柴灣", name="C蓮", unit="IH")
    # E0008: template worker lacks skill (import-noise simulation) — assign
    # HC to an escort-pool worker who has no HC skill; baseline must flag it.
    e_bad = new_elder(district="筲箕灣", unit="EH", notes="模擬匯入錯誤")
    # pick a new joiner (end of the pool) so the edge case doesn't collide
    # with W002's leave scenario
    bad_worker = [w for w in employees if w.id in escort_pool_ids][-1]
    st, et = _session_time(Period.AM, 1)
    services.append(FixedService(
        id=ids.next("FS"), elder_id=e_bad.id, service_code=ServiceCode.HOME_CLEAN,
        weekday=2, period=Period.AM, session_index=1, start_time=st, end_time=et,
        week_pattern=WeekPattern(), assigned_worker_id=bad_worker.id,
        district=e_bad.district, notes="模擬：模板同工無此技能",
    ))

    # --- EX_RO recipients (165) -------------------------------------------
    for i in range(165):
        exclusive = rng.random() < 0.30
        e = new_elder(unit="EH" if rng.random() < 0.6 else "IH")
        fs = add_service(e, ServiceCode.EXERCISE, WeekPattern(), exclusive=exclusive,
                         notes="運動訓練固定同工" if exclusive else None)
        if fs and exclusive:
            e.exclusive_worker_id = fs.assigned_worker_id
        if fs and rng.random() < 0.25:  # second weekly session, same worker
            w = next(x for x in employees if x.id == fs.assigned_worker_id)
            add_service(e, ServiceCode.EXERCISE, WeekPattern(), exclusive=exclusive,
                        worker=w)

    # --- HC recipients (80) with week-of-month patterns --------------------
    hc_patterns = (["1,3"] * 20 + ["2,4"] * 20 + ["1"] * 10 + ["2"] * 8 +
                   ["3"] * 8 + ["4"] * 6 + ["單月"] * 4 + ["雙月"] * 4)
    for pat in hc_patterns:
        e = new_elder(unit="IH" if rng.random() < 0.5 else "EH")
        add_service(e, ServiceCode.HOME_CLEAN, WeekPattern.parse(pat))

    # --- Bath (16 more) & PC (10) ------------------------------------------
    for i in range(16):
        req = GenderRequirement.FEMALE if i % 8 else GenderRequirement.ANY
        e = new_elder(gender_req=req, unit="IH")
        add_service(e, ServiceCode.BATH, WeekPattern())
    for i in range(10):
        e = new_elder(gender_req=GenderRequirement.FEMALE, unit="IH")
        add_service(e, ServiceCode.PERSONAL_CARE,
                    WeekPattern.parse("2,4") if i % 2 else WeekPattern())

    # --- Meal-only elders (fill to 320) ------------------------------------
    while len(elders) < 320:
        new_elder(unit="EH", notes="送飯服務（路線安排）")

    # --- Meal route template tasks (route-level, no individual elder) ------
    route_workers = [w for w in employees if ServiceCode.MEAL in w.skills]
    for r_i, route in enumerate(MEAL_ROUTES):
        district = ROUTE_DISTRICT[route]
        cands = sorted(route_workers, key=lambda w: (district not in w.routes, w.id))
        for weekday in range(1, 6):
            pattern = WeekPattern()
            for cand in cands:
                key = (cand.id, weekday, Period.AM.value, 2)
                if all(not pattern.overlaps(p) for p in occupancy.get(key, [])):
                    occupancy.setdefault(key, []).append(pattern)
                    st, et = _session_time(Period.AM, 2)
                    services.append(FixedService(
                        id=ids.next("FS"), service_code=ServiceCode.MEAL,
                        weekday=weekday, period=Period.AM, session_index=2,  # type: ignore[arg-type]
                        start_time=st, end_time=et, week_pattern=pattern,
                        assigned_worker_id=cand.id, district=district, route=route,
                    ))
                    break

    # --- Kitchen duty template (both periods, kitchen-segment workers only;
    # centre-attached workers with kitchen skill stay free for centre duty) --
    for w in employees:
        if ServiceCode.KITCHEN not in w.skills or w.home_team in CENTERS:
            continue
        for weekday in range(1, 6):
            for period in (Period.AM, Period.PM):
                key = (w.id, weekday, period.value, 1)
                pattern = WeekPattern()
                if all(not pattern.overlaps(p) for p in occupancy.get(key, [])):
                    occupancy.setdefault(key, []).append(pattern)
                    st, et = _session_time(period, 1)
                    services.append(FixedService(
                        id=ids.next("FS"), service_code=ServiceCode.KITCHEN,
                        weekday=weekday, period=period, session_index=1,  # type: ignore[arg-type]
                        start_time=st, end_time=et, week_pattern=pattern,
                        assigned_worker_id=w.id, district="柴灣",
                        notes="執牌(柴灣廚房)",
                    ))
    return elders, services


def _build_escorts(rng: random.Random, elders: list[Elder], ids: _Ids,
                   week_start: date) -> list[EscortRequest]:
    """Escort week: Mon 4+2, Tue 3+3, Wed 5+2 (over nominal baseline),
    Thu 2+2 (under), Fri 4+3, Sat 1+0 = 31 requests."""
    plan = {
        (1, Period.AM): 4, (1, Period.PM): 2,
        (2, Period.AM): 3, (2, Period.PM): 3,
        (3, Period.AM): 5, (3, Period.PM): 2,
        (4, Period.AM): 2, (4, Period.PM): 2,
        (5, Period.AM): 4, (5, Period.PM): 3,
        (6, Period.AM): 1, (6, Period.PM): 0,
    }
    escort_elders = [e for e in elders if e.status == "active"]
    rng.shuffle(escort_elders)
    pool = iter(escort_elders)
    requests: list[EscortRequest] = []
    for (weekday, period), count in plan.items():
        for i in range(count):
            elder = next(pool)
            dest, subject = rng.choice(DESTINATIONS)
            hour = rng.choice([9, 10, 11]) if period == Period.AM else rng.choice([14, 15, 16])
            requests.append(EscortRequest(
                id=ids.next("ER"),
                service_date=week_start + timedelta(days=weekday - 1),
                period=period, elder_id=elder.id,
                appointment_time=time(hour, rng.choice([0, 15, 30, 45])),
                destination=dest, subject=subject,
                transport=rng.choice(TRANSPORTS),
                gender_requirement=(GenderRequirement.FEMALE if rng.random() < 0.15
                                    else GenderRequirement.ANY),
            ))
    # Edge case: Thursday-AM escort for the unknown-gender elder (E0005) with
    # a same-gender requirement: the elder's gender is unknown, so the
    # requirement is UNKNOWN -> unverifiable -> data-gap review (fail-safe).
    requests.append(EscortRequest(
        id=ids.next("ER"),
        service_date=week_start + timedelta(days=3), period=Period.AM,
        elder_id="E0005", appointment_time=time(10, 0),
        destination="RH", subject="老人科", transport="的士來回",
        gender_requirement=GenderRequirement.UNKNOWN,
        notes="要求同性別同工，但長者性別資料缺失（data gap）",
    ))
    # Edge case: 'must' preference for W001 (娥), who is busy with exclusive
    # E+RO visits — preference cannot be honoured without review.
    requests.append(EscortRequest(
        id=ids.next("ER"),
        service_date=week_start, period=Period.AM,
        elder_id=elders[0].id, appointment_time=time(9, 30),
        destination="PY", subject="覆診", transport="的士來回",
        preferred_worker_id="W001", preference_strength="must",
        notes="只要娥姐陪診",
    ))
    return requests


def _build_duty_requirements() -> list[CenterDutyRequirement]:
    reqs: list[CenterDutyRequirement] = []
    plan = {"AMC": (3, 2), "MRC": (2, 2), "GC": (2, 2)}
    for center, (am, pm) in plan.items():
        for weekday in range(1, 6):
            reqs.append(CenterDutyRequirement(center=center, weekday=weekday,  # type: ignore[arg-type]
                                              period=Period.AM, required_count=am))
            reqs.append(CenterDutyRequirement(center=center, weekday=weekday,  # type: ignore[arg-type]
                                              period=Period.PM, required_count=pm))
    # Saturday: MRC only (observed in the real Saturday block; unconfirmed).
    reqs.append(CenterDutyRequirement(center="MRC", weekday=6, period=Period.AM,
                                      required_count=2))
    return reqs


def generate_dataset(seed: int = DEFAULT_SEED,
                     week_start: date = DEFAULT_WEEK_START) -> MockDataset:
    rng = random.Random(seed)
    ids = _Ids()
    employees = _build_employees(rng)
    elders, services = _build_elders_and_services(rng, employees, ids)
    escorts = _build_escorts(rng, elders, ids, week_start)
    return MockDataset(
        seed=seed,
        employees=employees,
        elders=elders,
        fixed_services=services,
        escort_requests=escorts,
        duty_requirements=_build_duty_requirements(),
        params=ScheduleParams(week_start=week_start, districts=DISTRICTS),
    )


def example_changes(dataset: MockDataset) -> list[ChangeEvent]:
    """Demo change events referencing stable edge-case ids."""
    ws = dataset.params.week_start
    tue, wed, thu, fri = (ws + timedelta(days=d) for d in (1, 2, 3, 4))
    first_fri_escort = next(
        (r for r in dataset.escort_requests
         if r.service_date == fri and r.period == Period.PM), None)
    events = [
        ChangeEvent(id="EV1", type=ChangeType.LEAVE, change_date=tue,
                    worker_id="W002", reason="嘉偉全日病假（護送主力）"),
        ChangeEvent(id="EV2", type=ChangeType.LEAVE, change_date=ws,
                    period=Period.AM, worker_id="W001",
                    reason="娥上午請假（專屬運動訓練同工）"),
        ChangeEvent(id="EV3", type=ChangeType.ELDER_CANCELLATION,
                    change_date=thu,
                    elder_id=next(
                        fs.elder_id for fs in dataset.fixed_services
                        if fs.weekday == 4 and not fs.is_exclusive
                        and fs.elder_id and fs.week_pattern.matches(thu)),
                    reason="長者入院"),
        ChangeEvent(id="EV4", type=ChangeType.ESCORT_NEW, change_date=wed,
                    period=Period.AM,
                    new_escort=EscortRequest(
                        id="ER-EXTRA1", service_date=wed, period=Period.AM,
                        elder_id=dataset.elders[10].id,
                        appointment_time=time(10, 30), destination="東區醫院",
                        subject="眼科", transport="的士來回"),
                    reason="臨時新增護送（超出當日基準）"),
    ]
    if first_fri_escort:
        events.append(ChangeEvent(
            id="EV5", type=ChangeType.ESCORT_CANCELLED, change_date=fri,
            period=Period.PM, escort_request_id=first_fri_escort.id,
            elder_id=first_fri_escort.elder_id, reason="長者取消覆診"))
    return events
