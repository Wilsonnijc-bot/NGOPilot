"""Scheduler bridge: turn a rule-based ``SchedulerSnapshot`` into a draft roster.

This package is the scheduler-first entry point described in
``docs/spec/ENGINEERING_SPEC.md``. It never reads Excel:

* ``generator``  — expands snapshot demand into concrete dated tasks;
* ``adapter``    — lowers that demand into the engine's ``MockDataset``;
* ``bridge``     — drafts + repairs a ``ScheduleVersion`` via the greedy engine;
* ``fixture``    — a representative real-style snapshot for tests/demos.
"""
from .adapter import to_dataset
from .bridge import SchedulerResult, run_scheduler
from .fixture import representative_snapshot
from .generator import GeneratedDemands, duty_requirements, generate_demands, week_dates
from .reconciliation import (
    finalize_version_provenance,
    reconcile_weekly_demands,
    version_content_hash,
)

__all__ = [
    "GeneratedDemands",
    "SchedulerResult",
    "duty_requirements",
    "generate_demands",
    "finalize_version_provenance",
    "representative_snapshot",
    "run_scheduler",
    "reconcile_weekly_demands",
    "to_dataset",
    "week_dates",
    "version_content_hash",
]
