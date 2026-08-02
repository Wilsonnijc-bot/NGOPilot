"""Demo builder for the NGO weekly-roster workflow.

This is deliberately a thin orchestration layer around the scheduler-first
contract: Excel files are parsed upstream, promoted into a conservative
``SchedulerSnapshot``, then the existing greedy/repair engine drafts the roster.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable

from ..domain import (
    ChangeEvent,
    ChangeType,
    DataGap,
    Elder,
    EscortRequest,
    ExcludedSourceRecord,
    GenderRequirement,
    MasterDataSet,
    Period,
    SchedulerSnapshot,
    ServiceCode,
    SourceEvidence,
    TaskDemand,
    TaskKind,
    TaskSource,
    WorkerAvailability,
    content_fingerprint,
    stable_id,
)
from ..importer import (
    DivisionImportResult,
    parse_division_workbook,
    parse_escort_workbook,
    parse_hc_timetable_workbook,
)
from ..importer.base import ImportResult
from ..importer.models import ParsedRecord, SourceRef
from .master_data_bridge import (
    DEFAULT_DIVISION_TEMPLATE,
    bootstrap_master_data_from_division,
    lower_master_data,
)

MasterDataProvider = Callable[[DivisionImportResult], MasterDataSet | None]


@dataclass
class WeeklyRosterDemoBuild:
    snapshot: SchedulerSnapshot
    division: DivisionImportResult
    hc: ImportResult[dict[str, Any]]
    escort: ImportResult[dict[str, Any]]
    source_counts: dict[str, int]
    warnings: list[str] = field(default_factory=list)
    change_summaries: list[str] = field(default_factory=list)

    @property
    def ambiguity_count(self) -> int:
        return (
            len(self.division.ambiguities)
            + len(self.hc.ambiguities)
            + len(self.escort.ambiguities)
        )


class WeeklyRosterDemoBuilder:
    """Promote the built-in division template + uploaded weekly files.

    The division workbook supplies the fixed base and export layout. HC and
    escort workbooks supply concrete target-week demand. Temporary changes are
    represented as scheduler change events, never as ad-hoc workbook mutation.
    """

    def __init__(
        self,
        *,
        division_template_path: Path = DEFAULT_DIVISION_TEMPLATE,
        master_data: MasterDataSet | None = None,
        master_data_provider: MasterDataProvider | None = None,
    ) -> None:
        self.division_template_path = division_template_path
        self.master_data = master_data
        self.master_data_provider = master_data_provider

    def build(
        self,
        *,
        hc_workbook_path: Path,
        escort_workbook_path: Path,
        week_start: date,
        changes_json: str | list[dict[str, Any]] | dict[str, Any] | None = None,
    ) -> WeeklyRosterDemoBuild:
        division = parse_division_workbook(self.division_template_path)
        hc = parse_hc_timetable_workbook(hc_workbook_path)
        escort = parse_escort_workbook(escort_workbook_path)

        requested_week_start = week_start
        week_start = week_start - timedelta(days=week_start.weekday())

        master_data = self._master_data_for(division)
        lowered = lower_master_data(master_data, week_start)
        workers = lowered.workers
        worker_ids = lowered.worker_aliases
        elder_aliases = lowered.elder_aliases
        elders_by_id = lowered.elders_by_id
        data_gaps: list[DataGap] = list(lowered.data_gaps)
        excluded_source_records: list[ExcludedSourceRecord] = list(
            lowered.excluded_source_records
        )
        demands: list[TaskDemand] = list(lowered.demands)
        availability: list[WorkerAvailability] = list(lowered.availability)
        change_events: list[ChangeEvent] = list(lowered.change_events)
        source_counts: Counter[str] = Counter(lowered.source_counts)
        warnings: list[str] = []
        if requested_week_start != week_start:
            warnings.append(
                f"目標週開始日 {requested_week_start.isoformat()} 不是星期一；"
                f"已自動對齊至該週星期一 {week_start.isoformat()}。"
            )

        hc_selected = self._hc_demands(
            hc, week_start, worker_ids, elder_aliases, elders_by_id, data_gaps,
            source_counts, excluded_source_records)
        demands.extend(hc_selected)
        if hc.summary.parsed_count and not hc_selected:
            warnings.append(
                "HC 時間表沒有落在目標週內的日期；已保留解析摘要，但不偽造 HC 需求。"
            )

        escort_selected = self._escort_demands(
            escort, week_start, worker_ids, elder_aliases, elders_by_id, data_gaps,
            source_counts, excluded_source_records)
        demands.extend(escort_selected)
        if escort.summary.parsed_count and not escort_selected:
            warnings.append(
                "護送總表沒有落在目標週內的日期；已保留解析摘要，但不偽造護送需求。"
            )

        weekly_change_events, weekly_availability, change_summaries = self._change_events(
            changes_json, worker_ids, elder_aliases, elders_by_id, data_gaps)
        change_events.extend(weekly_change_events)
        availability.extend(weekly_availability)
        source_counts["temporary_changes"] = len(weekly_change_events)

        escort_slot_count = sum(
            1 for assignment in division.assignments
            if assignment.kind == "escort_slot"
        )
        baseline_escort = max(1, round(escort_slot_count / 12)) if escort_slot_count else 4

        config = master_data.rule_config.scheduler_config.model_copy(deep=True)
        config.version = config.version or "weekly-demo-v1"
        config.escort_occupancy = config.escort_occupancy.model_copy(update={
            "baseline_reserved_workers_per_half_day": baseline_escort,
            "assumption": (
                config.escort_occupancy.assumption
                or "由內置分工表 ESC 預留位推算；待 NGO 確認。"
            ),
        })
        if not config.assumptions:
            config.assumptions = [
                "照顧員工作分工表作為固定基礎與輸出模板。",
                "HC/護送工作簿只篩選目標週內的具體日期。",
                "缺失 master data 不自動猜測，轉為審核/資料缺口。",
            ]

        snapshot = SchedulerSnapshot(
            week_start=week_start,
            config=config,
            workers=workers,
            elders=sorted(elders_by_id.values(), key=lambda e: e.id),
            availability=availability,
            demands=demands,
            change_events=change_events,
            data_gaps=data_gaps,
            source_evidence=list(lowered.source_evidence),
            excluded_source_records=excluded_source_records,
            source=TaskSource.OPERATOR_INPUT,
            source_note="weekly demo: built-in division base + uploaded HC/escort + temporary changes",
        )

        return WeeklyRosterDemoBuild(
            snapshot=snapshot,
            division=division,
            hc=hc,
            escort=escort,
            source_counts=dict(source_counts),
            warnings=warnings,
            change_summaries=change_summaries,
        )

    # ------------------------------------------------------------------
    # Promotion helpers
    # ------------------------------------------------------------------

    def _master_data_for(self, division: DivisionImportResult) -> MasterDataSet:
        if self.master_data is not None:
            return self.master_data
        if self.master_data_provider is not None:
            provided = self.master_data_provider(division)
            if provided is not None:
                return provided
        return bootstrap_master_data_from_division(division)

    def _hc_demands(
        self,
        result: ImportResult[dict[str, Any]],
        week_start: date,
        worker_ids: dict[str, str],
        elder_aliases: dict[str, str],
        elders_by_id: dict[str, Elder],
        data_gaps: list[DataGap],
        counts: Counter[str],
        excluded: list[ExcludedSourceRecord],
    ) -> list[TaskDemand]:
        dates = _week_date_set(week_start)
        out: list[TaskDemand] = []
        for parsed in result.records:
            record = parsed.record
            if not record or record.get("section") == "section_marker":
                continue
            service_date = _parse_date(record.get("service_date"))
            evidence = _upload_record_evidence(
                parsed,
                workbook_role="hc_upload",
                identity={
                    "source_ref": record.get("source_ref"),
                    "service_date": service_date,
                    "service_code": record.get("service_code_raw"),
                    "period": record.get("period"),
                },
            )
            if service_date not in dates:
                excluded.append(ExcludedSourceRecord(
                    source_record_id=str(record.get("source_ref") or evidence.id),
                    reason_code="outside_target_week",
                    source_evidence=[evidence],
                    detail="HC row outside target Monday-Saturday window",
                ))
                continue
            service = _service_code(record.get("service_code_raw"))
            if service is None:
                gap = DataGap(
                    kind="other",
                    field="service_code",
                    message=f"HC row {record.get('source_ref')} 服務代碼無法解析。",
                    blocking=True,
                    policy="ineligible",
                    source_ref_ids=[evidence.id],
                    source=TaskSource.FIXTURE,
                )
                data_gaps.append(gap)
                excluded.append(ExcludedSourceRecord(
                    source_record_id=str(record.get("source_ref") or evidence.id),
                    reason_code="invalid_source",
                    source_evidence=[evidence],
                    detail=gap.message,
                ))
                continue
            elder_id = self._elder_id(
                elder_aliases,
                elders_by_id,
                record.get("elder_alias"),
                district=record.get("unit"),
                unit=record.get("unit"),
            )
            demand_gaps: list[DataGap] = []
            if service in (ServiceCode.PERSONAL_CARE, ServiceCode.BATH) and elder_id:
                gap = DataGap(
                    kind="gender",
                    entity_id=elder_id,
                    field="gender_requirement",
                    message=f"{record.get('elder_alias')} 的 {service.value} 需要性別核實。",
                    blocking=True,
                    policy="ineligible",
                    source_ref_ids=[evidence.id],
                    source=TaskSource.FIXTURE,
                )
                data_gaps.append(gap)
                demand_gaps.append(gap)
            if record.get("change_raw"):
                gap = DataGap(
                    kind="other",
                    entity_id=elder_id,
                    field="change_raw",
                    message=(
                        f"HC {record.get('source_ref')} 有改期/備註："
                        f"{record.get('change_raw')}，需人工確認。"
                    ),
                    blocking=False,
                    policy="allowed_with_review",
                    source_ref_ids=[evidence.id],
                    source=TaskSource.FIXTURE,
                )
                data_gaps.append(gap)
                demand_gaps.append(gap)
            period = _period(record.get("period")) or Period.AM
            kind = TaskKind.ESCORT if service == ServiceCode.ESCORT else TaskKind.HC_PATTERN
            out.append(TaskDemand(
                id=f"hc-{record.get('source_ref', len(out) + 1)}".replace("!", "-"),
                kind=kind,
                source=TaskSource.FIXTURE,
                service_code=service,
                task_date=service_date,
                weekday=record.get("weekday"),
                period=period,
                session_index=None if kind == TaskKind.ESCORT else 1,
                occupies_full_period=(kind == TaskKind.ESCORT),
                elder_id=elder_id,
                pinned_worker_id=_resolve_alias(worker_ids, record.get("worker_alias")),
                district=record.get("unit"),
                destination=record.get("unit") if kind == TaskKind.ESCORT else None,
                data_gaps=demand_gaps,
                data_gap_ids=[gap.id for gap in demand_gaps],
                source_refs=[record.get("source_ref") or ""],
                source_evidence=[evidence],
                notes=record.get("change_raw") or record.get("case_raw"),
            ))
            counts["hc_selected"] += 1
        return out

    def _escort_demands(
        self,
        result: ImportResult[dict[str, Any]],
        week_start: date,
        worker_ids: dict[str, str],
        elder_aliases: dict[str, str],
        elders_by_id: dict[str, Elder],
        data_gaps: list[DataGap],
        counts: Counter[str],
        excluded: list[ExcludedSourceRecord],
    ) -> list[TaskDemand]:
        dates = _week_date_set(week_start)
        out: list[TaskDemand] = []
        for parsed in result.records:
            record = parsed.record
            if not record or record.get("status") not in {"requested", "cancelled"}:
                continue
            service_date = _parse_date(record.get("service_date"))
            evidence = _upload_record_evidence(
                parsed,
                workbook_role="escort_upload",
                identity={
                    "source_ref": record.get("source_ref"),
                    "service_date": service_date,
                    "period": record.get("period"),
                    "destination": record.get("destination"),
                    "status": record.get("status"),
                },
            )
            if service_date not in dates:
                excluded.append(ExcludedSourceRecord(
                    source_record_id=str(record.get("source_ref") or evidence.id),
                    reason_code="outside_target_week",
                    source_evidence=[evidence],
                    detail="escort row outside target Monday-Saturday window",
                ))
                continue
            elder_id = self._elder_id(
                elder_aliases,
                elders_by_id,
                record.get("elder_alias"),
                district=record.get("unit"),
                unit=record.get("unit"),
            )
            preferred_worker_id = _resolve_alias(
                worker_ids, record.get("preferred_worker_alias"))
            demand_gaps: list[DataGap] = []
            if record.get("preferred_worker_alias") and not preferred_worker_id:
                gap = DataGap(
                    kind="other",
                    entity_id=elder_id,
                    field="preferred_worker_id",
                    message=(
                        f"護送 {record.get('source_ref')} 建議同工 "
                        f"{record.get('preferred_worker_alias')} 未能對應。"
                    ),
                    blocking=False,
                    policy="allowed_with_review",
                    source_ref_ids=[evidence.id],
                    source=TaskSource.FIXTURE,
                )
                data_gaps.append(gap)
                demand_gaps.append(gap)
            period = _period(record.get("period")) or Period.AM
            out.append(TaskDemand(
                id=f"escort-{record.get('row')}",
                kind=TaskKind.ESCORT,
                source=TaskSource.FIXTURE,
                service_code=ServiceCode.ESCORT,
                task_date=service_date,
                weekday=service_date.isoweekday() if service_date else None,
                period=period,
                session_index=None,
                occupies_full_period=True,
                elder_id=elder_id,
                preferred_worker_id=preferred_worker_id,
                preference_strength=record.get("preference_strength"),
                district=record.get("unit"),
                destination=record.get("destination") or "未提供目的地",
                start_time=_parse_time(record.get("appointment_time")),
                status="cancelled" if record.get("status") == "cancelled" else "active",
                data_gaps=demand_gaps,
                data_gap_ids=[gap.id for gap in demand_gaps],
                source_refs=[record.get("source_ref") or ""],
                source_evidence=[evidence],
                notes=_join_notes(record.get("subject"), record.get("transport"),
                                  record.get("raw_notes")),
            ))
            if record.get("status") == "requested":
                counts["escort_selected"] += 1
        return out

    def _change_events(
        self,
        changes_json: str | list[dict[str, Any]] | dict[str, Any] | None,
        worker_ids: dict[str, str],
        elder_aliases: dict[str, str],
        elders_by_id: dict[str, Elder],
        data_gaps: list[DataGap],
    ) -> tuple[list[ChangeEvent], list[WorkerAvailability], list[str]]:
        raw = _parse_changes_json(changes_json)
        events: list[ChangeEvent] = []
        availability: list[WorkerAvailability] = []
        summaries: list[str] = []
        for i, change in enumerate(raw, start=1):
            change_entity_id = (
                f"weekly_change:{content_fingerprint(change)[:20]}"
            )
            ctype = str(change.get("type") or change.get("change_type") or "").strip()
            event_date = _parse_date(change.get("change_date") or change.get("date"))
            period = _period(change.get("period"))
            if not ctype or event_date is None:
                data_gaps.append(DataGap(
                    kind="other",
                    entity_id=change_entity_id,
                    field="type_or_date",
                    reason_code="change_missing_type_or_date",
                    message=f"第 {i} 條臨時變更缺少類型或日期，未自動套用。",
                    blocking=True,
                    source=TaskSource.WEEKLY_CHANGE,
                ))
                continue
            if ctype == ChangeType.LEAVE.value:
                worker_id = change.get("worker_id") or _resolve_alias(
                    worker_ids, change.get("worker_alias") or change.get("worker"))
                if not worker_id:
                    data_gaps.append(DataGap(
                        kind="other",
                        entity_id=change_entity_id,
                        field="worker_id",
                        reason_code="leave_worker_unresolved",
                        message=f"第 {i} 條請假變更的同工未能對應，未自動套用。",
                        blocking=True,
                        source=TaskSource.WEEKLY_CHANGE,
                    ))
                    continue
                event_id, evidence = _change_evidence(
                    ctype, event_date, period, {"worker_id": worker_id}
                )
                event = ChangeEvent(
                    id=event_id,
                    type=ChangeType.LEAVE,
                    change_date=event_date,
                    period=period,
                    worker_id=worker_id,
                    reason=change.get("reason") or "Demo 臨時請假",
                    source_refs=[f"weekly_change:{event_id}"],
                    source_evidence=[evidence],
                )
                events.append(event)
                availability.append(WorkerAvailability(
                    worker_id=worker_id,
                    available_date=event_date,
                    period=period,
                    is_available=False,
                    reason="leave",
                    source=TaskSource.WEEKLY_CHANGE,
                    source_refs=[f"weekly_change:{event_id}"],
                    source_evidence=[evidence],
                    notes=event.reason,
                ))
                summaries.append(f"同工請假：{worker_id} {event_date} {period.value if period else '全日'}")
            elif ctype == ChangeType.ELDER_CANCELLATION.value:
                elder_id = change.get("elder_id") or self._elder_id(
                    elder_aliases,
                    elders_by_id,
                    change.get("elder_alias") or change.get("elder"),
                    district=None,
                    unit=None,
                )
                event_id, evidence = _change_evidence(
                    ctype, event_date, period, {"elder_id": elder_id}
                )
                event = ChangeEvent(
                    id=event_id,
                    type=ChangeType.ELDER_CANCELLATION,
                    change_date=event_date,
                    period=period,
                    elder_id=elder_id,
                    reason=change.get("reason") or "Demo 長者取消服務",
                    source_refs=[f"weekly_change:{event_id}"],
                    source_evidence=[evidence],
                )
                events.append(event)
                summaries.append(f"長者取消：{elder_id} {event_date} {period.value if period else '全日'}")
            elif ctype == ChangeType.ESCORT_NEW.value:
                elder_id = change.get("elder_id") or self._elder_id(
                    elder_aliases,
                    elders_by_id,
                    change.get("elder_alias") or change.get("elder"),
                    district=change.get("unit"),
                    unit=change.get("unit"),
                )
                if not elder_id:
                    data_gaps.append(DataGap(
                        kind="other",
                        entity_id=change_entity_id,
                        field="elder_id",
                        reason_code="new_escort_elder_missing",
                        message=f"第 {i} 條新增護送缺少長者名稱，未自動套用。",
                        blocking=True,
                        source=TaskSource.WEEKLY_CHANGE,
                    ))
                    continue
                preferred_worker_id = change.get("preferred_worker_id") or _resolve_alias(
                    worker_ids, change.get("preferred_worker_alias"))
                event_id, evidence = _change_evidence(
                    ctype,
                    event_date,
                    period,
                    {
                        "elder_id": elder_id,
                        "destination": change.get("destination"),
                        "appointment_time": (
                            change.get("appointment_time") or change.get("start_time")
                        ),
                        "preferred_worker_id": preferred_worker_id,
                    },
                )
                request = EscortRequest(
                    id=f"new-escort-{event_id.removeprefix('change-')}",
                    service_date=event_date,
                    period=period or Period.AM,
                    elder_id=elder_id,
                    appointment_time=_parse_time(
                        change.get("appointment_time") or change.get("start_time")),
                    destination=change.get("destination") or "未提供目的地",
                    subject=change.get("subject"),
                    transport=change.get("transport"),
                    preferred_worker_id=preferred_worker_id,
                    preference_strength=change.get("preference_strength"),
                    source_refs=[f"weekly_change:{event_id}"],
                    source_evidence=[evidence],
                    notes=change.get("reason") or change.get("notes"),
                )
                event = ChangeEvent(
                    id=event_id,
                    type=ChangeType.ESCORT_NEW,
                    change_date=event_date,
                    period=period,
                    new_escort=request,
                    reason=change.get("reason") or "Demo 新增護送",
                    source_refs=[f"weekly_change:{event_id}"],
                    source_evidence=[evidence],
                )
                events.append(event)
                summaries.append(f"新增護送：{elder_id} {event_date} {request.period.value}")
            elif ctype == ChangeType.ESCORT_CANCELLED.value:
                escort_id = change.get("escort_request_id")
                if not escort_id:
                    data_gaps.append(DataGap(
                        kind="other",
                        entity_id=change_entity_id,
                        field="escort_request_id",
                        reason_code="escort_cancellation_request_missing",
                        message=f"第 {i} 條護送取消缺少 escort_request_id，未自動套用。",
                        blocking=True,
                        source=TaskSource.WEEKLY_CHANGE,
                    ))
                    continue
                event_id, evidence = _change_evidence(
                    ctype,
                    event_date,
                    period,
                    {"escort_request_id": escort_id},
                )
                events.append(ChangeEvent(
                    id=event_id,
                    type=ChangeType.ESCORT_CANCELLED,
                    change_date=event_date,
                    period=period,
                    escort_request_id=escort_id,
                    reason=change.get("reason") or "Demo 護送取消",
                    source_refs=[f"weekly_change:{event_id}"],
                    source_evidence=[evidence],
                ))
                summaries.append(f"護送取消：{escort_id} {event_date}")
            else:
                # Accept already-normalized ChangeEvent payloads when possible.
                try:
                    events.append(ChangeEvent.model_validate(change))
                    summaries.append(f"已套用變更：{ctype}")
                except Exception:
                    data_gaps.append(DataGap(
                        kind="other",
                        entity_id=change_entity_id,
                        field="type",
                        reason_code="change_type_unsupported",
                        message=f"第 {i} 條臨時變更類型不支援：{ctype}",
                        blocking=True,
                        source=TaskSource.WEEKLY_CHANGE,
                    ))
        return events, availability, summaries

    def _elder_id(
        self,
        elder_aliases: dict[str, str],
        elders_by_id: dict[str, Elder],
        alias: object,
        *,
        district: object | None,
        unit: object | None,
    ) -> str | None:
        name = _clean(alias)
        if not name:
            return None
        key = _normalize_alias(name)
        if key in elder_aliases:
            return elder_aliases[key]
        elder_id = stable_id("elder_", "uploaded_elder_alias", {
            "normalized_alias": key,
        })
        elders_by_id[elder_id] = Elder(
            id=elder_id,
            display_name=name,
            gender=None,
            district=_clean(district) or _clean(unit) or "未提供",
            owning_unit=_clean(unit) or "EH",
            gender_requirement=GenderRequirement.ANY,
            notes="Demo elder promoted from source workbook alias",
        )
        elder_aliases[key] = elder_id
        return elder_id


# --------------------------------------------------------------------------
# Small parsing helpers
# --------------------------------------------------------------------------


def _upload_record_evidence(
    parsed: ParsedRecord[dict[str, Any]],
    *,
    workbook_role: str,
    identity: dict[str, object],
) -> SourceEvidence:
    source = parsed.source
    locator = _safe_source_locator(source, fallback=identity.get("source_ref"))
    confidence = {
        "high": "high",
        "medium": "medium",
        "low": "low",
        "unknown": "low",
    }[parsed.parse_confidence]
    return SourceEvidence(
        kind="workbook_row",
        source_id=workbook_role,
        locator=f"{workbook_role}:{locator}",
        field="weekly_demand",
        content_fingerprint=content_fingerprint(identity),
        confidence=confidence,  # type: ignore[arg-type]
    )


def _safe_source_locator(source: SourceRef, *, fallback: object = None) -> str:
    if source.cell is not None:
        return source.cell.label
    if source.sheet_name and source.range_ref:
        return f"{source.sheet_name}!{source.range_ref}"
    if source.sheet_name:
        return source.sheet_name
    if source.doc_ref:
        return source.doc_ref
    return _clean(fallback) or "unknown-row"


def _change_evidence(
    change_type: str,
    change_date: date,
    period: Period | None,
    fields: dict[str, object],
) -> tuple[str, SourceEvidence]:
    identity = {
        "type": change_type,
        "change_date": change_date,
        "period": period.value if period else None,
        **fields,
    }
    fingerprint = content_fingerprint(identity)
    event_id = f"change-{fingerprint[:20]}"
    return event_id, SourceEvidence(
        kind="weekly_change",
        source_id="weekly_changes",
        locator=f"weekly_change:{fingerprint[:20]}",
        field=change_type,
        content_fingerprint=fingerprint,
        confidence="high",
    )


def _parse_changes_json(
    raw: str | list[dict[str, Any]] | dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if raw in (None, ""):
        return []
    if isinstance(raw, list):
        return [dict(item) for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        changes = raw.get("changes", raw)
        if isinstance(changes, list):
            return [dict(item) for item in changes if isinstance(item, dict)]
        return [dict(changes)] if isinstance(changes, dict) else []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return _parse_changes_json(parsed)


def _week_date_set(week_start: date) -> set[date]:
    return {week_start + timedelta(days=i) for i in range(6)}


def _clean(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    text = unicodedata.normalize("NFKC", str(value))
    text = text.replace("：", ":").replace("（", "(").replace("）", ")")
    return re.sub(r"\s+", " ", text).strip()


def _normalize_alias(value: object) -> str:
    text = _clean(value)
    text = re.sub(r"(照顧員|姑娘|姐姐|姐)$", "", text)
    text = re.sub(r"[^\w一-鿿]+", "", text)
    return text.lower()


def _alias_variants(*values: object) -> set[str]:
    out: set[str] = set()
    for value in values:
        text = _clean(value)
        if not text:
            continue
        candidates = {text}
        candidates.add(re.sub(r"\([^)]*\)", "", text).strip())
        candidates.add(text.split()[0])
        for candidate in candidates:
            key = _normalize_alias(candidate)
            if key:
                out.add(key)
    return out


def _resolve_alias(mapping: dict[str, str], alias: object) -> str | None:
    for variant in _alias_variants(alias):
        if variant in mapping:
            return mapping[variant]
    return None


def _service_code(value: object) -> ServiceCode | None:
    text = _clean(value).upper()
    if not text:
        return None
    aliases = {
        "ESC": ServiceCode.ESCORT,
        "ESCORT": ServiceCode.ESCORT,
        "ESCORTS": ServiceCode.ESCORT,
        "ESC ": ServiceCode.ESCORT,
        "E+RO": ServiceCode.EXERCISE,
        "ERO": ServiceCode.EXERCISE,
        "HC": ServiceCode.HOME_CLEAN,
        "PC": ServiceCode.PERSONAL_CARE,
        "B": ServiceCode.BATH,
        "D": ServiceCode.MEAL,
        "AMC": ServiceCode.DUTY_AMC,
        "MRC": ServiceCode.DUTY_MRC,
        "GC": ServiceCode.DUTY_GC,
        "KITCHEN": ServiceCode.KITCHEN,
    }
    return aliases.get(text)


def _period(value: object) -> Period | None:
    text = _clean(value).upper()
    if text in {"AM", "上午", "上"}:
        return Period.AM
    if text in {"PM", "下午", "下"}:
        return Period.PM
    return None


def _parse_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _clean(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_time(value: object) -> time | None:
    if isinstance(value, datetime):
        return value.time().replace(second=0, microsecond=0)
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    text = _clean(value)
    if not text:
        return None
    match = re.search(r"(\d{1,2})[:：](\d{2})", text)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return time(hour, minute)
    return None


def _join_notes(*values: object) -> str | None:
    parts = [_clean(value) for value in values if _clean(value)]
    return "；".join(parts) if parts else None
