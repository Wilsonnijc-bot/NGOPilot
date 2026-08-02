"""Support/admin APIs for persisted Phase 1A master data."""
from __future__ import annotations

from typing import TypeVar

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ..domain import (
    LeaveEvent,
    ManualOverride,
    MasterDataIssue,
    MasterDataSet,
    MasterElder,
    MasterFixedService,
    MasterRuleConfig,
    MasterWorker,
    TemporaryChange,
    WorkerAvailability,
    has_error_issues,
    validate_master_data,
)
from ..services.state import get_state
from ..services.master_data_bridge import bootstrap_master_data_from_template

router = APIRouter(prefix="/api/master-data", tags=["master-data"])

T = TypeVar("T")


class MasterDataResponse(BaseModel):
    version: int
    id: str
    created_at: str
    origin: str
    schema_version: str
    payload: MasterDataSet
    issues: list[MasterDataIssue]


class EntityMutationResponse(BaseModel):
    version: int
    id: str
    issues: list[MasterDataIssue]


def _store():
    store = get_state().store
    if store is None:
        raise RuntimeError("master data API requires a persistent store")
    return store


def _current_record() -> dict:
    store = _store()
    current = store.get_master_data()
    if current is not None:
        return current
    payload = bootstrap_master_data_from_template()
    issues = validate_master_data(payload)
    return store.save_master_data(payload, origin=payload.origin, issues=issues)


def _current_payload() -> MasterDataSet:
    return MasterDataSet.model_validate(_current_record()["payload"])


def _response(record: dict) -> MasterDataResponse:
    return MasterDataResponse.model_validate(record)


def _save_or_422(payload: MasterDataSet, *, origin: str) -> dict:
    issues = validate_master_data(payload)
    if has_error_issues(issues):
        raise HTTPException(
            status_code=422,
            detail={"issues": [issue.model_dump(mode="json") for issue in issues]},
        )
    return _store().save_master_data(payload, origin=origin, issues=issues)


def _entity_response(record: dict) -> EntityMutationResponse:
    return EntityMutationResponse(
        version=record["version"],
        id=record["id"],
        issues=[MasterDataIssue.model_validate(issue) for issue in record["issues"]],
    )


def _not_found(entity: str, entity_id: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"{entity} {entity_id!r} not found",
    )


def _conflict(entity: str, entity_id: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"{entity} {entity_id!r} already exists",
    )


def _find_by_id(items: list[T], entity_id: str) -> tuple[int, T] | None:
    for idx, item in enumerate(items):
        if getattr(item, "id", None) == entity_id:
            return idx, item
    return None


@router.get("", response_model=MasterDataResponse)
def get_master_data() -> MasterDataResponse:
    return _response(_current_record())


@router.put("", response_model=MasterDataResponse)
def put_master_data(payload: MasterDataSet) -> MasterDataResponse:
    record = _save_or_422(payload, origin=payload.origin or "api_replace")
    return _response(record)


@router.get("/versions")
def list_master_data_versions() -> list[dict]:
    _current_record()
    return _store().list_master_data_versions()


@router.get("/issues", response_model=list[MasterDataIssue])
def get_master_data_issues() -> list[MasterDataIssue]:
    _current_record()
    return [MasterDataIssue.model_validate(issue)
            for issue in _store().get_master_data_issues()]


@router.get("/workers", response_model=list[MasterWorker])
def list_workers() -> list[MasterWorker]:
    return _current_payload().workers


@router.post("/workers", response_model=EntityMutationResponse, status_code=201)
def create_worker(worker: MasterWorker) -> EntityMutationResponse:
    payload = _current_payload()
    if _find_by_id(payload.workers, worker.id):
        _conflict("worker", worker.id)
    record = _save_or_422(
        payload.model_copy(update={"workers": [*payload.workers, worker]}),
        origin="api_worker_create",
    )
    return _entity_response(record)


