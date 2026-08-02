"""Validated immutable output promotion."""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from uuid import uuid4

from ..errors import ToolError
from ..jobs.store import JobRecord, JobStore
from ..tool_api import ArtifactRef
from .staging import FileService
from .validation import validate_content


class ArtifactService:
    def __init__(self, files: FileService, jobs: JobStore):
        self.files = files
        self.jobs = jobs

    def promote(
        self,
        *,
        job: JobRecord,
        source_path: str | Path,
        kind: str,
        media_type: str,
        expected_extensions: tuple[str, ...],
    ) -> ArtifactRef:
        source = Path(source_path).expanduser().resolve(strict=True)
        if not source.is_file() or source.stat().st_size <= 0:
            raise ToolError(
                "OUTPUT_VALIDATION_FAILED",
                "The native output is missing or empty.",
                details={"path": str(source)},
            )
        suffix = source.suffix.lower()
        allowed = tuple(item.lower() for item in expected_extensions)
        if suffix not in allowed:
            raise ToolError(
                "OUTPUT_VALIDATION_FAILED",
                "The native output has an unexpected file type.",
                details={"path": str(source), "allowed": list(allowed)},
            )
        content_kind = (
            "pdf"
            if suffix == ".pdf"
            else "office_zip"
            if suffix in {".docx", ".xlsx", ".xlsm"}
            else None
        )
        validate_content(source, content_kind)

        outputs = self.files.ensure_job_directories(job) / "outputs"
        target = outputs / f"{uuid4().hex[:12]}_{source.name}"
        temporary = outputs / f".{target.name}.tmp"
        shutil.copyfile(source, temporary)
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        digest = _sha256(target)
        return self.jobs.register_artifact(
            job_id=job.job_id,
            kind=kind,
            path=target.resolve(),
            native_path=str(source),
            media_type=media_type,
            size_bytes=target.stat().st_size,
            sha256=digest,
        )

    def verify_registered(
        self,
        *,
        job: JobRecord,
        artifact: ArtifactRef,
    ) -> ArtifactRef:
        path = Path(artifact.path).resolve()
        outputs = (self.files.ensure_job_directories(job) / "outputs").resolve()
        if not path.is_relative_to(outputs) or not path.is_file():
            raise ToolError(
                "ARTIFACT_INTEGRITY_ERROR",
                "The registered artifact is missing or outside its job output directory.",
                details={"artifact_id": artifact.artifact_id, "path": str(path)},
            )
        size = path.stat().st_size
        digest = _sha256(path)
        if size != artifact.size_bytes or digest != artifact.sha256:
            raise ToolError(
                "ARTIFACT_INTEGRITY_ERROR",
                "The registered artifact no longer matches its stored integrity record.",
                details={
                    "artifact_id": artifact.artifact_id,
                    "path": str(path),
                    "expected_size_bytes": artifact.size_bytes,
                    "actual_size_bytes": size,
                    "expected_sha256": artifact.sha256,
                    "actual_sha256": digest,
                },
            )
        validate_content(
            path,
            "pdf"
            if path.suffix.lower() == ".pdf"
            else "office_zip"
            if path.suffix.lower() in {".docx", ".xlsx", ".xlsm"}
            else None,
        )
        return artifact


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
