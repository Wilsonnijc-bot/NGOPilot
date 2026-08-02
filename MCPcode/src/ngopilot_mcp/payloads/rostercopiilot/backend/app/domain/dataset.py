"""Dataset container binding all master data for one deployment/demo."""
from __future__ import annotations

from pydantic import BaseModel, Field

from .entities import (
    CenterDutyRequirement,
    Elder,
    Employee,
    EscortRequest,
    FixedService,
    ScheduleParams,
)
from .snapshot import WorkerAvailability


class MockDataset(BaseModel):
    seed: int = 2026
    employees: list[Employee] = Field(default_factory=list)
    elders: list[Elder] = Field(default_factory=list)
    fixed_services: list[FixedService] = Field(default_factory=list)
    escort_requests: list[EscortRequest] = Field(default_factory=list)
    duty_requirements: list[CenterDutyRequirement] = Field(default_factory=list)
    unavailable_slots: list[WorkerAvailability] = Field(default_factory=list)
    params: ScheduleParams

    def employee_map(self) -> dict[str, Employee]:
        return {w.id: w for w in self.employees}

    def elder_map(self) -> dict[str, Elder]:
        return {e.id: e for e in self.elders}

    def escort_map(self) -> dict[str, EscortRequest]:
        return {r.id: r for r in self.escort_requests}
