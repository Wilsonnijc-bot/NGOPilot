"""Task generation layer — snapshot demands → concrete dated tasks.

This module is the single authority for *what work exists* in the target week.
It expands the normalized ``SchedulerSnapshot`` inputs into a flat list of
dated :class:`~app.domain.snapshot.TaskDemand` items that the engine adapter
then lowers into schedulable domain objects.

Expansion rules (docs/spec/rulebook.md, docs/spec/ENGINEERING_SPEC.md §5):

* fixed services / HC patterns / meal routes → one dated task per weekday
  occurrence that matches the demand's week pattern (RB-FIX-02 week-of-month);
* escort requests → a whole-half-day occupancy task (RB-ESC-01, Q-B5);
* centre duty requirements → ``required_count`` duty tasks per slot (RB-DUTY-01);
* elder cancellation / hospitalisation → the matching demand is *suppressed*
  (represented, never silently dropped — RB-DATA-01);
* worker leave → a :class:`ChangeEvent` for the repair pass, plus availability.

The generator never opens Excel. It shares :class:`WeekPattern` semantics with
the engine, so its dated set is consistent with what the scheduler places.
"""
from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel, Field, model_validator

from ..domain import (
    CenterDutyRequirement,
    ChangeEvent,
    ChangeType,
    DataGap,
    ExcludedSourceRecord,
    Period,
    SchedulerSnapshot,
    ServiceCode,
    SKILL_GATED,
    SourceEvidence,
    TaskDemand,
    TaskKind,
    TaskSource,
    canonical_json,
    content_fingerprint,
    merge_source_evidence,
    stable_id,
)

# Demand kinds that come from recurring templates and need weekday-of-week dating.
_RECURRING_KINDS = {
    TaskKind.FIXED_SERVICE,
    TaskKind.HC_PATTERN,
    TaskKind.MEAL_LOGISTICS,
}
# Demand statuses that mean "exists but is not schedulable this week".
_SUPPRESSED_STATUSES = {"cancelled", "hospitalised", "leave"}


