"""Host-side workflow controller for CareFlow paper forms to Excel."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ngopilot_mcp.shared.errors import InvalidRequestError, ToolError
from ngopilot_mcp.shared.tool_api import ToolCall, ToolExecution, ToolRuntime

from .artifacts import (
    EXCEL_ARTIFACT_KIND,
    EXCEL_MEDIA_TYPE,
    validate_excel_artifact,
)
from .manifest import MANIFEST
from .schemas import ExportCall, ReviewCall, StartCall, StatusCall, validate_request
from .state import (
    add_source_paths,
    native_batch_id,
    next_operations,
    normalized_state,
    record_ids,
    unpack_worker_result,
)
from .validation import ALLOWED_IMAGE_EXTENSIONS, start_warnings, validate_image_source


def _validation_error(error: ValidationError) -> InvalidRequestError:
    details = [
        {"type": item["type"], "location": list(item["loc"]), "message": item["msg"]}
        for item in error.errors()
    ]
    return InvalidRequestError(
        "The paper-forms request does not match the selected operation.",
        details={"validation_errors": details},
    )


def _from_replay(response: dict[str, Any]) -> ToolExecution:
    fields = {
        key: value
        for key, value in response.items()
        if key
        in {
            "operation",
            "job_id",
            "state",
            "result",
            "tool",
            "native_status",
            "native_refs",
            "artifacts",
            "next_operations",
            "warnings",
            "error",
            "schema_version",
        }
    }
    return ToolExecution(**fields)


class PaperFormsToExcelController:
    async def execute(self, call: ToolCall, runtime: ToolRuntime) -> ToolExecution:
        try:
            request = validate_request(
                {
                    "operation": call.operation,
                    "job_id": call.job_id,
                    "request_id": call.request_id,
                    "input": call.input,
                }
            )
        except ValidationError as exc:
            raise _validation_error(exc) from exc

        if isinstance(request, StartCall):
            return await self._start(request, runtime)
        if isinstance(request, StatusCall):
            return await self._status(request, runtime)
        if isinstance(request, ReviewCall):
            return await self._review(request, runtime)
        if isinstance(request, ExportCall):
            return await self._export(request, runtime)
        raise AssertionError("validated request did not match an operation")

    async def _start(self, request: StartCall, runtime: ToolRuntime) -> ToolExecution:
        source_paths = [
            validate_image_source(path) for path in request.input.image_paths
        ]
        public_input = request.input.model_dump(mode="json")
        job = runtime.create_job(
            tool_name=MANIFEST.name,
            request_id=request.request_id,
            input_payload=public_input,
        )
        handle = runtime.begin_operation(
            job=job,
            operation=request.operation,
            request_id=request.request_id,
            payload=public_input,
        )
        if handle.replay is not None:
            return _from_replay(handle.replay)

        try:
            staged_paths: list[Path] = []
            for index, source_path in enumerate(source_paths, start=1):
                staged_paths.append(
                    runtime.stage_file(
                        job=job,
                        role=f"completed_form_image_{index:03d}",
                        source_path=source_path,
                        allowed_extensions=ALLOWED_IMAGE_EXTENSIONS,
                        max_bytes=None,
                        content_kind="image",
                    )
                )

            native_payload = {
                "title": request.input.title,
                "image_paths": [str(path) for path in staged_paths],
                "original_filenames": [path.name for path in source_paths],
                "volunteer_team": request.input.volunteer_team,
                "visit_date": request.input.visit_date,
                "note": request.input.note,
                "auto_complete": request.input.auto_complete,
            }
            response = await runtime.call_worker(
                worker=MANIFEST.worker,
                tool_name=MANIFEST.name,
                operation=request.operation,
                job=job,
                payload=native_payload,
            )
            result, native_status, native_refs, native_warnings = unpack_worker_result(
                response
            )
            ids = record_ids(result)
            if len(ids) != len(staged_paths):
                raise ToolError(
                    "NATIVE_PROTOCOL_ERROR",
                    "CareFlow did not return one volunteer record for every staged image.",
                )
            source_map = {
                str(record_id): str(path)
                for record_id, path in zip(ids, staged_paths, strict=True)
            }
            native_refs["record_source_paths"] = source_map
            result = add_source_paths(result, source_map)
            warnings = start_warnings(len(staged_paths)) + native_warnings
            return runtime.complete_operation(
                job=job,
                handle=handle,
                state=normalized_state(native_status),
                native_status=native_status,
                result=result,
                native_refs=native_refs,
                artifacts=[],
                warnings=warnings,
                next_operations=next_operations(result, native_status),
            )
        except Exception as exc:  # noqa: BLE001 - every operation failure is persisted
            return runtime.fail_operation(job=job, handle=handle, error=exc)

    async def _status(self, request: StatusCall, runtime: ToolRuntime) -> ToolExecution:
        job = runtime.get_job(tool_name=MANIFEST.name, job_id=request.job_id)
        batch_id = native_batch_id(job)
        if batch_id is None:
            return runtime.job_execution(job=job, operation=request.operation)
        return await self._native_operation(
            request=request,
            runtime=runtime,
            job=job,
            payload={"native_batch_id": batch_id},
        )

    async def _review(self, request: ReviewCall, runtime: ToolRuntime) -> ToolExecution:
        job = runtime.get_job(tool_name=MANIFEST.name, job_id=request.job_id)
        batch_id = native_batch_id(job)
        if batch_id is None:
            raise InvalidRequestError("This job has no CareFlow batch to review.")

        known_ids = set(getattr(job, "native_refs", {}).get("record_ids", []))
        requested_ids = {review.record_id for review in request.input.reviews}
        unknown_ids = sorted(requested_ids - known_ids) if known_ids else []
        if unknown_ids:
            raise InvalidRequestError(
                "One or more record IDs do not belong to this job.",
                details={"unknown_record_ids": unknown_ids},
            )

        payload = {
            "native_batch_id": batch_id,
            "reviews": [
                {
                    "record_id": review.record_id,
                    "final_fields": review.final_fields.model_dump(mode="json"),
                    "reviewer": review.reviewer,
                }
                for review in request.input.reviews
            ],
        }
        return await self._native_operation(
            request=request,
            runtime=runtime,
            job=job,
            payload=payload,
        )

    async def _export(self, request: ExportCall, runtime: ToolRuntime) -> ToolExecution:
        job = runtime.get_job(tool_name=MANIFEST.name, job_id=request.job_id)
        batch_id = native_batch_id(job)
        if batch_id is None:
            raise InvalidRequestError("This job has no CareFlow batch to export.")

        handle = runtime.begin_operation(
            job=job,
            operation=request.operation,
            request_id=request.request_id,
            payload=request.input.model_dump(mode="json"),
        )
        if handle.replay is not None:
            return _from_replay(handle.replay)
        try:
            response = await runtime.call_worker(
                worker=MANIFEST.worker,
                tool_name=MANIFEST.name,
                operation=request.operation,
                job=job,
                payload={"native_batch_id": batch_id},
            )
            result, native_status, native_refs, warnings = unpack_worker_result(
                response
            )
            candidate = response.get("artifact_path")
            if not isinstance(candidate, str):
                raise ToolError(
                    "NATIVE_PROTOCOL_ERROR", "CareFlow omitted the Excel output path."
                )
            validated_path = validate_excel_artifact(candidate)
            artifact = runtime.promote_artifact(
                job=job,
                source_path=validated_path,
                kind=EXCEL_ARTIFACT_KIND,
                media_type=EXCEL_MEDIA_TYPE,
                expected_extensions=(".xlsx",),
            )
            result["output_path"] = artifact.path
            export_result = result.get("export")
            if isinstance(export_result, dict):
                export_result["output_path"] = artifact.path
            refs = dict(getattr(job, "native_refs", {}))
            refs.update(native_refs)
            return runtime.complete_operation(
                job=job,
                handle=handle,
                state=normalized_state(native_status),
                native_status=native_status,
                result=add_source_paths(result, refs.get("record_source_paths", {})),
                native_refs=refs,
                artifacts=[artifact],
                warnings=warnings,
                next_operations=next_operations(result, native_status),
            )
        except Exception as exc:  # noqa: BLE001 - every operation failure is persisted
            return runtime.fail_operation(job=job, handle=handle, error=exc)

    async def _native_operation(
        self,
        *,
        request: StatusCall | ReviewCall,
        runtime: ToolRuntime,
        job: Any,
        payload: dict[str, Any],
    ) -> ToolExecution:
        operation_payload = request.input.model_dump(mode="json")
        handle = runtime.begin_operation(
            job=job,
            operation=request.operation,
            request_id=request.request_id,
            payload=operation_payload,
        )
        if handle.replay is not None:
            return _from_replay(handle.replay)
        try:
            response = await runtime.call_worker(
                worker=MANIFEST.worker,
                tool_name=MANIFEST.name,
                operation=request.operation,
                job=job,
                payload=payload,
            )
            result, native_status, native_refs, warnings = unpack_worker_result(
                response
            )
            refs = dict(getattr(job, "native_refs", {}))
            refs.update(native_refs)
            result = add_source_paths(result, refs.get("record_source_paths", {}))
            return runtime.complete_operation(
                job=job,
                handle=handle,
                state=normalized_state(native_status),
                native_status=native_status,
                result=result,
                native_refs=refs,
                artifacts=[],
                warnings=warnings,
                next_operations=next_operations(result, native_status),
            )
        except Exception as exc:  # noqa: BLE001 - every operation failure is persisted
            return runtime.fail_operation(job=job, handle=handle, error=exc)


CONTROLLER = PaperFormsToExcelController()
