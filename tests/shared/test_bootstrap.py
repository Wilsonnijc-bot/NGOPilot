from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

import ngopilot_mcp.bootstrap as bootstrap_module
from ngopilot_mcp.bootstrap import (
    _seed_careflow_resources,
    _tree_digest,
    _validate_sources,
)
from ngopilot_mcp.config import Settings


def _settings(tmp_path: Path) -> Settings:
    package_root = Path(bootstrap_module.__file__).resolve().parent
    return Settings(
        state_root=tmp_path / "state",
        careflow_source=package_root / "payloads" / "careflow" / "backend",
        roster_source=package_root / "payloads" / "rostercopiilot",
        careflow_python=Path(sys.executable),
        roster_python=Path(sys.executable),
        allowed_input_roots=(),
        worker_timeout_seconds=30,
    )


def test_vendor_manifest_matches_bundled_sources_and_runtime_locks(
    tmp_path: Path,
) -> None:
    _validate_sources(_settings(tmp_path))

    manifest_path = (
        Path(bootstrap_module.__file__).resolve().parent / "vendor.lock.toml"
    )
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    assert [item["package_id"] for item in manifest["applications"]] == [
        "careflow",
        "rostercopiilot",
    ]


def test_vendor_manifest_hash_mismatch_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = bootstrap_module._VENDOR_LOCK.read_text(encoding="utf-8")
    manifest = tomllib.loads(original)
    digest = manifest["applications"][0]["runtime_lock_sha256"]
    tampered = tmp_path / "vendor.lock.toml"
    tampered.write_text(original.replace(digest, "0" * 64, 1), encoding="utf-8")
    monkeypatch.setattr(bootstrap_module, "_VENDOR_LOCK", tampered)

    with pytest.raises(RuntimeError, match="CareFlow runtime lock hash mismatch"):
        _validate_sources(_settings(tmp_path))


def test_source_tree_digest_ignores_only_generated_build_residue(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    expected = _tree_digest(source)

    generated = (
        source / "build" / "lib" / "copy.py",
        source / "example.egg-info" / "PKG-INFO",
        source / "__pycache__" / "app.cpython-311.pyc",
        source / "logs" / "vision.log",
    )
    for path in generated:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"generated")

    assert _tree_digest(source) == expected
    (source / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert _tree_digest(source) != expected


def test_careflow_resource_seed_refreshes_a_stale_managed_copy(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    target = settings.careflow_data / "form_templates" / "ccsv.json"
    target.parent.mkdir(parents=True)
    target.write_text("stale", encoding="utf-8")

    _seed_careflow_resources(settings)

    source = settings.careflow_source / "data" / "form_templates" / "ccsv.json"
    assert target.read_bytes() == source.read_bytes()
