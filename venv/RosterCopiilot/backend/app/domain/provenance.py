"""Canonical provenance identities and reconciliation value objects.

This module is deliberately independent of the scheduler, API, persistence,
and exporter layers.  Every derived provenance identifier is created here so
those layers cannot drift onto subtly different hashing rules.
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
import unicodedata
from datetime import date, datetime, time
from enum import Enum
from typing import Any, Iterable, Literal, Mapping, Sequence

from pydantic import BaseModel, Field, field_validator, model_validator


EvidenceConfidence = Literal["high", "medium", "low", "seed"]
DispositionKind = Literal[
    "scheduled",
    "needs_review",
    "unassigned",
    "confirmed_cancelled",
    "suppressed_with_audit",
]
GapPolicy = Literal["ineligible", "allowed_with_review", "informational"]


_SEEN_IDENTITIES: dict[str, str] = {}
_SEEN_LOCK = threading.Lock()


def canonical_json(value: Any) -> str:
    """Serialize identity values using the Phase 1B canonical JSON contract."""

    normalized = _canonical_value(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def content_fingerprint(value: Any) -> str:
    """Return a full SHA-256 fingerprint without retaining sensitive content."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def stable_id(prefix: str, namespace: str, identity_fields: Mapping[str, Any]) -> str:
    """Build one stable derived ID and fail closed on a truncated collision."""

    if not prefix.endswith("_"):
        raise ValueError("stable ID prefix must end with an underscore")
    namespace = _normalize_string(namespace)
    if not namespace:
        raise ValueError("stable ID namespace must not be empty")
    payload = canonical_json(identity_fields)
    canonical_input = f"{namespace}:{payload}"
    derived = f"{prefix}{hashlib.sha256(canonical_input.encode('utf-8')).hexdigest()[:20]}"
    with _SEEN_LOCK:
        prior = _SEEN_IDENTITIES.get(derived)
        if prior is not None and prior != canonical_input:
            raise ValueError(f"stable ID collision for {derived}")
        _SEEN_IDENTITIES[derived] = canonical_input
    return derived


def normalize_identity_string(value: str) -> str:
    """Return the exact canonical string used by stable identity hashing."""

    return _normalize_string(value)


