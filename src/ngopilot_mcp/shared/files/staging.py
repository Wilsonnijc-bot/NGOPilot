"""Immutable local-path input staging."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path
from uuid import uuid4

from ...config import Settings
from ..errors import ToolError
from ..jobs.store import JobRecord
from .validation import validate_content

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class FileService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def job_root(self, job: JobRecord) -> Path:
        return (self.settings.jobs_root / job.tool_name / job.job_id).resolve()

    def ensure_job_directories(self, job: JobRecord) -> Path:
        root = self.job_root(job)
        for name in ("inputs", "intermediate", "outputs", "logs"):
            path = root / name
            path.mkdir(parents=True, exist_ok=True)
            try:
                path.chmod(0o700)
            except OSError:
                pass
        return root

    def stage_file(
        self,
        *,
        job: JobRecord,
        role: str,
        source_path: str | Path,
        allowed_extensions: tuple[str, ...],
        max_bytes: int | None = None,
        content_kind: str | None = None,
    ) -> Path:
        raw = Path(source_path).expanduser()
        if not raw.is_absolute():
            raise ToolError(
                "PATH_NOT_ABSOLUTE",
                f"The {role} path must be absolute.",
                details={"role": role, "path": str(raw)},
            )
        if raw.is_symlink():
            raise ToolError(
                "PATH_NOT_ALLOWED",
                f"The {role} path cannot be a symbolic link.",
                details={"role": role, "path": str(raw)},
            )
        try:
            source = raw.resolve(strict=True)
        except FileNotFoundError as exc:
            raise ToolError(
                "FILE_NOT_FOUND",
                f"The {role} file does not exist.",
                details={"role": role, "path": str(raw)},
            ) from exc
        if not source.is_file():
            raise ToolError(
                "PATH_NOT_ALLOWED",
                f"The {role} path must refer to a regular file.",
                details={"role": role, "path": str(source)},
            )
        if self.settings.allowed_input_roots and not any(
            source.is_relative_to(root) for root in self.settings.allowed_input_roots
        ):
            raise ToolError(
                "PATH_NOT_ALLOWED",
                f"The {role} file is outside the configured input roots.",
                details={"role": role, "path": str(source)},
            )
        if source.is_relative_to(self.settings.jobs_root):
            raise ToolError(
                "PATH_NOT_ALLOWED",
                "A job may not consume a file from an MCP private job directory.",
                details={"role": role, "path": str(source)},
            )

        suffix = source.suffix.lower()
        allowed = tuple(item.lower() for item in allowed_extensions)
        if suffix not in allowed:
            raise ToolError(
                "UNSUPPORTED_FILE_TYPE",
                f"The {role} file must use one of: {', '.join(allowed)}.",
                details={"role": role, "path": str(source), "allowed": list(allowed)},
            )
        size = source.stat().st_size
        if size <= 0:
            raise ToolError(
                "EMPTY_FILE",
                f"The {role} file is empty.",
                details={"role": role, "path": str(source)},
            )
        if max_bytes is not None and size > max_bytes:
            raise ToolError(
                "FILE_TOO_LARGE",
                f"The {role} file exceeds the {max_bytes}-byte limit.",
                details={"role": role, "size_bytes": size, "max_bytes": max_bytes},
            )
        validate_content(source, content_kind)

        inputs = self.ensure_job_directories(job) / "inputs"
        safe_role = _SAFE_NAME.sub("_", role).strip("._") or "input"
        digest = _sha256(source)[:12]
        target = inputs / f"{safe_role}_{digest}{suffix}"
        if target.exists():
            if _sha256(target) != _sha256(source):
                raise ToolError(
                    "INPUT_COLLISION",
                    "A staged input path exists with different content.",
                )
            return target
        temporary = inputs / f".{target.name}.{uuid4().hex}.tmp"
        shutil.copyfile(source, temporary)
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        return target.resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
