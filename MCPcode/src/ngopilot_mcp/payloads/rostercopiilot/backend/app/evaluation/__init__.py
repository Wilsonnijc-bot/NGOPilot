"""Deterministic operational evaluation helpers."""

from .parallel_run import (
    ParallelRunValidationError,
    canonical_report_json,
    evaluate_parallel_run,
    failure_report,
)

__all__ = [
    "ParallelRunValidationError",
    "canonical_report_json",
    "evaluate_parallel_run",
    "failure_report",
]
