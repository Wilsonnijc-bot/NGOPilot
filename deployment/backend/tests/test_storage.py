from __future__ import annotations

import io
import json
from pathlib import Path
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError

from ngopilot_gateway.storage import (
    RUNTIME_CACHE_MARKER,
    PlaceholderError,
    StorageService,
    parse_placeholder,
    validate_tenant_file,
)


class UploadDatabase:
    def __init__(self, row: dict[str, object] | None):
        self.row = row

    async def upload_for_placeholder(self, user_id, placeholder):
        return self.row


class CacheDatabase:
    def __init__(self, uploads=None, artifact=None):
        self.uploads = uploads or []
        self.artifact = artifact
        self.artifacts: dict[str, dict[str, object]] = {}

    async def ready_uploads_for_user(self, user_id):
        return self.uploads

    async def artifact_for_local_path(self, user_id, local_path):
        return self.artifact or self.artifacts.get(local_path)

    async def upsert_artifact(self, **values):
        self.artifacts[str(values["local_path"])] = values


class MemoryS3:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        self.objects[key] = Path(filename).read_bytes()

    def download_file(self, bucket, key, filename):
        Path(filename).write_bytes(self.objects[key])

    def put_object(self, *, Bucket, Key, Body, **kwargs):
        self.objects[Key] = bytes(Body)

    def get_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[Key])}

    def list_objects_v2(self, *, Bucket, Prefix, ContinuationToken=None):
        return {
            "Contents": [{"Key": key} for key in self.objects if key.startswith(Prefix)],
            "IsTruncated": False,
        }

    def list_object_versions(self, *, Bucket, Prefix, **kwargs):
        return {
            "Versions": [
                {"Key": key, "VersionId": "current", "IsLatest": True}
                for key in self.objects
                if key.startswith(Prefix)
            ],
            "DeleteMarkers": [],
            "IsTruncated": False,
        }

    def delete_objects(self, *, Bucket, Delete):
        for item in Delete["Objects"]:
            self.objects.pop(item["Key"], None)

    def generate_presigned_url(self, operation, *, Params, ExpiresIn):
        return f"https://s3.example.test/{Params['Key']}?expires={ExpiresIn}"


class FailingUploadS3(MemoryS3):
    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        raise RuntimeError("simulated S3 failure")


def test_parse_placeholder_round_trip() -> None:
    upload_id = uuid4()
    placeholder = f"ngopilot-upload://{upload_id}/case%20notes.pdf"

    assert parse_placeholder(placeholder) == (upload_id, "case notes.pdf")


@pytest.mark.parametrize(
    "placeholder",
    [
        "https://example.test/file.txt",
        "ngopilot-upload://not-a-uuid/file.txt",
        "ngopilot-upload://00000000-0000-0000-0000-000000000000/../file.txt",
    ],
)
def test_parse_placeholder_rejects_unsafe_values(placeholder: str) -> None:
    with pytest.raises(PlaceholderError):
        parse_placeholder(placeholder)


@pytest.mark.asyncio
async def test_resolve_payload_uses_only_owned_ready_upload(settings) -> None:
    user_id = uuid4()
    upload_id = uuid4()
    placeholder = f"ngopilot-upload://{upload_id}/source.xlsx"
    relative = Path("tenants") / str(user_id) / "uploads" / str(upload_id) / "source.xlsx"
    path = settings.data_root / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"input")
    service = StorageService(
        settings,
        UploadDatabase({"status": "ready", "local_path": relative.as_posix()}),
    )

    prompt = f'Turn these forms into Excel\n\nAttachments:\n["{placeholder}"]'
    resolved = await service.resolve_payload(user_id, {"prompt": prompt})

    assert resolved == {
        "prompt": f'Turn these forms into Excel\n\nAttachments:\n["{path.resolve()}"]'
    }


def test_tenant_file_rejects_symlink_escape(settings, tmp_path: Path) -> None:
    user_id = uuid4()
    upload_root = settings.data_root / "tenants" / str(user_id) / "uploads"
    upload_root.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    (upload_root / "link.txt").symlink_to(outside)
    relative = Path("tenants") / str(user_id) / "uploads" / "link.txt"

    with pytest.raises(PlaceholderError):
        validate_tenant_file(settings.data_root, user_id, relative.as_posix(), "uploads")


