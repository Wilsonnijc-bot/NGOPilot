"""Persistent storage boundary for Phase 1.

The scheduler still works with in-memory Pydantic objects. This package keeps
that surface stable while persisting snapshots, versions and import review
state into a single SQLite file.
"""
from .sqlite import (
    RosterStore,
    WeeklyRunStoreError,
    WeeklyRunVersionConflictError,
    default_db_path,
)

__all__ = [
    "RosterStore",
    "WeeklyRunStoreError",
    "WeeklyRunVersionConflictError",
    "default_db_path",
]
