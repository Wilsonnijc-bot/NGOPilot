"""Host-side controller for the complete RosterCopiilot weekly workflow."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ngopilot_mcp.shared.errors import InvalidRequestError, ToolError
from ngopilot_mcp.shared.tool_api import ToolCall, ToolExecution, ToolRuntime

from .artifacts import (
    FINAL_ARTIFACT_KIND,
    FINAL_FILENAME,
    REVIEW_ARTIFACT_KIND,
    REVIEW_FILENAME,
    XLSX_MEDIA_TYPE,
    validate_roster_workbook,
)
from .manifest import MANIFEST
from .schemas import (
    ExportCall,
    GetPublishedCall,
    PublishCall,
    RevalidateCall,
    ReviewCall,
    StartCall,
    StatusCall,
    validate_request,
)
from .state import (
    merge_native_refs,
    native_run_id,
    next_operations,
    normalized_state,
    publication_artifact,
    record_publication_artifact,
    staged_workbook_ref,
    unpack_worker_result,
)
from .validation import (
    ALLOWED_WORKBOOK_EXTENSIONS,
    MAX_WORKBOOK_BYTES,
    validate_workbook_source,
)


def _validation_error(error: ValidationError) -> InvalidRequestError:
    details = [
        {
            "type": item["type"],
            "location": list(item["loc"]),
            "message": item["msg"],
        }
        for item in error.errors()
    ]
    return InvalidRequestError(
        "The roster request does not match the selected operation.",
        details={"validation_errors": details},
    )


def _from_replay(response: dict[str, Any]) -> ToolExecution:
    allowed = {
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
    return ToolExecution(
        **{key: value for key, value in response.items() if key in allowed}
    )


def _require_run(job: Any, operation: str) -> str:
    run_id = native_run_id(job)
    if run_id is None:
        raise InvalidRequestError(
            f"This job has no durable RosterCopiilot run to {operation}.",
            details={"job_id": getattr(job, "job_id", None)},
        )
    return run_id


def _required_worker_string(response: dict[str, Any], key: str) -> str:
    value = response.get(key)
    if not isinstance(value, str) or not value:
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            f"RosterCopiilot omitted {key} from its worker response.",
        )
    return value


class RosterCopilotController:
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
            return await self._plain_native(request, runtime, "review")
        if isinstance(request, RevalidateCall):
            return await self._plain_native(request, runtime, "revalidate")
        if isinstance(request, ExportCall):
            return await self._export(request, runtime)
        if isinstance(request, PublishCall):
            return await self._publication(request, runtime)
        if isinstance(request, GetPublishedCall):
            return await self._publication(request, runtime)
        raise AssertionError("validated roster request did not match an operation")

    async def _start(self, request: StartCall, runtime: ToolRuntime) -> ToolExecution:
        hc_source = validate_workbook_source(
            request.input.hc_workbook_path,
            role="hc_workbook_path",
        )
        escort_source = validate_workbook_source(
            request.input.escort_workbook_path,
            role="escort_workbook_path",
        )
        public_input = request.input.model_dump(mode="json")
        job = runtime.create_job(
            tool_name=MANIFEST.name,
            request_id=request.request_id,
            input_payload=public_input,
        )
        handle = runtime.begin_operation(
            job=job,
            operation="start",
            request_id=request.request_id,
            payload=public_input,
        )
        if handle.replay is not None:
            return _from_replay(handle.replay)

        try:
            hc_staged = runtime.stage_file(
                job=job,
                role="hc_workbook",
                source_path=hc_source,
                allowed_extensions=ALLOWED_WORKBOOK_EXTENSIONS,
                max_bytes=MAX_WORKBOOK_BYTES,
                content_kind="office_zip",
            )
            escort_staged = runtime.stage_file(
                job=job,
                role="escort_workbook",
                source_path=escort_source,
                allowed_extensions=ALLOWED_WORKBOOK_EXTENSIONS,
                max_bytes=MAX_WORKBOOK_BYTES,
                content_kind="office_zip",
            )
            response = await runtime.call_worker(
                worker=MANIFEST.worker,
                tool_name=MANIFEST.name,
                operation="start",
                job=job,
                payload={
                    "hc_workbook_path": str(hc_staged),
                    "escort_workbook_path": str(escort_staged),
                    "hc_original_filename": hc_source.name,
                    "escort_original_filename": escort_source.name,
                    "week_start": request.input.week_start,
                    "changes": request.input.changes,
                },
            )
            result, native_status, native_refs, warnings = unpack_worker_result(
                response
            )
            if not isinstance(native_refs.get("run_id"), str):
                raise ToolError(
                    "NATIVE_PROTOCOL_ERROR",
                    "RosterCopiilot did not return its durable run_id.",
                )
            native_refs["input_workbooks"] = {
                "hc": staged_workbook_ref(
                    hc_staged,
                    role="hc_workbook",
                    original_name=hc_source.name,
                ),
                "escort": staged_workbook_ref(
                    escort_staged,
                    role="escort_workbook",
                    original_name=escort_source.name,
                ),
            }
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
        except Exception as exc:  # noqa: BLE001 - persist operation failure
            return runtime.fail_operation(job=job, handle=handle, error=exc)

    async def _status(self, request: StatusCall, runtime: ToolRuntime) -> ToolExecution:
        job = runtime.get_job(tool_name=MANIFEST.name, job_id=request.job_id)
        run_id = native_run_id(job)
        if run_id is None:
            return runtime.job_execution(job=job, operation="status")
        return await self._call_native(
            request=request,
            runtime=runtime,
            job=job,
            worker_payload={"native_run_id": run_id},
        )

    async def _plain_native(
        self,
        request: ReviewCall | RevalidateCall,
        runtime: ToolRuntime,
        operation_label: str,
    ) -> ToolExecution:
        job = runtime.get_job(tool_name=MANIFEST.name, job_id=request.job_id)
        run_id = _require_run(job, operation_label)
        return await self._call_native(
            request=request,
            runtime=runtime,
            job=job,
            worker_payload={
                "native_run_id": run_id,
                "command": request.input.model_dump(mode="json"),
            },
        )

    async def _export(self, request: ExportCall, runtime: ToolRuntime) -> ToolExecution:
        job = runtime.get_job(tool_name=MANIFEST.name, job_id=request.job_id)
        run_id = _require_run(job, "export")
        handle = runtime.begin_operation(
            job=job,
            operation="export",
            request_id=request.request_id,
            payload=request.input.model_dump(mode="json"),
        )
        if handle.replay is not None:
            return _from_replay(handle.replay)
        try:
            response = await runtime.call_worker(
                worker=MANIFEST.worker,
                tool_name=MANIFEST.name,
                operation="export",
                job=job,
                payload={"native_run_id": run_id},
            )
            result, native_status, incoming_refs, warnings = unpack_worker_result(
                response
            )
            candidate = validate_roster_workbook(
                _required_worker_string(response, "artifact_path"),
                expected_filename=REVIEW_FILENAME,
            )
            artifact = runtime.promote_artifact(
                job=job,
                source_path=candidate,
                kind=REVIEW_ARTIFACT_KIND,
                media_type=XLSX_MEDIA_TYPE,
                expected_extensions=(".xlsx",),
            )
            result["output_path"] = artifact.path
            review_export = result.get("review_export")
            if isinstance(review_export, dict):
                review_export["output_path"] = artifact.path
            refs = merge_native_refs(job, incoming_refs)
            native_source = response.get("native_source_path")
            if isinstance(native_source, str):
                refs["last_native_review_export_path"] = native_source
            return runtime.complete_operation(
                job=job,
                handle=handle,
                state=normalized_state(native_status),
                native_status=native_status,
                result=result,
                native_refs=refs,
                artifacts=[artifact],
                warnings=warnings,
                next_operations=next_operations(result, native_status),
            )
        except Exception as exc:  # noqa: BLE001 - persist operation failure
            return runtime.fail_operation(job=job, handle=handle, error=exc)

    async def _publication(
        self,
        request: PublishCall | GetPublishedCall,
        runtime: ToolRuntime,
    ) -> ToolExecution:
        job = runtime.get_job(tool_name=MANIFEST.name, job_id=request.job_id)
        run_id = _require_run(job, request.operation)
        public_payload = request.input.model_dump(mode="json")
        handle = runtime.begin_operation(
            job=job,
            operation=request.operation,
            request_id=request.request_id,
            payload=public_payload,
        )
        if handle.replay is not None:
            return _from_replay(handle.replay)
        try:
            response = await runtime.call_worker(
                worker=MANIFEST.worker,
                tool_name=MANIFEST.name,
                operation=request.operation,
                job=job,
                payload={
                    "native_run_id": run_id,
                    "command": public_payload,
                },
            )
            result, native_status, incoming_refs, warnings = unpack_worker_result(
                response
            )
            publication_id = _required_worker_string(response, "publication_id")
            expected_sha256 = _required_worker_string(response, "artifact_sha256")
            candidate = validate_roster_workbook(
                _required_worker_string(response, "artifact_path"),
                expected_filename=FINAL_FILENAME,
                expected_sha256=expected_sha256,
            )
            refs = merge_native_refs(job, incoming_refs)
            prior = publication_artifact(job, publication_id)
            artifacts: list[Any] = []
            if prior is None:
                artifact = runtime.promote_artifact(
                    job=job,
                    source_path=candidate,
                    kind=FINAL_ARTIFACT_KIND,
                    media_type=XLSX_MEDIA_TYPE,
                    expected_extensions=(".xlsx",),
                )
                refs = record_publication_artifact(
                    refs,
                    publication_id=publication_id,
                    artifact=artifact,
                )
                output_path = artifact.path
                artifacts.append(artifact)
            else:
                output_path = _required_mapping_string(prior, "path")
                validate_roster_workbook(
                    output_path,
                    expected_filename=FINAL_FILENAME,
                    expected_sha256=expected_sha256,
                )
            result["output_path"] = output_path
            publication = result.get("publication")
            if request.operation == "get_published":
                publication = result.get("requested_publication", publication)
            if isinstance(publication, dict):
                publication["output_path"] = output_path
            return runtime.complete_operation(
                job=job,
                handle=handle,
                state="published",
                native_status=native_status,
                result=result,
                native_refs=refs,
                artifacts=artifacts,
                warnings=warnings,
                next_operations=next_operations(result, native_status),
            )
        except Exception as exc:  # noqa: BLE001 - persist operation failure
            return runtime.fail_operation(job=job, handle=handle, error=exc)

    async def _call_native(
        self,
        *,
        request: StatusCall | ReviewCall | RevalidateCall,
        runtime: ToolRuntime,
        job: Any,
        worker_payload: dict[str, Any],
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
                payload=worker_payload,
            )
            result, native_status, incoming_refs, warnings = unpack_worker_result(
                response
            )
            refs = merge_native_refs(job, incoming_refs)
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
        except Exception as exc:  # noqa: BLE001 - persist operation failure
            return runtime.fail_operation(job=job, handle=handle, error=exc)


def _required_mapping_string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ToolError(
            "ARTIFACT_INTEGRITY_ERROR",
            f"The stored publication artifact mapping has no {key}.",
        )
    return item


CONTROLLER = RosterCopilotController()