@router.get("/workers/{worker_id}", response_model=MasterWorker)
def get_worker(worker_id: str) -> MasterWorker:
    found = _find_by_id(_current_payload().workers, worker_id)
    if found is None:
        _not_found("worker", worker_id)
    return found[1]


@router.put("/workers/{worker_id}", response_model=EntityMutationResponse)
def update_worker(worker_id: str, worker: MasterWorker) -> EntityMutationResponse:
    payload = _current_payload()
    found = _find_by_id(payload.workers, worker_id)
    if found is None:
        _not_found("worker", worker_id)
    idx, _ = found
    workers = list(payload.workers)
    workers[idx] = worker.model_copy(update={"id": worker_id})
    record = _save_or_422(
        payload.model_copy(update={"workers": workers}),
        origin="api_worker_update",
    )
    return _entity_response(record)


@router.delete("/workers/{worker_id}", response_model=EntityMutationResponse)
def delete_worker(worker_id: str) -> EntityMutationResponse:
    payload = _current_payload()
    if _find_by_id(payload.workers, worker_id) is None:
        _not_found("worker", worker_id)
    record = _save_or_422(
        payload.model_copy(
            update={"workers": [row for row in payload.workers if row.id != worker_id]}
        ),
        origin="api_worker_delete",
    )
    return _entity_response(record)


@router.get("/elders", response_model=list[MasterElder])
def list_elders() -> list[MasterElder]:
    return _current_payload().elders


@router.post("/elders", response_model=EntityMutationResponse, status_code=201)
def create_elder(elder: MasterElder) -> EntityMutationResponse:
    payload = _current_payload()
    if _find_by_id(payload.elders, elder.id):
        _conflict("elder", elder.id)
    record = _save_or_422(
        payload.model_copy(update={"elders": [*payload.elders, elder]}),
        origin="api_elder_create",
    )
    return _entity_response(record)


@router.get("/elders/{elder_id}", response_model=MasterElder)
def get_elder(elder_id: str) -> MasterElder:
    found = _find_by_id(_current_payload().elders, elder_id)
    if found is None:
        _not_found("elder", elder_id)
    return found[1]


@router.put("/elders/{elder_id}", response_model=EntityMutationResponse)
def update_elder(elder_id: str, elder: MasterElder) -> EntityMutationResponse:
    payload = _current_payload()
    found = _find_by_id(payload.elders, elder_id)
    if found is None:
        _not_found("elder", elder_id)
    idx, _ = found
    elders = list(payload.elders)
    elders[idx] = elder.model_copy(update={"id": elder_id})
    record = _save_or_422(
        payload.model_copy(update={"elders": elders}),
        origin="api_elder_update",
    )
    return _entity_response(record)


@router.delete("/elders/{elder_id}", response_model=EntityMutationResponse)
def delete_elder(elder_id: str) -> EntityMutationResponse:
    payload = _current_payload()
    if _find_by_id(payload.elders, elder_id) is None:
        _not_found("elder", elder_id)
    record = _save_or_422(
        payload.model_copy(
            update={"elders": [row for row in payload.elders if row.id != elder_id]}
        ),
        origin="api_elder_delete",
    )
    return _entity_response(record)


@router.get("/fixed-services", response_model=list[MasterFixedService])
def list_fixed_services() -> list[MasterFixedService]:
    return _current_payload().fixed_services


@router.post("/fixed-services", response_model=EntityMutationResponse, status_code=201)
def create_fixed_service(service: MasterFixedService) -> EntityMutationResponse:
    payload = _current_payload()
    if _find_by_id(payload.fixed_services, service.id):
        _conflict("fixed service", service.id)
    record = _save_or_422(
        payload.model_copy(update={"fixed_services": [*payload.fixed_services, service]}),
        origin="api_fixed_service_create",
    )
    return _entity_response(record)


