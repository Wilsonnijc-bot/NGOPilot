"""Private S3 mirroring and safe tenant-local upload resolution."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import mimetypes
import re
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import unquote, urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

import aiofiles
import boto3
from botocore.config import Config as BotoConfig
from fastapi import HTTPException, UploadFile, status

from .config import Settings
from .db import Database

logger = logging.getLogger(__name__)

PLACEHOLDER_PATTERN = re.compile(
    r"ngopilot-upload://[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/[^\s\"<>]+"
)
SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


class PlaceholderError(ValueError):
    pass


def parse_placeholder(value: str) -> tuple[UUID, str]:
    parsed = urlsplit(value)
    if parsed.scheme != "ngopilot-upload" or not parsed.netloc or parsed.query or parsed.fragment:
        raise PlaceholderError("Invalid upload placeholder")
    try:
        upload_id = UUID(parsed.netloc)
    except ValueError as error:
        raise PlaceholderError("Invalid upload identifier") from error
    encoded_name = parsed.path.removeprefix("/")
    if not encoded_name or "/" in encoded_name:
        raise PlaceholderError("Invalid upload filename")
    filename = unquote(encoded_name)
    if not filename or filename in {".", ".."} or Path(filename).name != filename:
        raise PlaceholderError("Invalid upload filename")
    return upload_id, filename


def safe_filename(value: str) -> str:
    cleaned = SAFE_FILENAME_PATTERN.sub("_", Path(value).name).strip("._")
    if not cleaned:
        cleaned = "upload"
    suffix = Path(value).suffix
    if suffix and not cleaned.endswith(suffix) and len(suffix) <= 16:
        cleaned += SAFE_FILENAME_PATTERN.sub("_", suffix)
    return cleaned[:180]


def _has_symlink_component(root: Path, relative: Path) -> bool:
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def validate_tenant_file(
    data_root: Path,
    user_id: UUID,
    local_path: str,
    area: str,
) -> Path:
    relative = Path(local_path)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise PlaceholderError("Stored upload path is invalid")
    data_root_resolved = data_root.resolve()
    if _has_symlink_component(data_root_resolved, relative):
        raise PlaceholderError("Stored upload path contains a symbolic link")
    candidate = (data_root_resolved / relative).resolve(strict=True)
    allowed = (data_root_resolved / "tenants" / str(user_id) / area).resolve(strict=True)
    if not candidate.is_relative_to(allowed) or not candidate.is_file():
        raise PlaceholderError("Stored upload path is outside the tenant directory")
    return candidate


def iter_mappings(value: Any, *, parse_json_strings: bool = True) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_mappings(child, parse_json_strings=parse_json_strings)
    elif isinstance(value, list):
        for child in value:
            yield from iter_mappings(child, parse_json_strings=parse_json_strings)
    elif parse_json_strings and isinstance(value, str) and len(value) <= 1_000_000:
        stripped = value.lstrip()
        if stripped.startswith(("{", "[")):
            try:
                decoded = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                return
            yield from iter_mappings(decoded, parse_json_strings=False)


class StorageService:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self._tasks: set[asyncio.Task[None]] = set()
        self._s3 = None
        if settings.s3_configured:
            self._s3 = boto3.client(
                "s3",
                region_name=settings.s3_region,
                endpoint_url=settings.s3_endpoint_url or None,
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
                config=BotoConfig(signature_version="s3v4"),
            )

    async def close(self) -> None:
        if not self._tasks:
            return
        await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def store_upload(
        self,
        user_id: UUID,
        upload_id_value: str,
        placeholder: str,
        file: UploadFile,
    ) -> dict[str, Any]:
        if self._s3 is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Object storage is not configured",
            )
        try:
            upload_id = UUID(upload_id_value)
            placeholder_id, placeholder_filename = parse_placeholder(placeholder)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
            ) from error
        if upload_id != placeholder_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Upload identifier does not match placeholder",
            )
        original_filename = Path(file.filename or "").name
        if not original_filename or original_filename != placeholder_filename:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Upload filename does not match placeholder",
            )

        content_type = file.content_type or "application/octet-stream"
        try:
            await self.db.create_upload(
                upload_id, user_id, original_filename, content_type, placeholder
            )
        except Exception as error:
            # A client UUID is an idempotency key; overwriting another object is never allowed.
            if error.__class__.__name__.endswith("UniqueViolationError"):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="Upload already exists"
                ) from error
            raise

        relative = (
            Path("tenants")
            / str(user_id)
            / "uploads"
            / str(upload_id)
            / safe_filename(original_filename)
        )
        destination = self.settings.data_root / relative
        destination.parent.mkdir(parents=True, exist_ok=False, mode=0o700)
        digest = hashlib.sha256()
        size = 0
        try:
            async with aiofiles.open(destination, "xb") as output:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > self.settings.max_upload_bytes:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail="Upload exceeds the configured size limit",
                        )
                    digest.update(chunk)
                    await output.write(chunk)
            destination.chmod(0o600)
            object_key = f"tenants/{user_id}/uploads/{upload_id}"
            await self._upload_private(destination, object_key, content_type, digest.hexdigest())
            await self.db.finish_upload(
                upload_id,
                user_id,
                size_bytes=size,
                sha256=digest.hexdigest(),
                local_path=relative.as_posix(),
                object_key=object_key,
            )
        except Exception as error:
            if destination.exists():
                destination.unlink()
            await self.db.fail_upload(upload_id, user_id, type(error).__name__)
            raise
        finally:
            await file.close()

        return {
            "id": str(upload_id),
            "placeholder": placeholder,
            "filename": original_filename,
            "content_type": content_type,
            "size_bytes": size,
            "sha256": digest.hexdigest(),
        }

    async def resolve_placeholder(self, user_id: UUID, placeholder: str) -> str:
        parse_placeholder(placeholder)
        deadline = asyncio.get_running_loop().time() + self.settings.upload_resolve_timeout_seconds
        while True:
            row = await self.db.upload_for_placeholder(user_id, placeholder)
            if row is not None and row["status"] == "ready" and row["local_path"]:
                return str(
                    validate_tenant_file(
                        self.settings.data_root, user_id, row["local_path"], "uploads"
                    )
                )
            if row is not None and row["status"] == "failed":
                raise PlaceholderError("Upload failed before the prompt was sent")
            if asyncio.get_running_loop().time() >= deadline:
                raise PlaceholderError("Upload is not ready; try sending the prompt again")
            await asyncio.sleep(0.1)

    async def resolve_payload(self, user_id: UUID, value: Any) -> Any:
        placeholders: set[str] = set()

        def collect(item: Any) -> None:
            if isinstance(item, str):
                placeholders.update(PLACEHOLDER_PATTERN.findall(item))
            elif isinstance(item, dict):
                for child in item.values():
                    collect(child)
            elif isinstance(item, list):
                for child in item:
                    collect(child)

        collect(value)
        if not placeholders:
            return value
        replacements = {
            item: await self.resolve_placeholder(user_id, item) for item in placeholders
        }

        def replace(item: Any) -> Any:
            if isinstance(item, str):
                for placeholder, path in replacements.items():
                    item = item.replace(placeholder, path)
                return item
            if isinstance(item, dict):
                return {key: replace(child) for key, child in item.items()}
            if isinstance(item, list):
                return [replace(child) for child in item]
            return item

        return replace(value)

    def schedule_artifact_mirror(self, user_id: UUID, payload: Any) -> None:
        task = asyncio.create_task(
            self._mirror_artifacts(user_id, payload), name=f"artifact-mirror-{user_id}"
        )
        self._tasks.add(task)
        task.add_done_callback(self._artifact_task_done)

    def _artifact_task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Artifact mirror failed: %s", type(task.exception()).__name__)

    async def artifact_download_url(self, user_id: UUID, local_path: str) -> dict[str, Any]:
        if self._s3 is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Object storage is not configured",
            )

        supplied = Path(local_path)
        data_root = self.settings.data_root.resolve()
        if supplied.is_absolute():
            try:
                relative = supplied.resolve(strict=True).relative_to(data_root)
            except (FileNotFoundError, OSError, ValueError) as error:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found"
                ) from error
        else:
            relative = supplied

        try:
            validate_tenant_file(self.settings.data_root, user_id, relative.as_posix(), "workflow")
        except (PlaceholderError, FileNotFoundError, OSError) as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found"
            ) from error

        row = await self.db.artifact_for_local_path(user_id, relative.as_posix())
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Artifact is not available yet",
            )

        filename = safe_filename(row["filename"])
        url = await asyncio.to_thread(
            self._s3.generate_presigned_url,
            "get_object",
            Params={
                "Bucket": self.settings.s3_bucket,
                "Key": row["object_key"],
                "ResponseContentDisposition": f'attachment; filename="{filename}"',
                "ResponseContentType": row["content_type"],
            },
            ExpiresIn=300,
        )
        return {
            "url": url,
            "filename": row["filename"],
            "content_type": row["content_type"],
            "size_bytes": row["size_bytes"],
            "sha256": row["sha256"],
            "expires_in": 300,
        }

    async def _mirror_artifacts(self, user_id: UUID, payload: Any) -> None:
        if self._s3 is None:
            return
        seen: set[Path] = set()
        for mapping in iter_mappings(payload):
            job_id = mapping.get("job_id")
            if not isinstance(job_id, str) or len(job_id) > 96:
                job_id = None
            for key in ("path", "output_path", "artifact_path"):
                raw_path = mapping.get(key)
                if not isinstance(raw_path, str) or not raw_path.startswith("/"):
                    continue
                try:
                    path = Path(raw_path).resolve(strict=True)
                    workflow = (
                        self.settings.data_root / "tenants" / str(user_id) / "workflow"
                    ).resolve(strict=True)
                except (FileNotFoundError, OSError):
                    continue
                if path in seen or not path.is_file() or not path.is_relative_to(workflow):
                    continue
                relative = path.relative_to(self.settings.data_root.resolve())
                if _has_symlink_component(self.settings.data_root.resolve(), relative):
                    continue
                seen.add(path)
                digest, size = await asyncio.to_thread(self._digest_file, path)
                content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                artifact_id = uuid5(NAMESPACE_URL, f"{user_id}:{relative.as_posix()}")
                object_key = f"tenants/{user_id}/artifacts/{artifact_id}"
                await self._upload_private(path, object_key, content_type, digest)
                await self.db.upsert_artifact(
                    artifact_id=artifact_id,
                    user_id=user_id,
                    job_id=job_id,
                    filename=path.name,
                    content_type=content_type,
                    size_bytes=size,
                    sha256=digest,
                    local_path=relative.as_posix(),
                    object_key=object_key,
                )

    async def _upload_private(
        self, path: Path, object_key: str, content_type: str, digest: str
    ) -> None:
        assert self._s3 is not None
        await asyncio.to_thread(
            self._s3.upload_file,
            str(path),
            self.settings.s3_bucket,
            object_key,
            ExtraArgs={
                "ContentType": content_type,
                "Metadata": {"sha256": digest},
                "ServerSideEncryption": "AES256",
            },
        )

    @staticmethod
    def _digest_file(path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size
