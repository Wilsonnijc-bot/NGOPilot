"""Host-side workflow controller for CareFlow government forms."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from ngopilot_mcp.shared.errors import (
    InvalidJobStateError,
    InvalidRequestError,
    ToolError,
)
from ngopilot_mcp.shared.tool_api import ToolCall, ToolExecution, ToolRuntime

from .artifacts import ARTIFACT_KIND, PDF_MEDIA_TYPE, validate_native_pdf
from .manifest import MANIFEST
from .schemas import (
    ExportCall,
    ImageSource,
    ListTemplatesCall,
    ReviewCall,
    StartCall,
    StatusCall,
    validate_request,
)
from .state import reviewed_values, unpack_export, unpack_start, validate_discovery
from .validation import (
    ALL_IMAGE_EXTENSIONS,
    preview_field_keys,
    require_ready_template,
    sha256_file,
    supported_image_extensions,
    validate_complete_field_values,
    validate_image_source,
)


class GovernmentFormsController:
    async def execute(self, call: ToolCall, runtime: ToolRuntime) -> ToolExecution:
        request = _validated_request(call)
        if isinstance(request, ListTemplatesCall):
            return await self._list_templates(request, runtime)
        if isinstance(request, StartCall):
            return await self._start(request, runtime)
        if isinstance(request, StatusCall):
            return self._status(request, runtime)
        if isinstance(request, ReviewCall):
            return self._review(request, runtime)
        if isinstance(request, ExportCall):
            return await self._export(request, runtime)
        raise AssertionError("validated request did not match an operation")

    async def _list_templates(
        self,
        request: ListTemplatesCall,
        runtime: ToolRuntime,
    ) -> ToolExecution:
        result = await _discover(runtime)
        return ToolExecution(
            tool=MANIFEST.name,
            operation=request.operation,
            job_id=None,
            state="succeeded",
            native_status="ready",
            result=result,
            next_operations=["start"],
            warnings=deepcopy(result.get("warnings", [])),
        )

    async def _start(self, request: StartCall, runtime: ToolRuntime) -> ToolExecution:
        discovery = await _discover(runtime)
        require_ready_template(discovery, request.input.template_id)
        source = request.input.source
        source_path = None
        extensions = supported_image_extensions(discovery)
        if isinstance(source, ImageSource):
            source_path = validate_image_source(
                source.image_path,
                supported_extensions=extensions,
            )

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
            return _replayed_execution(handle.replay)

        try:
            native_source = source.model_dump(mode="json")
            source_metadata: dict[str, Any] = {"kind": source.kind}
            if source_path is not None:
                staged = runtime.stage_file(
                    job=job,
                    role="elder_profile_image",
                    source_path=source_path,
                    allowed_extensions=ALL_IMAGE_EXTENSIONS,
                    max_bytes=None,
                    content_kind="image",
                )
                native_source = {"kind": "image", "image_path": str(staged)}
                source_metadata.update(
                    {
                        "staged_path": str(staged),
                        "sha256": sha256_file(staged),
                        "original_filename": source_path.name,
                    }
                )
            response = await runtime.call_worker(
                worker=MANIFEST.worker,
                tool_name=MANIFEST.name,
                operation=request.operation,
                job=job,
                payload={
                    "template_id": request.input.template_id,
                    "use_llm": request.input.use_llm,
                    "source_hint": request.input.source_hint,
                    "source": native_source,
                },
            )
            result, native_refs, warnings = unpack_start(response)
            preview_field_keys(result)
            result["source"] = source_metadata
            native_refs["source"] = deepcopy(source_metadata)
            return runtime.complete_operation(
                job=job,
                handle=handle,
                state="pending_review",
                native_status="pending_review",
                result=result,
                native_refs=native_refs,
                artifacts=[],
                warnings=warnings,
                next_operations=["status", "review"],
            )
        except Exception as exc:  # noqa: BLE001 - start failures are durable
            return runtime.fail_operation(job=job, handle=handle, error=exc)

    def _status(self, request: StatusCall, runtime: ToolRuntime) -> ToolExecution:
        job = runtime.get_job(tool_name=MANIFEST.name, job_id=request.job_id)
        return runtime.job_execution(job=job, operation=request.operation)

    def _review(self, request: ReviewCall, runtime: ToolRuntime) -> ToolExecution:
        job = runtime.get_job(tool_name=MANIFEST.name, job_id=request.job_id)
        if job.state not in {"pending_review", "reviewed"}:
            raise InvalidJobStateError(job.state, request.operation)
        values = request.input.field_values
        validate_complete_field_values(job.result, values)
        operation_payload = request.input.model_dump(mode="json")
        handle = runtime.begin_operation(
            job=job,
            operation=request.operation,
            request_id=request.request_id,
            payload=operation_payload,
        )
        if handle.replay is not None:
            return _replayed_execution(handle.replay)
        try:
            result = deepcopy(job.result)
            result["reviewed_values"] = dict(values)
            result["review"] = {
                "field_values": dict(values),
                "reviewer": request.input.reviewer,
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            }
            return runtime.complete_operation(
                job=job,
                handle=handle,
                state="reviewed",
                native_status=job.native_status,
                result=result,
                native_refs=dict(job.native_refs),
                artifacts=[],
                warnings=list(job.warnings),
                next_operations=["status", "review", "export"],
            )
        except Exception as exc:  # noqa: BLE001 - preserve last reviewable state
            return runtime.fail_operation(
                job=job,
                handle=handle,
                error=exc,
                state=job.state,
            )

    async def _export(self, request: ExportCall, runtime: ToolRuntime) -> ToolExecution:
        job = runtime.get_job(tool_name=MANIFEST.name, job_id=request.job_id)
        if job.state == "exported":
            return runtime.job_execution(job=job, operation=request.operation)
        if job.state != "reviewed":
            raise InvalidJobStateError(job.state, request.operation)
        field_values = reviewed_values(job.result)
        elder_profile = job.result.get("elder_profile")
        template_id = job.result.get("template_id")
        template = job.result.get("template")
        if field_values is None or not isinstance(elder_profile, dict):
            raise InvalidJobStateError(job.state, request.operation)
        if not isinstance(template_id, str) or not isinstance(template, Mapping):
            raise InvalidJobStateError(job.state, request.operation)
        expected_pages = template.get("pdf_pages")
        if not isinstance(expected_pages, int) or expected_pages <= 0:
            raise ToolError(
                "NATIVE_PROTOCOL_ERROR",
                "The persisted CareFlow template has no valid page count.",
            )

        handle = runtime.begin_operation(
            job=job,
            operation=request.operation,
            request_id=request.request_id,
            payload={},
        )
        if handle.replay is not None:
            return _replayed_execution(handle.replay)
        try:
            response = await runtime.call_worker(
                worker=MANIFEST.worker,
                tool_name=MANIFEST.name,
                operation=request.operation,
                job=job,
                payload={
                    "template_id": template_id,
                    "elder_profile": deepcopy(elder_profile),
                    "field_values": deepcopy(field_values),
                },
            )
            native_result, native_refs, warnings, path, observed_pages = unpack_export(
                response
            )
            validated = validate_native_pdf(
                path,
                expected_page_count=expected_pages,
                observed_page_count=observed_pages,
            )
            artifact = runtime.promote_artifact(
                job=job,
                source_path=validated,
                kind=ARTIFACT_KIND,
                media_type=PDF_MEDIA_TYPE,
                expected_extensions=(".pdf",),
            )
            result = deepcopy(job.result)
            result["export"] = native_result
            result["output_path"] = artifact.path
            refs = dict(job.native_refs)
            refs.update(native_refs)
            return runtime.complete_operation(
                job=job,
                handle=handle,
                state="exported",
                native_status="filled",
                result=result,
                native_refs=refs,
                artifacts=[artifact],
                warnings=list(job.warnings) + warnings,
                next_operations=["status"],
            )
        except Exception as exc:  # noqa: BLE001 - preserve reviewed snapshot
            return runtime.fail_operation(
                job=job,
                handle=handle,
                error=exc,
                state=job.state,
            )


CONTROLLER = GovernmentFormsController()


async def _discover(runtime: ToolRuntime) -> dict[str, Any]:
    response = await runtime.call_worker_discovery(
        worker=MANIFEST.worker,
        tool_name=MANIFEST.name,
        operation="list_templates",
        payload={},
    )
    return validate_discovery(response)


def _validated_request(call: ToolCall) -> Any:
    try:
        return validate_request(
            {
                "operation": call.operation,
                "job_id": call.job_id,
                "request_id": call.request_id,
                "input": call.input,
            }
        )
    except ValidationError as exc:
        raise InvalidRequestError(
            "The government-forms request does not match the selected operation.",
            details={"validation_errors": exc.errors(include_url=False)},
        ) from exc


def _replayed_execution(payload: Mapping[str, Any]) -> ToolExecution:
    fields = {
        key: value
        for key, value in payload.items()
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
