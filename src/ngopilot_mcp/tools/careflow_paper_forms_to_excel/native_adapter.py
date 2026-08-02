"""Worker-only adapter for CareFlow's volunteer-form services.

This module deliberately loads CareFlow's top-level ``app`` package lazily so
host-side manifest and schema discovery remain dependency-safe.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def _native_bindings() -> SimpleNamespace:
    from app.api.volunteer import BatchOut, _record_to_out
    from app.config import settings
    from app.db import engine, init_db
    from app.models import BatchStatus, VolunteerBatch, VolunteerRecord
    from app.services import excel_export, volunteer_form
    from sqlmodel import Session, select

    return SimpleNamespace(
        Session=Session,
        select=select,
        BatchOut=BatchOut,
        record_to_out=_record_to_out,
        settings=settings,
        engine=engine,
        init_db=init_db,
        BatchStatus=BatchStatus,
        VolunteerBatch=VolunteerBatch,
        VolunteerRecord=VolunteerRecord,
        excel_export=excel_export,
        volunteer_form=volunteer_form,
    )


def _status_value(status: Any) -> str:
    return str(getattr(status, "value", status))


def _get_batch(native: SimpleNamespace, session: Any, batch_id: int) -> Any:
    batch = session.get(native.VolunteerBatch, batch_id)
    if batch is None:
        raise ValueError(f"batch {batch_id} not found")
    return batch


def _list_records(native: SimpleNamespace, session: Any, batch_id: int) -> list[Any]:
    return list(
        session.exec(
            native.select(native.VolunteerRecord)
            .where(native.VolunteerRecord.batch_id == batch_id)
            .order_by(native.VolunteerRecord.id)
        ).all()
    )


def _serialize_batch(native: SimpleNamespace, batch: Any) -> dict[str, Any]:
    return native.BatchOut(**batch.model_dump()).model_dump(mode="json")


def _serialize_record(native: SimpleNamespace, record: Any) -> dict[str, Any]:
    return native.record_to_out(record).model_dump(mode="json")


def _snapshot(
    native: SimpleNamespace,
    session: Any,
    batch_id: int,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    batch = _get_batch(native, session, batch_id)
    records = _list_records(native, session, batch_id)
    reviewed_count = sum(bool(record.is_reviewed) for record in records)
    result: dict[str, Any] = {
        "batch": _serialize_batch(native, batch),
        "records": [_serialize_record(native, record) for record in records],
        "field_schema": native.volunteer_form.get_field_schema(),
        "reviewed_count": reviewed_count,
        "unreviewed_count": len(records) - reviewed_count,
    }
    if extra:
        result.update(extra)
    return {
        "native_status": _status_value(batch.status),
        "native_refs": {
            "batch_id": batch_id,
            "record_ids": [record.id for record in records],
        },
        "result": result,
        "warnings": [],
    }


def _require_batch_id(payload: dict[str, Any]) -> int:
    batch_id = payload.get("native_batch_id")
    if not isinstance(batch_id, int) or isinstance(batch_id, bool) or batch_id <= 0:
        raise ValueError("native_batch_id must be a positive integer")
    return batch_id


def _handle_start(
    native: SimpleNamespace, session: Any, payload: dict[str, Any]
) -> dict[str, Any]:
    image_paths = payload.get("image_paths")
    original_filenames = payload.get("original_filenames")
    if not isinstance(image_paths, list) or not image_paths:
        raise ValueError("image_paths must contain at least one staged image")
    if not isinstance(original_filenames, list) or len(original_filenames) != len(
        image_paths
    ):
        raise ValueError("original_filenames must align with image_paths")

    files: list[tuple[str, bytes]] = []
    for raw_path, raw_name in zip(image_paths, original_filenames, strict=True):
        if not isinstance(raw_path, str) or not Path(raw_path).is_absolute():
            raise ValueError("every staged image path must be absolute")
        if not isinstance(raw_name, str) or Path(raw_name).name != raw_name:
            raise ValueError("every original filename must be a plain filename")
        files.append((raw_name, Path(raw_path).read_bytes()))

    batch = native.volunteer_form.create_batch(
        session,
        title=payload["title"],
        volunteer_team=payload.get("volunteer_team"),
        visit_date=payload.get("visit_date"),
        note=payload.get("note"),
    )
    batch_id = int(batch.id)
    native.volunteer_form.add_photos(session, batch_id, files)
    try:
        native.volunteer_form.run_extraction(
            session,
            batch_id,
            auto_complete=payload.get("auto_complete", False),
        )
    except Exception as exc:  # noqa: BLE001 - CareFlow records FAILED before raising
        # CareFlow itself durably flips an uncaught extraction to FAILED. Return
        # that native batch reference so MCP status/recovery can still inspect it.
        response = _snapshot(
            native,
            session,
            batch_id,
            extra={
                "native_error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            },
        )
        response["warnings"] = [f"CareFlow extraction failed: {exc}"]
        return response
    return _snapshot(native, session, batch_id)


def _handle_status(
    native: SimpleNamespace, session: Any, payload: dict[str, Any]
) -> dict[str, Any]:
    return _snapshot(native, session, _require_batch_id(payload))


def _handle_review(
    native: SimpleNamespace, session: Any, payload: dict[str, Any]
) -> dict[str, Any]:
    batch_id = _require_batch_id(payload)
    _get_batch(native, session, batch_id)
    reviews = payload.get("reviews")
    if not isinstance(reviews, list) or not reviews:
        raise ValueError("reviews must contain at least one record")

    reviewed_ids: list[int] = []
    for review in reviews:
        if not isinstance(review, dict):
            raise TypeError("each review must be an object")
        record_id = review.get("record_id")
        record = session.get(native.VolunteerRecord, record_id)
        if record is None or record.batch_id != batch_id:
            raise ValueError(f"record {record_id} does not belong to batch {batch_id}")
        native.volunteer_form.review_record(
            session,
            record_id,
            final_fields=review["final_fields"],
            reviewer=review.get("reviewer"),
        )
        reviewed_ids.append(record_id)

    return _snapshot(
        native,
        session,
        batch_id,
        extra={"reviewed_record_ids": reviewed_ids},
    )


def _handle_export(
    native: SimpleNamespace, session: Any, payload: dict[str, Any]
) -> dict[str, Any]:
    batch_id = _require_batch_id(payload)
    batch = _get_batch(native, session, batch_id)
    all_records = _list_records(native, session, batch_id)
    reviewed_records = [record for record in all_records if record.is_reviewed]
    if not reviewed_records:
        raise ValueError(
            "This batch has no reviewed records; review at least one record before export."
        )

    rows = [
        {
            "final_fields": record.final_fields or {},
            "reviewer": record.reviewer,
            "reviewed_at": (
                record.reviewed_at.strftime("%Y-%m-%d %H:%M")
                if record.reviewed_at
                else None
            ),
        }
        for record in reviewed_records
    ]
    output_path = native.excel_export.make_export_path(batch_id).resolve()
    native.excel_export.export_batch(
        batch_title=batch.title,
        volunteer_team=batch.volunteer_team,
        rows=rows,
        out_path=output_path,
    )

    relative_path = str(output_path.relative_to(native.settings.data_path))
    batch.exported_file = relative_path
    batch.exported_at = datetime.utcnow()  # noqa: DTZ003 - matches CareFlow 0.4.8
    batch.status = native.BatchStatus.EXPORTED
    session.add(batch)
    session.commit()

    export_result = {
        "batch_id": batch_id,
        "exported_file": relative_path,
        "download_url": f"/api/files/{relative_path}",
        "row_count": len(rows),
    }
    response = _snapshot(
        native,
        session,
        batch_id,
        extra={
            "export": export_result,
            "exported_row_count": len(rows),
        },
    )
    response["artifact_path"] = str(output_path)
    if len(reviewed_records) != len(all_records):
        response["warnings"] = [
            (
                f"Partial export: {len(rows)} reviewed record(s) were exported and "
                f"{len(all_records) - len(rows)} unreviewed record(s) were omitted."
            )
        ]
    return response


def handle(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Execute one validated operation inside the managed CareFlow worker."""

    handlers = {
        "start": _handle_start,
        "status": _handle_status,
        "review": _handle_review,
        "export": _handle_export,
    }
    try:
        handler = handlers[operation]
    except KeyError as exc:
        raise ValueError(f"unsupported paper-forms operation: {operation}") from exc

    native = _native_bindings()
    native.init_db()
    with native.Session(native.engine) as session:
        return handler(native, session, payload)