@pytest.mark.asyncio
async def test_tenant_cache_round_trips_through_s3_and_removes_old_snapshot(settings) -> None:
    user_id = uuid4()
    upload_id = uuid4()
    tenant = settings.data_root / "tenants" / str(user_id)
    session_file = tenant / "goose" / "state" / "session.json"
    database_file = tenant / "workflow" / "jobs.sqlite3"
    temporary_file = tenant / "tmp" / "large-response.txt"
    upload_relative = Path("tenants") / str(user_id) / "uploads" / str(upload_id) / "source.xlsx"
    upload_file = settings.data_root / upload_relative
    for path, content in (
        (session_file, b"session-one"),
        (database_file, b"sqlite-state"),
        (temporary_file, b"discard-me"),
        (upload_file, b"excel-input"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    upload_key = f"tenants/{user_id}/uploads/{upload_id}"
    s3 = MemoryS3()
    s3.objects[upload_key] = b"excel-input"
    database = CacheDatabase(
        uploads=[
            {
                "local_path": upload_relative.as_posix(),
                "object_key": upload_key,
                "size_bytes": len(b"excel-input"),
                "sha256": StorageService._digest_file(upload_file)[0],
            }
        ]
    )
    service = StorageService(settings, database)
    service._s3 = s3

    await service.persist_and_evict_tenant_cache(user_id)

    assert not tenant.exists()
    pointer_key = service._snapshot_pointer_key(user_id)
    first_pointer = json.loads(s3.objects[pointer_key])
    first_prefix = f"tenants/{user_id}/runtime-snapshots/{first_pointer['snapshot_id']}/"
    assert any(key.startswith(first_prefix) for key in s3.objects)
    assert all(b"discard-me" not in value for value in s3.objects.values())

    await service.restore_tenant_cache(user_id)

    assert session_file.read_bytes() == b"session-one"
    assert database_file.read_bytes() == b"sqlite-state"
    assert upload_file.read_bytes() == b"excel-input"
    assert not temporary_file.exists()
    assert (tenant / RUNTIME_CACHE_MARKER).is_file()

    session_file.write_bytes(b"session-two")
    await service.persist_and_evict_tenant_cache(user_id)

    second_pointer = json.loads(s3.objects[pointer_key])
    assert second_pointer["snapshot_id"] != first_pointer["snapshot_id"]
    assert not any(key.startswith(first_prefix) for key in s3.objects)


@pytest.mark.asyncio
async def test_artifact_url_remains_available_after_local_cache_eviction(settings) -> None:
    user_id = uuid4()
    relative = Path("tenants") / str(user_id) / "workflow" / "exports" / "roster.xlsx"
    artifact = {
        "filename": "roster.xlsx",
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "object_key": f"tenants/{user_id}/artifacts/example",
        "size_bytes": 1234,
        "sha256": "a" * 64,
    }
    service = StorageService(settings, CacheDatabase(artifact=artifact))
    service._s3 = MemoryS3()

    result = await service.artifact_download_url(user_id, relative.as_posix())

    assert result["filename"] == "roster.xlsx"
    assert result["url"].startswith("https://s3.example.test/")


@pytest.mark.asyncio
async def test_agent_text_file_path_is_mirrored_before_immediate_download(settings) -> None:
    user_id = uuid4()
    relative = Path("tenants") / str(user_id) / "generated report.xlsx"
    path = settings.data_root / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"generated workbook")
    database = CacheDatabase()
    service = StorageService(settings, database)
    service._s3 = MemoryS3()

    service.schedule_artifact_mirror(
        user_id,
        {
            "params": {
                "content": [
                    {
                        "type": "text",
                        "text": f"Generated file:\n{path}.",
                    }
                ]
            }
        },
    )
    result = await service.artifact_download_url(user_id, str(path))

    assert result["filename"] == "generated report.xlsx"
    assert relative.as_posix() in database.artifacts
    assert result["url"].startswith("https://s3.example.test/")


@pytest.mark.asyncio
async def test_failed_snapshot_retains_local_tenant_cache(settings) -> None:
    user_id = uuid4()
    tenant = settings.data_root / "tenants" / str(user_id)
    state_file = tenant / "workflow" / "jobs.sqlite3"
    state_file.parent.mkdir(parents=True)
    state_file.write_bytes(b"must-survive")
    service = StorageService(settings, CacheDatabase())
    service._s3 = FailingUploadS3()

    with pytest.raises(RuntimeError, match="simulated S3 failure"):
        await service.persist_and_evict_tenant_cache(user_id)

    assert state_file.read_bytes() == b"must-survive"
    assert service._snapshot_pointer_key(user_id) not in service._s3.objects