class SourceEvidence(BaseModel):
    """Safe structured reference to one fact used by the scheduler."""

    id: str = ""
    kind: str
    source_id: str
    source_version: str | None = None
    locator: str | None = None
    field: str | None = None
    content_fingerprint: str | None = None
    confidence: EvidenceConfidence = "high"

    @field_validator(
        "kind",
        "source_id",
        "source_version",
        "locator",
        "field",
        "content_fingerprint",
        mode="before",
    )
    @classmethod
    def _normalize_identity_strings(cls, value: Any) -> Any:
        # The serialized value must be just as canonical as the value used by
        # stable_id().  Otherwise two whitespace/NFC variants could share an
        # ID while their persisted payloads still differed by input order.
        return normalize_identity_string(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def _derive_id(self) -> "SourceEvidence":
        expected = stable_id("src_", "source_evidence", {
            "kind": self.kind,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "locator": self.locator,
            "field": self.field,
            "content_fingerprint": self.content_fingerprint,
        })
        if self.id and self.id != expected:
            raise ValueError("source evidence ID does not match its canonical identity")
        self.id = expected
        return self


_CONFIDENCE_ORDER: dict[EvidenceConfidence, int] = {
    "seed": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
}


def merge_source_evidence(
    *groups: Iterable[SourceEvidence],
) -> list[SourceEvidence]:
    """Deduplicate evidence deterministically using the safest confidence.

    Confidence is deliberately excluded from ``SourceEvidence.id``: the ID
    identifies the fact, while confidence describes how safe it is to use.
    When the same fact arrives through multiple paths, retaining the most
    optimistic row would make publication depend on parser/list order.  The
    merged registry therefore keeps ``seed < low < medium < high``.
    """

    merged: dict[str, SourceEvidence] = {}
    identities: dict[str, str] = {}
    for group in groups:
        for item in group:
            identity = canonical_json(item.model_dump(
                mode="json", exclude={"confidence"}
            ))
            prior_identity = identities.get(item.id)
            if prior_identity is not None and prior_identity != identity:
                # This should already be impossible because the ID validator
                # uses the same identity.  Keep the guard at every merge
                # boundary so a future model change fails closed.
                raise ValueError(
                    f"conflicting source evidence records share ID {item.id}"
                )
            identities[item.id] = identity
            prior = merged.get(item.id)
            if prior is None or (
                _CONFIDENCE_ORDER[item.confidence]
                < _CONFIDENCE_ORDER[prior.confidence]
            ):
                merged[item.id] = item
    return [merged[key] for key in sorted(merged)]


class ExcludedSourceRecord(BaseModel):
    """Diagnostic source row that did not become a weekly demand."""

    source_record_id: str
    reason_code: Literal[
        "week_pattern_not_matched",
        "outside_target_week",
        "not_schedulable_kind",
        "inactive_source",
        "invalid_source",
    ]
    source_evidence: list[SourceEvidence] = Field(default_factory=list)
    detail: str | None = None


class DemandDisposition(BaseModel):
    """The one terminal state of a concrete dated weekly demand."""

    demand_id: str
    disposition: DispositionKind
    entry_id: str | None = None
    audit_ids: list[str] = Field(default_factory=list)
    source_ref_ids: list[str] = Field(default_factory=list)
    reason_code: str | None = None


class ReconciliationError(BaseModel):
    """Structured fail-closed provenance or conservation error."""

    code: Literal[
        "demand_conservation_error",
        "missing_demand_link",
        "missing_entry_link",
        "missing_audit_link",
        "missing_data_gap_link",
        "missing_evidence_link",
        "invalid_uncertainty_state",
    ]
    message: str
    demand_ids: list[str] = Field(default_factory=list)
    entry_ids: list[str] = Field(default_factory=list)
    audit_ids: list[str] = Field(default_factory=list)
    data_gap_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class DemandReconciliationReport(BaseModel):
    """Canonical demand totals shared by API, export sheets, and metadata."""

    weekly_demand_total: int = 0
    scheduled: int = 0
    needs_review: int = 0
    unassigned: int = 0
    confirmed_cancelled: int = 0
    suppressed_with_audit: int = 0
    dispositions: list[DemandDisposition] = Field(default_factory=list)
    excluded_source_records: list[ExcludedSourceRecord] = Field(default_factory=list)
    excluded_source_record_counts: dict[str, int] = Field(default_factory=dict)
    active_entry_ids: list[str] = Field(default_factory=list)
    review_entry_ids: list[str] = Field(default_factory=list)
    unassigned_entry_ids: list[str] = Field(default_factory=list)
    cancellation_entry_ids: list[str] = Field(default_factory=list)
    suppression_demand_ids: list[str] = Field(default_factory=list)
    pending_audit_counts: dict[str, int] = Field(default_factory=dict)
    decided_audit_counts: dict[str, int] = Field(default_factory=dict)
    placement_count: int = 0
    changed_cell_count: int = 0
    hard_violation_count: int = 0
    export_failure_count: int = 0
    errors: list[ReconciliationError] = Field(default_factory=list)
    publication_state: Literal["blocked", "draft", "ready"] = "blocked"
    version_id: str | None = None
    content_hash: str | None = None

    @property
    def disposition_total(self) -> int:
        return (
            self.scheduled
            + self.needs_review
            + self.unassigned
            + self.confirmed_cancelled
            + self.suppressed_with_audit
        )


def _canonical_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python", exclude_none=True)
    if isinstance(value, Enum):
        return _canonical_value(value.value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, str):
        return _normalize_string(value)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical JSON does not allow non-finite numbers")
        return value
    if isinstance(value, Mapping):
        return {
            _normalize_string(str(key)): _canonical_value(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        raise TypeError("sets are forbidden in canonical JSON payloads")
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def _normalize_string(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip()
