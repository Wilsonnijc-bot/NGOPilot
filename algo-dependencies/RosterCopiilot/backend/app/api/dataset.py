"""Mock dataset lifecycle endpoints."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..mockdata import DEFAULT_SEED
from ..services.state import get_state

router = APIRouter(prefix="/api/dataset", tags=["dataset"])


class RegenerateRequest(BaseModel):
    seed: int = DEFAULT_SEED


class DatasetSummary(BaseModel):
    seed: int
    employees: int
    elders: int
    fixed_services: int
    escort_requests: int
    duty_requirements: int
    week_start: str
    baseline_version_id: str
    baseline_metrics: dict[str, float]


def _summary() -> DatasetSummary:
    state = get_state()
    ds = state.dataset
    return DatasetSummary(
        seed=ds.seed,
        employees=len(ds.employees),
        elders=len(ds.elders),
        fixed_services=len(ds.fixed_services),
        escort_requests=len(ds.escort_requests),
        duty_requirements=len(ds.duty_requirements),
        week_start=ds.params.week_start.isoformat(),
        baseline_version_id=state.baseline_id,
        baseline_metrics=state.baseline.summary,
    )


@router.get("/summary", response_model=DatasetSummary)
def summary() -> DatasetSummary:
    return _summary()


@router.post("/regenerate", response_model=DatasetSummary)
def regenerate(req: RegenerateRequest) -> DatasetSummary:
    """Regenerate the mock dataset with a seed (deterministic) and rebuild
    the baseline. Same seed => identical dataset and roster."""
    get_state().regenerate(req.seed)
    return _summary()
