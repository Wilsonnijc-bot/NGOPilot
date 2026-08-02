"""Schedule API: generation, versions, audit queue and decisions."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..domain import (
    AuditDecision,
    AuditItem,
    ChangeEvent,
    MockDataset,
    ScheduleVersion,
    SchedulerSnapshot,
)
from ..scheduler import run_scheduler
from ..services.state import get_state

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


class GenerateScheduleRequest(BaseModel):
    changes: list[ChangeEvent] = Field(default_factory=list)


class VersionSummary(BaseModel):
    id: str
    kind: str
    parent_version_id: str | None
    created_at: str
    week_start: str
    is_current: bool
    entry_count: int
    metrics: dict[str, float]


class SolveScheduleResponse(BaseModel):
    version: ScheduleVersion
    generated_counts: dict[str, int]
    suppressed_count: int
    data_gap_count: int
    hard_constraint_violations: int


@router.get("/mock-data", response_model=MockDataset)
def mock_data() -> MockDataset:
    return get_state().dataset


@router.get("/current", response_model=ScheduleVersion)
def current_schedule() -> ScheduleVersion:
    return get_state().current


@router.post("/generate", response_model=ScheduleVersion)
def generate(req: GenerateScheduleRequest) -> ScheduleVersion:
    """Rebuild the weekly baseline; optionally apply change events on top."""
    return get_state().generate(req.changes)


@router.post("/solve", response_model=SolveScheduleResponse)
def solve(snapshot: SchedulerSnapshot) -> SolveScheduleResponse:
    """Build a draft roster from the scheduler-first snapshot contract."""
    result = run_scheduler(snapshot)
    return SolveScheduleResponse(
        version=result.version,
        generated_counts=result.generated.counts_by_kind,
        suppressed_count=len(result.generated.suppressed),
        data_gap_count=len(result.generated.data_gaps),
        hard_constraint_violations=len(result.violations),
    )


@router.post("/reset", response_model=ScheduleVersion)
def reset() -> ScheduleVersion:
    """Drop repairs and decisions; back to a fresh baseline (same dataset)."""
    return get_state().reset_schedule()


@router.get("/versions", response_model=list[VersionSummary])
def versions() -> list[VersionSummary]:
    state = get_state()
    out = []
    for v in state.versions.values():
        out.append(VersionSummary(
            id=v.id, kind=v.kind.value, parent_version_id=v.parent_version_id,
            created_at=v.created_at.isoformat(), week_start=v.week_start.isoformat(),
            is_current=(v.id == state.current_id), entry_count=len(v.entries),
            metrics=v.summary,
        ))
    out.sort(key=lambda s: s.created_at)
    return out


@router.get("/versions/{version_id}", response_model=ScheduleVersion)
def get_version(version_id: str) -> ScheduleVersion:
    version = get_state().get_version(version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="version not found")
    return version


@router.get("/audit", response_model=list[AuditItem])
def audit_queue() -> list[AuditItem]:
    """Pending first, blocking first, then by severity."""
    return get_state().audit_queue()


@router.post("/audit/{audit_id}/decision", response_model=ScheduleVersion)
def decide_audit_item(audit_id: str, decision: AuditDecision) -> ScheduleVersion:
    try:
        return get_state().decide(audit_id, decision)
    except KeyError:
        raise HTTPException(status_code=404, detail="audit item not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
