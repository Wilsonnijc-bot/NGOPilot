"""Domain-neutral structural file validation."""

from __future__ import annotations

import zipfile
from pathlib import Path

from ..errors import ToolError


def validate_content(path: Path, content_kind: str | None) -> None:
    if content_kind is None:
        return
    if content_kind == "image":
        _validate_image(path)
    elif content_kind == "office_zip":
        _validate_office_zip(path)
    elif content_kind == "audio":
        _validate_audio(path)
    elif content_kind == "pdf":
        _validate_pdf(path)
    else:
        raise ValueError(f"Unknown content validation kind: {content_kind}")


def _invalid(path: Path, kind: str) -> ToolError:
    return ToolError(
        "FILE_CONTENT_MISMATCH",
        f"The file '{path.name}' is not a valid {kind} file.",
        details={"path": str(path), "expected_kind": kind},
    )


def _validate_image(path: Path) -> None:
    header = path.read_bytes()[:32]
    suffix = path.suffix.lower()
    valid = False
    if suffix in {".jpg", ".jpeg"}:
        valid = header.startswith(b"\xff\xd8\xff")
    elif suffix == ".png":
        valid = header.startswith(b"\x89PNG\r\n\x1a\n")
    elif suffix in {".heic", ".heif"}:
        valid = len(header) >= 12 and header[4:8] == b"ftyp"
    if not valid:
        raise _invalid(path, "image")


def _validate_office_zip(path: Path) -> None:
    if not zipfile.is_zipfile(path):
        raise _invalid(path, "Office Open XML")
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if "[Content_Types].xml" not in names:
                raise _invalid(path, "Office Open XML")
            total_size = 0
            for info in archive.infolist():
                total_size += info.file_size
                if info.file_size > 256 * 1024 * 1024:
                    raise ToolError(
                        "UNSAFE_ARCHIVE",
                        "An archive member exceeds the uncompressed size limit.",
                    )
                if info.compress_size and info.file_size / info.compress_size > 200:
                    raise ToolError(
                        "UNSAFE_ARCHIVE",
                        "The archive compression ratio exceeds the safety limit.",
                    )
            if total_size > 512 * 1024 * 1024 or len(names) > 20_000:
                raise ToolError(
                    "UNSAFE_ARCHIVE",
                    "The uncompressed archive exceeds the safety limit.",
                )
    except zipfile.BadZipFile as exc:
        raise _invalid(path, "Office Open XML") from exc


def _validate_audio(path: Path) -> None:
    header = path.read_bytes()[:32]
    suffix = path.suffix.lower()
    valid = {
        ".wav": header.startswith(b"RIFF") and header[8:12] == b"WAVE",
        ".flac": header.startswith(b"fLaC"),
        ".ogg": header.startswith(b"OggS"),
        ".mp3": header.startswith(b"ID3")
        or (len(header) > 1 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0),
        ".m4a": len(header) >= 12 and header[4:8] == b"ftyp",
        ".aac": len(header) > 1 and header[0] == 0xFF and header[1] & 0xF6 == 0xF0,
    }.get(suffix, False)
    if not valid:
        raise _invalid(path, "audio")


def _validate_pdf(path: Path) -> None:
    with path.open("rb") as stream:
        if not stream.read(5).startswith(b"%PDF-"):
            raise _invalid(path, "PDF")
