"""Entity-resolution helpers for imported workbook aliases."""
from __future__ import annotations

import difflib
import re
import unicodedata
from collections import defaultdict
from typing import Any

from .base import ImportResult
from .models import ImportAmbiguity, ImportBatchSummary, ParsedRecord, SourceRef

DOC_REF = "docs/spec/excel_io_contract.md §6"


def normalize_alias(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"\s+", "", text)
    return text.strip().lower()


def _record_dict(record: ParsedRecord[Any]) -> dict[str, Any]:
    return record.record if isinstance(record.record, dict) else {}


def _is_probable_full_name(alias: str) -> bool:
    # Workbook schedule aliases are usually masked short names (e.g. Y珍).
    # Three+ CJK chars from transfer logs are treated as privacy-sensitive full
    # names until a human maps them.
    return len(alias) >= 3 and bool(re.fullmatch(r"[一-鿿]+", alias))


def resolve_import_batch(*results: ImportResult[dict[str, Any]]) -> ImportResult[dict[str, Any]]:
    worker_sources: dict[str, list[tuple[str, SourceRef]]] = defaultdict(list)
    elder_sources: dict[str, list[tuple[str, SourceRef]]] = defaultdict(list)
    records: list[ParsedRecord[dict[str, Any]]] = []
    ambiguities: list[ImportAmbiguity] = []

    for result in results:
        for parsed in result.records:
            data = _record_dict(parsed)
            for key in ("worker_alias", "preferred_worker_alias", "worker_before"):
                alias = data.get(key)
                if alias:
                    worker_sources[normalize_alias(alias)].append((str(alias), parsed.source))
            for key in ("worker_after_raw",):
                alias = data.get(key)
                if alias:
                    clean = re.sub(r"\(.*?\)", "", str(alias)).strip()
                    worker_sources[normalize_alias(clean)].append((clean, parsed.source))
            for key in ("elder_alias", "case_raw"):
                alias = data.get(key)
                if alias:
                    elder_sources[normalize_alias(alias)].append((str(alias), parsed.source))
            full_name = data.get("elder_full_name")
            if full_name:
                elder_sources[normalize_alias(full_name)].append((str(full_name), parsed.source))

    for entity_type, sources in (("worker", worker_sources), ("elder", elder_sources)):
        for norm, appearances in sources.items():
            display_values = sorted({alias for alias, _ in appearances})
            if not norm:
                continue
            if len(display_values) == 1:
                alias = display_values[0]
                if entity_type == "elder" and _is_probable_full_name(alias):
                    ambiguities.append(ImportAmbiguity(
                        code="FULL_NAME_LEAK",
                        message=f"full elder name {alias!r} needs manual alias mapping",
                        source=appearances[0][1],
                        severity="warning",
                        raw_value=alias,
                        resolution_hint="map this full name to the masked roster alias",
                    ))
                    continue
                records.append(ParsedRecord(
                    record={
                        "entity_type": entity_type,
                        "alias": alias,
                        "canonical_alias": alias,
                        "confidence": "exact",
                        "source_count": len(appearances),
                    },
                    source=appearances[0][1],
                    parse_confidence="high",
                ))
            else:
                ambiguities.append(ImportAmbiguity(
                    code="ALIAS_COLLISION",
                    message=f"{entity_type} alias normalises to multiple displays",
                    source=appearances[0][1],
                    severity="blocking",
                    candidates=tuple(display_values),
                    raw_value=", ".join(display_values),
                    resolution_hint="choose one canonical display or split entities",
                ))

        values = sorted({display for appearances in sources.values()
                         for display, _ in appearances})
        for i, left in enumerate(values):
            for right in values[i + 1:]:
                if left == right:
                    continue
                ratio = difflib.SequenceMatcher(
                    None, normalize_alias(left), normalize_alias(right)).ratio()
                if 0.82 <= ratio < 1:
                    ambiguities.append(ImportAmbiguity(
                        code="FUZZY_ALIAS_MATCH",
                        message=f"possible {entity_type} alias match requires review",
                        severity="warning",
                        candidates=(left, right),
                        raw_value=f"{left} ~ {right}",
                    ))

    summary = ImportBatchSummary(
        parser_name="entity_resolution",
        status="ok",
        parsed_count=len(records),
        inferred_count=len(records),
        flagged_count=len(ambiguities),
        silently_dropped_cells=0,
        notes=(f"Received {len(results)} parser result(s).",),
        doc_ref=DOC_REF,
    )
    return ImportResult(
        summary=summary,
        records=tuple(records),
        ambiguities=tuple(ambiguities),
    )