@router.get("/fixed-services/{service_id}", response_model=MasterFixedService)
def get_fixed_service(service_id: str) -> MasterFixedService:
    found = _find_by_id(_current_payload().fixed_services, service_id)
    if found is None:
        _not_found("fixed service", service_id)
    return found[1]


@router.put("/fixed-services/{service_id}", response_model=EntityMutationResponse)
def update_fixed_service(
    service_id: str,
    service: MasterFixedService,
) -> EntityMutationResponse:
    payload = _current_payload()
    found = _find_by_id(payload.fixed_services, service_id)
    if found is None:
        _not_found("fixed service", service_id)
    idx, _ = found
    fixed_services = list(payload.fixed_services)
    fixed_services[idx] = service.model_copy(update={"id": service_id})
    record = _save_or_422(
        payload.model_copy(update={"fixed_services": fixed_services}),
        origin="api_fixed_service_update",
    )
    return _entity_response(record)


@router.delete("/fixed-services/{service_id}", response_model=EntityMutationResponse)
def delete_fixed_service(service_id: str) -> EntityMutationResponse:
    payload = _current_payload()
    if _find_by_id(payload.fixed_services, service_id) is None:
        _not_found("fixed service", service_id)
    record = _save_or_422(
        payload.model_copy(
            update={
                "fixed_services": [
                    row for row in payload.fixed_services if row.id != service_id
                ]
            }
        ),
        origin="api_fixed_service_delete",
    )
    return _entity_response(record)


@router.get("/availability", response_model=list[WorkerAvailability])
def list_availability() -> list[WorkerAvailability]:
    return _current_payload().availability


@router.put("/availability", response_model=EntityMutationResponse)
def replace_availability(rows: list[WorkerAvailability]) -> EntityMutationResponse:
    payload = _current_payload()
    record = _save_or_422(
        payload.model_copy(update={"availability": rows}),
        origin="api_availability_replace",
    )
    return _entity_response(record)


@router.post("/availability", response_model=EntityMutationResponse, status_code=201)
def append_availability(row: WorkerAvailability) -> EntityMutationResponse:
    payload = _current_payload()
    record = _save_or_422(
        payload.model_copy(update={"availability": [*payload.availability, row]}),
        origin="api_availability_append",
    )
    return _entity_response(record)


@router.delete("/availability/{index}", response_model=EntityMutationResponse)
def delete_availability(index: int) -> EntityMutationResponse:
    payload = _current_payload()
    if index < 0 or index >= len(payload.availability):
        _not_found("availability row", str(index))
    rows = list(payload.availability)
    rows.pop(index)
    record = _save_or_422(
        payload.model_copy(update={"availability": rows}),
        origin="api_availability_delete",
    )
    return _entity_response(record)


@router.get("/leave-events", response_model=list[LeaveEvent])
def list_leave_events() -> list[LeaveEvent]:
    return _current_payload().leave_events


@router.post("/leave-events", response_model=EntityMutationResponse, status_code=201)
def append_leave_event(event: LeaveEvent) -> EntityMutationResponse:
    payload = _current_payload()
    record = _save_or_422(
        payload.model_copy(update={"leave_events": [*payload.leave_events, event]}),
        origin="api_leave_event_append",
    )
    return _entity_response(record)


@router.put("/leave-events", response_model=EntityMutationResponse)
def replace_leave_events(events: list[LeaveEvent]) -> EntityMutationResponse:
    payload = _current_payload()
    record = _save_or_422(
        payload.model_copy(update={"leave_events": events}),
        origin="api_leave_events_replace",
    )
    return _entity_response(record)


@router.delete("/leave-events/{index}", response_model=EntityMutationResponse)
def delete_leave_event(index: int) -> EntityMutationResponse:
    payload = _current_payload()
    if index < 0 or index >= len(payload.leave_events):
        _not_found("leave event", str(index))
    rows = list(payload.leave_events)
    rows.pop(index)
    record = _save_or_422(
        payload.model_copy(update={"leave_events": rows}),
        origin="api_leave_event_delete",
    )
    return _entity_response(record)


