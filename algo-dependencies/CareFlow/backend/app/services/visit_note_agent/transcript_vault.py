"""Encrypted transcript vault.

Family-of-the-elderly recordings can carry sensitive personal data.
Per partner branch's privacy rule the transcript must not be plaintext
on disk. We compromise between "complete burn" and "still reviewable":

- Transcripts live encrypted with Fernet (AES-128-CBC + HMAC-SHA256)
  inside `data/transcripts/`.
- The key lives in `data/.transcript_key` (auto-generated on first
  call, 0600). It NEVER leaves the server.
- `burn(session_id)` overwrites the file with random bytes and
  deletes — no recovery.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet

from ...config import settings


def _vault_dir() -> Path:
    d = settings.data_path / "transcripts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _key_path() -> Path:
    return settings.data_path / ".transcript_key"


def _load_or_create_key() -> bytes:
    p = _key_path()
    if p.exists():
        return p.read_bytes().strip()
    key = Fernet.generate_key()
    p.write_bytes(key)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return key


def write(session_id: int, transcript: str) -> str:
    """Encrypt + persist; returns relative path under data/."""
    fernet = Fernet(_load_or_create_key())
    blob = fernet.encrypt(transcript.encode("utf-8"))
    target = _vault_dir() / f"session_{session_id}.enc"
    target.write_bytes(blob)
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return str(target.relative_to(settings.data_path))


def read(rel_path: str) -> str:
    fernet = Fernet(_load_or_create_key())
    full = settings.data_path / rel_path
    if not full.exists():
        raise FileNotFoundError(f"Transcript vault file missing: {rel_path}")
    return fernet.decrypt(full.read_bytes()).decode("utf-8")


def burn(rel_path: str) -> bool:
    """Overwrite the file with random bytes then unlink. Idempotent."""
    full = settings.data_path / rel_path
    if not full.exists():
        return False
    try:
        size = full.stat().st_size
        with full.open("r+b") as f:
            f.write(secrets.token_bytes(max(size, 1024)))
            f.flush()
            os.fsync(f.fileno())
        full.unlink()
        return True
    except OSError:
        return False
