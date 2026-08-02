"""Workflow controller for the independent CareFlow meeting-notes tool."""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import ValidationError

from ngopilot_mcp.shared.errors import InvalidJobStateError, InvalidRequestError
from ngopilot_mcp.shared.tool_api import (
    ArtifactRef,
    ToolCall,
    ToolExecution,
    ToolRuntime,
)

from .artifacts import ARTIFACT_KIND, DOCX_MEDIA_TYPE, validate_native_docx
from .manifest import MANIFEST
from .schemas import (
    BurnRequest,
    ExportRequest,
    ReviewRequest,
    StartRequest,
    StatusRequest,
    parse_request,
)
from .state import (
    native_reference,
    native_status,
    next_operations,
    normalized_state,
    public_session,
)
from .validation import (
    AUDIO_EXTENSIONS,
    TEMPLATE_EXTENSIONS,
    validate_complete_slot_content,
    validate_start_files,
)


class MeetingNotesController:
    async def execute(self, call: ToolCall, runtime: ToolRuntime) -> ToolExecution:
        request = _validated_request(call)
        if isinstance(request, StartRequest):
            return await self._start(request, runtime)
        if isinstance(request, StatusRequest):
            return await self._status(request, runtime)
        if isinstance(request, ReviewRequest):
            return await self._review(request, runtime)
        if isinstance(request, ExportRequest):
            return self._export(request, runtime)
        if isinstance(request, BurnRequest):
            return await self._burn(request, runtime)
        raise InvalidRequestError(f"unsupported operation: {call.operation}")

    async def _start(
        self, request: StartRequest, runtime: ToolRuntime
    ) -> ToolExecution:
        try:
            audio_path, template_path = validate_start_files(request.input)
        except ValueError as exc:
            raise InvalidRequestError(str(exc)) from exc
        input_payload = request.input.model_dump(mode="json")
        job = runtime.create_job(
            tool_name=MANIFEST.name,
            request_id=request.request_id,
            input_payload=input_payload,
        )
        handle = runtime.begin_operation(
            job=job,
            operation=request.operation,
            request_id=request.request_id,
            payload=input_payload,
        )
        if handle.replay is not None:
            return _replayed_execution(handle.replay)

        try:
            staged_audio = runtime.stage_file(
                job=job,
                role="audio",
                source_path=audio_path,
                allowed_extensions=tuple(sorted(AUDIO_EXTENSIONS)),
                content_kind="audio",
            )
            staged_template = runtime.stage_file(
                job=job,
                role="report_template",
                source_path=template_path,
                allowed_extensions=tuple(sorted(TEMPLATE_EXTENSIONS)),
                content_kind=(
                    "office_zip" if template_path.suffix.lower() == ".docx" else None
                ),
            )
            worker_payload = {
                "title": request.input.title,
                "mode": request.input.mode,
                "audio_path": str(staged_audio),
                "template_path": str(staged_template),
                "note": request.input.note,
            }
            native = await runtime.call_worker(
                worker=MANIFEST.worker,
                tool_name=MANIFEST.name,
                operation="start",
                job=job,
                payload=worker_payload,
            )
            result = public_session(native, mode=request.input.mode)
            reference = native_reference(native)
            return runtime.complete_operation(
                job=job,
                handle=handle,
                state=normalized_state(result),
                native_status=native_status(result),
                result=result,
                native_refs={
                    "visit_session_id": reference,
                    "mode": request.input.mode,
                },
                next_operations=next_operations(result),
            )
        except Exception as exc:
            return runtime.fail_operation(job=job, handle=handle, error=exc)

    async def _status(
        self, request: StatusRequest, runtime: ToolRuntime
    ) -> ToolExecution:
        job = runtime.get_job(tool_name=MANIFEST.name, job_id=request.job_id)
        reference, mode = _job_identity(job)
        handle = runtime.begin_operation(
            job=job,
            operation=request.operation,
            request_id=request.request_id,
            payload={},
        )
        if handle.replay is not None:
            return _replayed_execution(handle.replay)
        try:
            native = await runtime.call_worker(
                worker=MANIFEST.worker,
                tool_name=MANIFEST.name,
                operation="status",
                job=job,
                payload={"native_session_id": reference},
            )
            result = public_session(native, mode=mode)
            state = normalized_state(result)
            if job.state == "exported" and state == "confirmed":
                state = "exported"
            return runtime.complete_operation(
                job=job,
                handle=handle,
                state=state,
                native_status=native_status(result),
                result=result,
                native_refs=dict(job.native_refs),
                next_operations=next_operations(result, exported=state == "exported"),
            )
        except Exception as exc:
            return runtime.fail_operation(job=job, handle=handle, error=exc)

    async def _review(
        self, request: ReviewRequest, runtime: ToolRuntime
    ) -> ToolExecution:
        job = runtime.get_job(tool_name=MANIFEST.name, job_id=request.job_id)
        reference, mode = _job_identity(job)
        if job.native_status not in {"pending_review", "confirmed"}:
            raise InvalidJobStateError(job.state, request.operation)
        try:
            validate_complete_slot_content(
                _template_contract(job.result),
                request.input.slot_content_final,
            )
        except ValueError as exc:
            raise InvalidRequestError(str(exc)) from exc
        payload = request.input.model_dump(mode="json")
        handle = runtime.begin_operation(
            job=job,
            operation=request.operation,
            request_id=request.request_id,
            payload=payload,
        )
        if handle.replay is not None:
            return _replayed_execution(handle.replay)
        try:
            native = await runtime.call_worker(
                worker=MANIFEST.worker,
                tool_name=MANIFEST.name,
                operation="review",
                job=job,
                payload={"native_session_id": reference, **payload},
            )
            result = public_session(native, mode=mode)
            if native_status(result) != "confirmed":
                raise ValueError("CareFlow phase two did not confirm the visit session")
            native_path = native.get("native_artifact_path")
            if not isinstance(native_path, str):
                raise ValueError("CareFlow phase two returned no generated DOCX path")
            validated_path = validate_native_docx(native_path)
            artifact = runtime.promote_artifact(
                job=job,
                source_path=validated_path,
                kind=ARTIFACT_KIND,
                media_type=DOCX_MEDIA_TYPE,
                expected_extensions=(".docx",),
            )
            return runtime.complete_operation(
                job=job,
                handle=handle,
                state="confirmed",
                native_status="confirmed",
                result=result,
                native_refs=dict(job.native_refs),
                artifacts=[artifact],
                next_operations=next_operations(result),
            )
        except Exception as exc:
            return runtime.fail_operation(job=job, handle=handle, error=exc)

    def _export(self, request: ExportRequest, runtime: ToolRuntime) -> ToolExecution:
        job = runtime.get_job(tool_name=MANIFEST.name, job_id=request.job_id)
        if job.native_status != "confirmed":
            raise InvalidJobStateError(job.state, request.operation)
        handle = runtime.begin_operation(
            job=job,
            operation=request.operation,
            request_id=request.request_id,
            payload={},
        )
        if handle.replay is not None:
            return _replayed_execution(handle.replay)
        try:
            current = runtime.job_execution(job=job, operation="export")
            artifact = _latest_meeting_note(current.artifacts)
            path = (
                artifact.path
                if isinstance(artifact, ArtifactRef)
                else artifact.get("path")
            )
            if not isinstance(path, str):
                raise ValueError("the registered meeting-note artifact has no path")
            validate_native_docx(path)
            result = dict(job.result)
            return runtime.complete_operation(
                job=job,
                handle=handle,
                state="exported",
                native_status=job.native_status,
                result=result,
                native_refs=dict(job.native_refs),
                artifacts=[artifact],
                next_operations=next_operations(result, exported=True),
            )
        except Exception as exc:
            return runtime.fail_operation(job=job, handle=handle, error=exc)

    async def _burn(self, request: BurnRequest, runtime: ToolRuntime) -> ToolExecution:
        job = runtime.get_job(tool_name=MANIFEST.name, job_id=request.job_id)
        reference, mode = _job_identity(job)
        handle = runtime.begin_operation(
            job=job,
            operation=request.operation,
            request_id=request.request_id,
            payload={},
        )
        if handle.replay is not None:
            return _replayed_execution(handle.replay)
        try:
            native = await runtime.call_worker(
                worker=MANIFEST.worker,
                tool_name=MANIFEST.name,
                operation="burn",
                job=job,
                payload={"native_session_id": reference},
            )
            result = public_session(native, mode=mode)
            result["burned"] = bool(native.get("burned"))
            state = normalized_state(result)
            if job.state == "exported" and state == "confirmed":
                state = "exported"
            return runtime.complete_operation(
                job=job,
                handle=handle,
                state=state,
                native_status=native_status(result),
                result=result,
                native_refs=dict(job.native_refs),
                next_operations=next_operations(result, exported=state == "exported"),
            )
        except Exception as exc:
            return runtime.fail_operation(job=job, handle=handle, error=exc)


