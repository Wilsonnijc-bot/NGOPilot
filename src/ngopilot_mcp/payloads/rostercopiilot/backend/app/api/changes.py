"""Change-event endpoints: examples, impact simulation, and committed repair."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..domain import ChangeEvent, ImpactReport, ScheduleVersion
from ..services.impact_analyzer import analyze_changes, summarize_reports
from ..services.state import get_state

router = APIRouter(prefix="/api/changes", tags=["changes"])


class ChangeRequest(BaseModel):
    changes: list[ChangeEvent] = Field(default_factory=list)


class ChangeResponse(BaseModel):
    version: ScheduleVersion
    impact_reports: list[ImpactReport]
    summary: dict


@router.get("/examples", response_model=list[ChangeEvent])
def examples() -> list[ChangeEvent]:
    return get_state().example_events()


@router.post("/simulate", response_model=ChangeResponse)
def simulate(req: ChangeRequest) -> ChangeResponse:
    """Dry-run impact analysis — the current schedule is NOT modified."""
    state = get_state()
    version, reports = analyze_changes(state, req.changes)
    return ChangeResponse(version=version, impact_reports=reports,
                          summary=summarize_reports(reports))


@router.post("/apply", response_model=ChangeResponse)
def apply(req: ChangeRequest) -> ChangeResponse:
    """Commit the repair: creates a new version and makes it current."""
    state = get_state()
    version, reports = state.apply(req.changes)
    return ChangeResponse(version=version, impact_reports=reports,
                          summary=summarize_reports(reports))
