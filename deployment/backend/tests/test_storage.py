from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from ngopilot_gateway.storage import (
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

    resolved = await service.resolve_payload(user_id, {"prompt": f"Review {placeholder}"})

    assert resolved == {"prompt": f"Review {path.resolve()}"}


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