class GeneratedDemands(BaseModel):
    """Result of expanding a snapshot into concrete dated demand for one week."""

    week_start: date
    tasks: list[TaskDemand] = Field(default_factory=list)
    suppressed: list[TaskDemand] = Field(default_factory=list)
    suppressed_weekly_demands: list[TaskDemand] = Field(default_factory=list)
    change_demands: list[TaskDemand] = Field(default_factory=list)
    excluded_source_records: list[ExcludedSourceRecord] = Field(default_factory=list)
    duty_requirements: list[CenterDutyRequirement] = Field(default_factory=list)
    leave_events: list[ChangeEvent] = Field(default_factory=list)
    data_gaps: list[DataGap] = Field(default_factory=list)
    source_evidence: list[SourceEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def _canonical_registries(self) -> "GeneratedDemands":
        self.source_evidence = merge_source_evidence(self.source_evidence)
        self.data_gaps = _dedupe_gaps(self.data_gaps)
        return self

    @property
    def counts_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for task in self.tasks:
            counts[task.kind.value] = counts.get(task.kind.value, 0) + 1
        return counts

    def tasks_of(self, kind: TaskKind) -> list[TaskDemand]:
        return [t for t in self.tasks if t.kind == kind]

    @property
    def weekly_demands(self) -> list[TaskDemand]:
        return [*self.tasks, *self.suppressed_weekly_demands, *self.change_demands]


def week_dates(week_start: date) -> list[date]:
    """Mon..Sat of the target week (Sunday is never scheduled, RB-TIME-03)."""
    return [week_start + timedelta(days=i) for i in range(6)]


def duty_requirements(snapshot: SchedulerSnapshot) -> list[CenterDutyRequirement]:
    """Collapse configured placeholders + explicit CENTRE_DUTY demands into
    one :class:`CenterDutyRequirement` per (centre, weekday, period).

    Explicit operator demands win over configured placeholders for the same
    slot, because a placeholder is an unconfirmed assumption (RB-DUTY-01).
    """
    reqs: dict[tuple[str, int, str], CenterDutyRequirement] = {}
    for placeholder in snapshot.config.centre_duty_placeholders:
        for weekday in placeholder.weekdays:
            for period in placeholder.periods:
                key = (placeholder.centre, weekday, period.value)
                reqs[key] = CenterDutyRequirement(
                    center=placeholder.centre,
                    weekday=weekday,  # type: ignore[arg-type]
                    period=period,
                    required_count=placeholder.required_count,
                )
    for demand in snapshot.demands:
        if demand.kind != TaskKind.CENTRE_DUTY or demand.centre is None:
            continue
        weekday = _weekday_of(demand, snapshot.week_start)
        if weekday is None or demand.period is None:
            continue
        key = (demand.centre, weekday, demand.period.value)
        reqs[key] = CenterDutyRequirement(
            center=demand.centre,
            weekday=weekday,  # type: ignore[arg-type]
            period=demand.period,
            required_count=demand.required_count,
        )
    return sorted(reqs.values(), key=lambda r: (r.center, r.weekday, r.period.value))


def generate_demands(snapshot: SchedulerSnapshot) -> GeneratedDemands:
    """Expand a snapshot into concrete dated demand for its target week."""
    tasks: list[TaskDemand] = []
    suppressed: list[TaskDemand] = []
    suppressed_weekly: list[TaskDemand] = []
    change_demands: list[TaskDemand] = []
    exclusions: list[ExcludedSourceRecord] = list(snapshot.excluded_source_records)
    data_gaps: list[DataGap] = list(snapshot.data_gaps)
    week = snapshot.week_start
    dates = set(week_dates(week))

    input_demands = [*snapshot.demands, *_configured_duty_demands(snapshot)]
    for raw_demand in input_demands:
        demand = _with_provenance(raw_demand)
        data_gaps.extend(demand.data_gaps)

        if demand.kind in _RECURRING_KINDS:
            dated = _expand_recurring(demand, week)
            if dated is None:
                excluded = _note(demand, "week_pattern_not_matched")
                suppressed.append(excluded)
                exclusions.append(_exclusion(excluded, "week_pattern_not_matched"))
            elif demand.status in _SUPPRESSED_STATUSES:
                weekly = _note(dated, f"suppressed:{demand.status}")
                suppressed.append(weekly)
                suppressed_weekly.append(weekly)
            else:
                tasks.append(dated)
        elif demand.kind == TaskKind.ESCORT:
            if demand.task_date not in dates:
                excluded = _note(demand, "escort_outside_target_week")
                suppressed.append(excluded)
                exclusions.append(_exclusion(excluded, "outside_target_week"))
            elif demand.status in _SUPPRESSED_STATUSES:
                weekly = _note(_as_escort(demand), f"suppressed:{demand.status}")
                suppressed.append(weekly)
                suppressed_weekly.append(weekly)
            else:
                tasks.append(_as_escort(demand))
        elif demand.kind == TaskKind.CENTRE_DUTY:
            expanded = _expand_duty(demand, week)
            if demand.status in _SUPPRESSED_STATUSES:
                weekly = [_note(item, f"suppressed:{demand.status}") for item in expanded]
                suppressed.extend(weekly)
                suppressed_weekly.extend(weekly)
            else:
                tasks.extend(expanded)
        # LEAVE_EVENT / CANCELLATION_EVENT demands carry no schedulable work;
        # disruptions travel through change_events instead.

    leave_events = _collect_leave_events(snapshot)
    data_gaps.extend(_event_target_gaps(snapshot, leave_events))
    change_demands = _change_demands(leave_events, dates)
    gap_by_id = {gap.id: gap for gap in data_gaps}
    change_demands = [
        demand.model_copy(update={
            "data_gaps": [
                gap_by_id[gap_id] for gap_id in demand.data_gap_ids
                if gap_id in gap_by_id
            ],
        })
        for demand in change_demands
    ]
    all_weekly = _finalize_demand_ids([*tasks, *suppressed_weekly, *change_demands])
    active_count = len(tasks)
    suppressed_count = len(suppressed_weekly)
    tasks = all_weekly[:active_count]
    suppressed_weekly = all_weekly[active_count:active_count + suppressed_count]
    change_demands = all_weekly[active_count + suppressed_count:]
    route_gaps, route_evidence = _route_uncertainty_gaps(tasks, snapshot.workers)
    data_gaps.extend(route_gaps)
    skill_gaps, skill_evidence = _skill_uncertainty_gaps(tasks, snapshot.workers)
    data_gaps.extend(skill_gaps)
    canonical_gaps = _dedupe_gaps(data_gaps)
    gap_by_id = {gap.id: gap for gap in canonical_gaps}
    all_weekly = [
        demand.model_copy(update={
            "data_gaps": [
                gap_by_id[gap_id]
                for gap_id in sorted({
                    *demand.data_gap_ids,
                    *(gap.id for gap in demand.data_gaps),
                })
                if gap_id in gap_by_id
            ],
        })
        for demand in [*tasks, *suppressed_weekly, *change_demands]
    ]
    tasks = all_weekly[:active_count]
    suppressed_weekly = all_weekly[active_count:active_count + suppressed_count]
    change_demands = all_weekly[active_count + suppressed_count:]
    evidence_registry = merge_source_evidence((
            *snapshot.source_evidence,
            *[item for worker in snapshot.workers for item in worker.source_evidence],
            *[item for row in snapshot.availability for item in row.source_evidence],
            *[item for demand in all_weekly for item in demand.source_evidence],
            *[item for row in exclusions for item in row.source_evidence],
            *route_evidence,
            *skill_evidence,
            *[item for event in leave_events for item in event.source_evidence],
    ))
    evidence_by_id = {item.id: item for item in evidence_registry}

    def authoritative(items: list[SourceEvidence]) -> list[SourceEvidence]:
        return [evidence_by_id[item.id] for item in items if item.id in evidence_by_id]

    all_weekly = [
        demand.model_copy(update={
            "source_evidence": authoritative(demand.source_evidence),
        })
        for demand in all_weekly
    ]
    tasks = all_weekly[:active_count]
    suppressed_weekly = all_weekly[active_count:active_count + suppressed_count]
    change_demands = all_weekly[active_count + suppressed_count:]
    leave_events = [
        event.model_copy(update={
            "source_evidence": authoritative(event.source_evidence),
        })
        for event in leave_events
    ]
    exclusions = [
        row.model_copy(update={
            "source_evidence": authoritative(row.source_evidence),
        })
        for row in exclusions
    ]
    _copy_change_provenance(leave_events, change_demands)
    reqs = _duty_requirements_from_tasks(tasks)

    return GeneratedDemands(
        week_start=week,
        tasks=tasks,
        suppressed=suppressed,
        suppressed_weekly_demands=suppressed_weekly,
        change_demands=change_demands,
        excluded_source_records=sorted(
            exclusions, key=lambda row: (row.reason_code, row.source_record_id)),
        duty_requirements=reqs,
        leave_events=leave_events,
        data_gaps=canonical_gaps,
        source_evidence=evidence_registry,
    )


# --------------------------------------------------------------------------
# Expansion helpers
# --------------------------------------------------------------------------

def _weekday_of(demand: TaskDemand, week_start: date) -> int | None:
    if demand.task_date is not None:
        return demand.task_date.isoweekday()
    return demand.weekday


def _date_for(demand: TaskDemand, week_start: date) -> date | None:
    """The concrete date this demand fires on within the target week."""
    if demand.task_date is not None:
        return demand.task_date
    if demand.weekday is not None:
        return week_start + timedelta(days=demand.weekday - 1)
    return None


def _expand_recurring(demand: TaskDemand, week_start: date) -> TaskDemand | None:
    """Date a recurring template task, gated by its week-of-month pattern."""
    on = _date_for(demand, week_start)
    if on is None:
        return None
    if demand.week_pattern is not None and not demand.week_pattern.matches(on):
        return None
    return demand.model_copy(update={
        "task_date": on,
        "weekday": on.isoweekday(),
        "source": TaskSource.GENERATED,
    })


def _as_escort(demand: TaskDemand) -> TaskDemand:
    """Normalize an escort demand to whole-half-day occupancy (RB-ESC-01)."""
    return demand.model_copy(update={
        "session_index": None,
        "occupies_full_period": True,
        "weekday": demand.task_date.isoweekday() if demand.task_date else demand.weekday,
        "source": TaskSource.GENERATED,
    })


def _expand_duty(demand: TaskDemand, week_start: date) -> list[TaskDemand]:
    """One duty task per required head (RB-DUTY-01)."""
    on = _date_for(demand, week_start)
    out: list[TaskDemand] = []
    for i in range(demand.required_count):
        out.append(demand.model_copy(update={
            "id": f"{demand.id}#{i + 1}",
            "task_date": on,
            "weekday": on.isoweekday() if on else demand.weekday,
            "required_count": 1,
            "duplicate_ordinal": i + 1,
            "source": TaskSource.GENERATED,
        }))
    return out


def _collect_leave_events(snapshot: SchedulerSnapshot) -> list[ChangeEvent]:
    """Worker unavailability that should drive the repair pass as leave.

    Explicit ``change_events`` pass through untouched; structural
    ``availability`` rows with ``is_available=False`` and ``reason="leave"``
    become leave events so the engine marks affected entries instead of
    silently under-scheduling. Manual overrides are structural capacity locks
    consumed by the eligibility gate, not synthetic leave events.
    """
    events: list[ChangeEvent] = list(snapshot.change_events)
    # A slot already covered by an explicit leave event must not be re-emitted
    # from availability, or the repair pass would process the leave twice.
    covered: set[tuple[str | None, date, str | None]] = {
        (ev.worker_id, ev.change_date, ev.period.value if ev.period else None)
        for ev in snapshot.change_events
        if ev.type == ChangeType.LEAVE
    }
    for avail in snapshot.availability:
        if avail.is_available or avail.reason != "leave":
            continue
        if avail.available_date is None:
            continue
        period_value = avail.period.value if avail.period else None
        if (avail.worker_id, avail.available_date, period_value) in covered:
            continue
        identity = {
            "worker_id": avail.worker_id,
            "change_date": avail.available_date,
            "period": avail.period,
            "source": avail.source,
        }
        evidence = list(avail.source_evidence) or [SourceEvidence(
            kind="availability",
            source_id=f"worker:{avail.worker_id}",
            locator=(
                f"availability:{avail.worker_id}:{avail.available_date.isoformat()}:"
                f"{avail.period.value if avail.period else 'day'}"
            ),
            field="leave",
            content_fingerprint=content_fingerprint(identity),
            confidence="high",
        )]
        events.append(ChangeEvent(
            type=ChangeType.LEAVE,
            change_date=avail.available_date,
            period=avail.period,
            worker_id=avail.worker_id,
            reason=avail.notes or "availability marked unavailable",
            source_refs=list(avail.source_refs),
            source_evidence=evidence,
            data_gap_ids=list(avail.data_gap_ids),
            data_gap_policies=dict(avail.data_gap_policies),
        ))
    normalized_events: list[ChangeEvent] = []
    for event in events:
        if event.source_evidence:
            normalized_events.append(event)
            continue
        assert event.id is not None
        fingerprint = content_fingerprint(event.model_dump(
            mode="json",
            exclude={
                "reason", "source_refs", "source_evidence",
                "data_gap_ids", "data_gap_policies", "override_ids",
                "depends_on",
            },
        ))
        source_ref = f"change_event:{event.id}"
        normalized_events.append(event.model_copy(update={
            "source_refs": sorted({*event.source_refs, source_ref}),
            "source_evidence": [SourceEvidence(
                kind="weekly_change",
                source_id=event.id,
                locator=source_ref,
                field=event.type.value,
                content_fingerprint=fingerprint,
                confidence="high",
            )],
        }))

    by_id: dict[str, ChangeEvent] = {}
    for event in normalized_events:
        assert event.id is not None
        prior = by_id.get(event.id)
        if prior is not None:
            prior_identity = prior.model_dump(
                mode="json", exclude={
                    "reason", "source_refs", "source_evidence",
                    "data_gap_ids", "data_gap_policies", "override_ids",
                    "depends_on",
                }
            )
            event_identity = event.model_dump(
                mode="json", exclude={
                    "reason", "source_refs", "source_evidence",
                    "data_gap_ids", "data_gap_policies", "override_ids",
                    "depends_on",
                }
            )
            if canonical_json(prior_identity) != canonical_json(event_identity):
                raise ValueError(f"conflicting change events share ID {event.id}")
            merged_policies = dict(prior.data_gap_policies)
            for gap_id, policy in event.data_gap_policies.items():
                if gap_id in merged_policies and merged_policies[gap_id] != policy:
                    raise ValueError(
                        f"conflicting data-gap policy for change event {event.id}"
                    )
                merged_policies[gap_id] = policy
            by_id[event.id] = prior.model_copy(update={
                "reason": min(
                    (item for item in (prior.reason, event.reason) if item),
                    default=None,
                ),
                "source_refs": sorted({*prior.source_refs, *event.source_refs}),
                "source_evidence": merge_source_evidence(
                    prior.source_evidence, event.source_evidence
                ),
                "data_gap_ids": sorted({*prior.data_gap_ids, *event.data_gap_ids}),
                "data_gap_policies": merged_policies,
                "override_ids": sorted({*prior.override_ids, *event.override_ids}),
                "depends_on": sorted({*prior.depends_on, *event.depends_on}),
            })
            continue
        by_id[event.id] = event
    return sorted(
        by_id.values(),
        key=lambda event: (event.change_date, event.type.value, event.id or ""),
    )


def _event_target_gaps(
    snapshot: SchedulerSnapshot,
    events: list[ChangeEvent],
) -> list[DataGap]:
    """Turn a structurally valid but unresolved change target into a blocker."""

    worker_ids = {worker.id for worker in snapshot.workers}
    elder_ids = {elder.id for elder in snapshot.elders}
    escort_ids = {
        demand.id for demand in snapshot.demands if demand.kind == TaskKind.ESCORT
    }
    gaps: list[DataGap] = []
    for event in events:
        missing_field: str | None = None
        target: str | None = None
        if event.type == ChangeType.LEAVE and event.worker_id not in worker_ids:
            missing_field, target = "worker_id", event.worker_id
        elif (
            event.type == ChangeType.ELDER_CANCELLATION
            and event.elder_id not in elder_ids
        ):
            missing_field, target = "elder_id", event.elder_id
        elif (
            event.type == ChangeType.ESCORT_CANCELLED
            and event.escort_request_id not in escort_ids
        ):
            missing_field, target = "escort_request_id", event.escort_request_id
        elif (
            event.type == ChangeType.ESCORT_NEW
            and event.new_escort is not None
            and event.new_escort.elder_id not in elder_ids
        ):
            missing_field, target = "new_escort.elder_id", event.new_escort.elder_id
        if missing_field is None:
            continue
        gaps.append(DataGap(
            kind="other",
            entity_id=event.id,
            field=missing_field,
            message=(f"Change event {event.id} references unknown {missing_field} "
                     f"{target or ''}".rstrip()),
            blocking=True,
            policy="ineligible",
            reason_code=f"change_target_missing:{missing_field}",
            source_ref_ids=[item.id for item in event.source_evidence],
            source=TaskSource.WEEKLY_CHANGE,
        ))
    return gaps


def _note(demand: TaskDemand, note: str) -> TaskDemand:
    prefix = f"{demand.notes} | " if demand.notes else ""
    return demand.model_copy(update={"notes": f"{prefix}{note}"})


def _dedupe_gaps(gaps: list[DataGap]) -> list[DataGap]:
    by_id: dict[str, DataGap] = {}
    for gap in gaps:
        prior = by_id.get(gap.id)
        if prior is None:
            by_id[gap.id] = gap
            continue
        by_id[gap.id] = prior.model_copy(update={
            "blocking": prior.blocking or gap.blocking,
            "message": min(prior.message, gap.message),
            "source": min((prior.source, gap.source), key=lambda item: item.value),
        })
    return [by_id[gap_id] for gap_id in sorted(by_id)]


def _route_uncertainty_gaps(tasks, workers) -> tuple[list[DataGap], list[SourceEvidence]]:
    """Materialize only meal-route facts that this weekly solve may use."""

    routes = sorted({
        task.route for task in tasks
        if task.service_code == ServiceCode.MEAL and task.route
    })
    gaps: list[DataGap] = []
    generated_evidence: list[SourceEvidence] = []
    for worker in sorted(workers, key=lambda item: item.id):
        for route in routes:
            if route in worker.routes and route not in worker.seed_routes:
                continue
            if any(
                field == f"route_facts:{route}"
                and worker.data_gap_policies.get(gap_id) == "ineligible"
                for gap_id, field in worker.data_gap_fields.items()
            ):
                continue
            evidence_ids = sorted(
                item.id for item in worker.source_evidence
                if item.field == f"route_facts:{route}"
            )
            if not evidence_ids:
                evidence = SourceEvidence(
                    kind="worker_registry",
                    source_id=f"worker:{worker.id}",
                    locator=f"worker_registry:{worker.id}",
                    field=f"route_facts:{route}",
                    content_fingerprint=content_fingerprint({
                        "worker_id": worker.id,
                        "route": route,
                        "qualified": False,
                    }),
                    confidence="low",
                )
                generated_evidence.append(evidence)
                evidence_ids = [evidence.id]
            gaps.append(DataGap(
                kind="route",
                entity_id=worker.id,
                field=f"route_facts:{route}",
                reason_code=(
                    "meal_route_seed_unverified"
                    if route in worker.seed_routes
                    else "meal_route_unconfirmed"
                ),
                message=(
                    f"同工 {worker.id} 的送飯路線 {route} 資格尚未確認，"
                    "只可作待審建議。"
                ),
                blocking=False,
                policy="allowed_with_review",
                source_ref_ids=evidence_ids,
                source=TaskSource.OPERATOR_INPUT,
            ))
    return gaps, generated_evidence


def _skill_uncertainty_gaps(tasks, workers) -> tuple[list[DataGap], list[SourceEvidence]]:
    """Materialize missing skill facts only for services considered this week."""

    services = sorted({
        task.service_code for task in tasks
        if task.service_code in SKILL_GATED
    }, key=lambda item: item.value)
    gaps: list[DataGap] = []
    generated_evidence: list[SourceEvidence] = []
    for worker in sorted(workers, key=lambda item: item.id):
        for service in services:
            field = f"skill_facts:{service.value}"
            existing_gap = next((
                gap_id for gap_id, gap_field in worker.data_gap_fields.items()
                if gap_field == field
            ), None)
            if service in worker.skills and service not in worker.seed_skills:
                continue
            if existing_gap is not None:
                continue
            evidence_ids = sorted(
                item.id for item in worker.source_evidence if item.field == field
            )
            is_seed = service in worker.seed_skills
            if not evidence_ids:
                evidence = SourceEvidence(
                    kind="worker_registry",
                    source_id=f"worker:{worker.id}",
                    locator=f"worker_registry:{worker.id}",
                    field=field,
                    content_fingerprint=content_fingerprint({
                        "worker_id": worker.id,
                        "service": service,
                        "qualified": False if not is_seed else None,
                        "seed": is_seed,
                    }),
                    confidence="seed" if is_seed else "low",
                )
                generated_evidence.append(evidence)
                evidence_ids = [evidence.id]
            gaps.append(DataGap(
                kind="skill",
                entity_id=worker.id,
                field=field,
                reason_code=(
                    "seed_skill_unverified" if is_seed
                    else "worker_skill_unconfirmed"
                ),
                message=(
                    f"同工 {worker.id} 的 {service.value} 技能仍是 seed 資料。"
                    if is_seed else
                    f"同工 {worker.id} 沒有可確認的 {service.value} 技能資格。"
                ),
                blocking=False,
                policy="allowed_with_review" if is_seed else "ineligible",
                source_ref_ids=evidence_ids,
                source=TaskSource.OPERATOR_INPUT,
            ))
    return gaps, generated_evidence


def _with_provenance(demand: TaskDemand) -> TaskDemand:
    evidence = merge_source_evidence(demand.source_evidence)
    if not evidence:
        locator = next((ref for ref in sorted(demand.source_refs) if ref), None)
        evidence = [SourceEvidence(
            kind=demand.source.value,
            source_id=demand.id,
            locator=locator,
            field="weekly_demand",
            confidence="high",
        )]
    primary_evidence_id = demand.primary_source_evidence_id
    if primary_evidence_id is None:
        if len(evidence) != 1:
            raise ValueError(
                f"weekly demand {demand.id} with multiple evidence rows requires "
                "primary_source_evidence_id"
            )
        primary_evidence_id = evidence[0].id
    if primary_evidence_id not in {item.id for item in evidence}:
        raise ValueError(
            f"weekly demand {demand.id} primary source evidence is not registered"
        )
    gaps = list(demand.data_gaps)
    return demand.model_copy(update={
        "source_evidence": evidence,
        "primary_source_evidence_id": primary_evidence_id,
        "data_gaps": gaps,
        "data_gap_ids": sorted({*demand.data_gap_ids, *(gap.id for gap in gaps)}),
    })


def _finalize_demand_ids(demands: list[TaskDemand]) -> list[TaskDemand]:
    groups: dict[str, list[tuple[int, TaskDemand]]] = {}
    for index, demand in enumerate(demands):
        if demand.task_date is None:
            raise ValueError(f"weekly demand {demand.id} has no concrete date")
        groups.setdefault(canonical_json(_demand_occurrence_identity(demand)), []).append(
            (index, demand)
        )

    ordinals: dict[int, int] = {}
    for rows in groups.values():
        if len(rows) == 1:
            ordinals[rows[0][0]] = rows[0][1].duplicate_ordinal
            continue
        explicit = [row.duplicate_ordinal for _, row in rows]
        if len(set(explicit)) == len(explicit) and set(explicit) == set(range(1, len(rows) + 1)):
            for index, row in rows:
                ordinals[index] = row.duplicate_ordinal
            continue
        ordered = sorted(rows, key=lambda pair: _demand_source_sort_key(pair[1]))
        source_keys = [_demand_source_sort_key(row) for _, row in ordered]
        if len(set(source_keys)) != len(source_keys):
            raise ValueError(
                "indistinguishable duplicate weekly demand source evidence"
            )
        for ordinal, (index, _) in enumerate(ordered, start=1):
            ordinals[index] = ordinal

    finalized: list[TaskDemand] = []
    for index, demand in enumerate(demands):
        evidence_ids = sorted(item.id for item in demand.source_evidence)
        if not evidence_ids or not demand.primary_source_evidence_id:
            raise ValueError(f"weekly demand {demand.id} has no source evidence")
        duplicate_ordinal = ordinals[index]
        demand_id = stable_id("dem_", "weekly_demand", {
            "source_evidence_id": demand.primary_source_evidence_id,
            **_demand_occurrence_identity(demand),
            "duplicate_ordinal": duplicate_ordinal,
        })
        finalized.append(demand.model_copy(update={
            "demand_id": demand_id,
            "duplicate_ordinal": duplicate_ordinal,
        }))
    return finalized


def _demand_occurrence_identity(demand: TaskDemand) -> dict[str, object]:
    return {
        "dated_occurrence": demand.task_date,
        "service": demand.service_code.value if demand.service_code else None,
        "elder": demand.elder_id,
        "centre": demand.centre,
        "route": demand.route,
        "period": demand.period.value if demand.period else None,
        "session": demand.session_index,
    }


def _demand_source_sort_key(demand: TaskDemand) -> str:
    return canonical_json({
        "source_evidence": sorted(
            (item.model_dump(mode="json") for item in demand.source_evidence),
            key=lambda item: item["id"],
        ),
        "source_refs": sorted(demand.source_refs),
    })


def _exclusion(demand: TaskDemand, reason: str) -> ExcludedSourceRecord:
    return ExcludedSourceRecord(
        source_record_id=demand.id,
        reason_code=reason,  # type: ignore[arg-type]
        source_evidence=list(demand.source_evidence),
        detail=demand.notes,
    )


def _configured_duty_demands(snapshot: SchedulerSnapshot) -> list[TaskDemand]:
    explicit = {
        (d.centre, _weekday_of(d, snapshot.week_start), d.period)
        for d in snapshot.demands
        if d.kind == TaskKind.CENTRE_DUTY
    }
    out: list[TaskDemand] = []
    for placeholder in snapshot.config.centre_duty_placeholders:
        for weekday in placeholder.weekdays:
            for period in placeholder.periods:
                if (placeholder.centre, weekday, period) in explicit:
                    continue
                source_id = (
                    f"{snapshot.config.version}:{placeholder.centre}:"
                    f"{weekday}:{period.value}"
                )
                out.append(TaskDemand(
                    id=f"config-duty:{source_id}",
                    kind=TaskKind.CENTRE_DUTY,
                    source=TaskSource.RULEBOOK,
                    service_code=ServiceCode(placeholder.centre),
                    weekday=weekday,
                    period=period,
                    required_count=placeholder.required_count,
                    centre=placeholder.centre,
                    assumptions=[item for item in [placeholder.assumption] if item],
                    source_refs=[f"scheduler_config:{source_id}"],
                    source_evidence=[SourceEvidence(
                        kind="rule_config",
                        source_id=source_id,
                        source_version=snapshot.config.version,
                        locator=f"centre_duty:{placeholder.centre}:{weekday}:{period.value}",
                        field="required_count",
                        confidence="seed" if placeholder.assumption else "medium",
                    )],
                ))
    return out


def _duty_requirements_from_tasks(tasks: list[TaskDemand]) -> list[CenterDutyRequirement]:
    grouped: dict[tuple[str, int, str], list[TaskDemand]] = {}
    for task in tasks:
        if task.kind != TaskKind.CENTRE_DUTY or task.centre is None \
                or task.weekday is None or task.period is None:
            continue
        grouped.setdefault((task.centre, task.weekday, task.period.value), []).append(task)
    out: list[CenterDutyRequirement] = []
    for (centre, weekday, period), rows in sorted(grouped.items()):
        rows.sort(key=lambda row: row.demand_id or "")
        out.append(CenterDutyRequirement(
            center=centre,
            weekday=weekday,  # type: ignore[arg-type]
            period=Period(period),
            required_count=len(rows),
            demand_ids=[row.demand_id for row in rows if row.demand_id],
            source_refs=sorted({ref for row in rows for ref in row.source_refs}),
            source_evidence=merge_source_evidence(
                item for row in rows for item in row.source_evidence
            ),
            data_gap_ids=sorted({gap for row in rows for gap in row.data_gap_ids}),
            data_gap_policies={
                gap_id: next(
                    (
                        gap.policy
                        for row in rows for gap in row.data_gaps
                        if gap.id == gap_id
                    ),
                    "ineligible",
                )
                for gap_id in sorted({
                    gap_id for row in rows for gap_id in row.data_gap_ids
                })
            },
            assumptions=sorted({value for row in rows for value in row.assumptions}),
            override_ids=sorted({value for row in rows for value in row.override_ids}),
            depends_on=sorted({value for row in rows for value in row.depends_on}),
        ))
    return out


def _change_demands(events: list[ChangeEvent], dates: set[date]) -> list[TaskDemand]:
    out: list[TaskDemand] = []
    for event in events:
        req = event.new_escort
        if event.type != ChangeType.ESCORT_NEW or req is None or req.service_date not in dates:
            continue
        evidence = merge_source_evidence(event.source_evidence, req.source_evidence)
        if not evidence:
            raise ValueError(f"new escort change {event.id} has no source evidence")
        primary_evidence_id = (
            event.source_evidence[0].id if event.source_evidence else evidence[0].id
        )
        out.append(_with_provenance(TaskDemand(
            id=req.id,
            kind=TaskKind.ESCORT,
            source=TaskSource.WEEKLY_CHANGE,
            service_code=ServiceCode.ESCORT,
            task_date=req.service_date,
            weekday=req.service_date.isoweekday(),
            period=req.period,
            session_index=None,
            occupies_full_period=True,
            elder_id=req.elder_id,
            preferred_worker_id=req.preferred_worker_id,
            preference_strength=req.preference_strength,
            destination=req.destination,
            start_time=req.appointment_time,
            source_refs=sorted({*event.source_refs, *req.source_refs}),
            source_evidence=evidence,
            primary_source_evidence_id=primary_evidence_id,
            data_gap_ids=sorted({*event.data_gap_ids, *req.data_gap_ids}),
            assumptions=list(req.assumptions),
            override_ids=sorted({*req.override_ids, *event.override_ids}),
            depends_on=sorted({*req.depends_on, *event.depends_on}),
            notes=req.notes or req.subject,
        )))
    return out


def _copy_change_provenance(events: list[ChangeEvent], demands: list[TaskDemand]) -> None:
    by_source_id = {d.id: d for d in demands}
    for event in events:
        if event.new_escort is None:
            continue
        demand = by_source_id.get(event.new_escort.id)
        if demand is None:
            continue
        event.new_escort = event.new_escort.model_copy(update={
            "demand_id": demand.demand_id,
            "source_refs": list(demand.source_refs),
            "source_evidence": list(demand.source_evidence),
            "data_gap_ids": list(demand.data_gap_ids),
            "data_gap_policies": {
                gap.id: gap.policy for gap in demand.data_gaps
            },
            "assumptions": list(demand.assumptions),
            "override_ids": list(demand.override_ids),
            "depends_on": list(demand.depends_on),
        })