CONTROLLER = MeetingNotesController()


def _validated_request(call: ToolCall) -> Any:
    try:
        return parse_request(
            {
                "operation": call.operation,
                "job_id": call.job_id,
                "request_id": call.request_id,
                "input": call.input,
            }
        )
    except ValidationError as exc:
        raise InvalidRequestError(
            "invalid careflow_meeting_notes request",
            details={"validation_errors": exc.errors(include_url=False)},
        ) from exc


def _job_identity(job: Any) -> tuple[int, str]:
    reference = job.native_refs.get("visit_session_id")
    mode = job.native_refs.get("mode", job.input_payload.get("mode"))
    if isinstance(reference, bool) or not isinstance(reference, int) or reference <= 0:
        raise InvalidJobStateError(job.state, "load native session")
    if mode not in {"home_visit", "internal_meeting"}:
        raise InvalidJobStateError(job.state, "load meeting-note mode")
    return reference, mode


def _template_contract(result: Mapping[str, Any]) -> Mapping[str, Any] | None:
    value = result.get("template_contract")
    return value if isinstance(value, Mapping) else None


def _latest_meeting_note(
    artifacts: list[ArtifactRef | dict[str, Any]],
) -> ArtifactRef | dict[str, Any]:
    matches = [
        artifact
        for artifact in artifacts
        if (
            artifact.kind if isinstance(artifact, ArtifactRef) else artifact.get("kind")
        )
        == ARTIFACT_KIND
    ]
    if not matches:
        raise InvalidJobStateError("unreviewed", "export")
    return matches[-1]


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