@router.get("/temporary-changes", response_model=list[TemporaryChange])
def list_temporary_changes() -> list[TemporaryChange]:
    return _current_payload().temporary_changes


@router.post("/temporary-changes", response_model=EntityMutationResponse, status_code=201)
def append_temporary_change(change: TemporaryChange) -> EntityMutationResponse:
    payload = _current_payload()
    record = _save_or_422(
        payload.model_copy(
            update={"temporary_changes": [*payload.temporary_changes, change]}
        ),
        origin="api_temporary_change_append",
    )
    return _entity_response(record)


@router.put("/temporary-changes", response_model=EntityMutationResponse)
def replace_temporary_changes(
    changes: list[TemporaryChange],
) -> EntityMutationResponse:
    payload = _current_payload()
    record = _save_or_422(
        payload.model_copy(update={"temporary_changes": changes}),
        origin="api_temporary_changes_replace",
    )
    return _entity_response(record)


@router.delete("/temporary-changes/{index}", response_model=EntityMutationResponse)
def delete_temporary_change(index: int) -> EntityMutationResponse:
    payload = _current_payload()
    if index < 0 or index >= len(payload.temporary_changes):
        _not_found("temporary change", str(index))
    rows = list(payload.temporary_changes)
    rows.pop(index)
    record = _save_or_422(
        payload.model_copy(update={"temporary_changes": rows}),
        origin="api_temporary_change_delete",
    )
    return _entity_response(record)


@router.get("/rule-config", response_model=MasterRuleConfig)
def get_rule_config() -> MasterRuleConfig:
    return _current_payload().rule_config


@router.put("/rule-config", response_model=EntityMutationResponse)
def update_rule_config(rule_config: MasterRuleConfig) -> EntityMutationResponse:
    payload = _current_payload()
    record = _save_or_422(
        payload.model_copy(update={"rule_config": rule_config}),
        origin="api_rule_config_update",
    )
    return _entity_response(record)


@router.get("/manual-overrides", response_model=list[ManualOverride])
def list_manual_overrides() -> list[ManualOverride]:
    return _current_payload().manual_overrides


@router.post("/manual-overrides", response_model=EntityMutationResponse, status_code=201)
def create_manual_override(override: ManualOverride) -> EntityMutationResponse:
    payload = _current_payload()
    if _find_by_id(payload.manual_overrides, override.id):
        _conflict("manual override", override.id)
    record = _save_or_422(
        payload.model_copy(
            update={"manual_overrides": [*payload.manual_overrides, override]}
        ),
        origin="api_manual_override_create",
    )
    return _entity_response(record)


@router.put("/manual-overrides/{override_id}", response_model=EntityMutationResponse)
def update_manual_override(
    override_id: str,
    override: ManualOverride,
) -> EntityMutationResponse:
    payload = _current_payload()
    found = _find_by_id(payload.manual_overrides, override_id)
    if found is None:
        _not_found("manual override", override_id)
    idx, _ = found
    rows = list(payload.manual_overrides)
    rows[idx] = override.model_copy(update={"id": override_id})
    record = _save_or_422(
        payload.model_copy(update={"manual_overrides": rows}),
        origin="api_manual_override_update",
    )
    return _entity_response(record)


@router.delete("/manual-overrides/{override_id}", response_model=EntityMutationResponse)
def delete_manual_override(override_id: str) -> EntityMutationResponse:
    payload = _current_payload()
    if _find_by_id(payload.manual_overrides, override_id) is None:
        _not_found("manual override", override_id)
    record = _save_or_422(
        payload.model_copy(
            update={
                "manual_overrides": [
                    row for row in payload.manual_overrides if row.id != override_id
                ]
            }
        ),
        origin="api_manual_override_delete",
    )
    return _entity_response(record)
