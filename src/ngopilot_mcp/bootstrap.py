"""Create the two managed application environments and seed native resources."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tomllib
import venv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings

_PACKAGE_ROOT = Path(__file__).resolve().parent
_VENDOR_LOCK = _PACKAGE_ROOT / "vendor.lock.toml"


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    careflow_python: Path
    roster_python: Path
    careflow_source: Path
    roster_source: Path


def bootstrap(settings: Settings, *, upgrade: bool = False) -> BootstrapResult:
    _validate_sources(settings)
    applications = _load_vendor_applications()
    lock_root = Path(__file__).resolve().parent / "runtime_locks"
    careflow_python = _ensure_environment(
        settings.state_root / "runtimes" / "careflow" / ".venv",
        settings.careflow_source,
        lock_root / "careflow.lock",
        _application_wheel(applications["careflow"], "careflow"),
        upgrade=upgrade,
    )
    roster_python = _ensure_environment(
        settings.state_root / "runtimes" / "rostercopiilot" / ".venv",
        settings.roster_source,
        lock_root / "rostercopiilot.lock",
        _application_wheel(applications["rostercopiilot"], "rostercopiilot"),
        upgrade=upgrade,
    )
    _seed_careflow_resources(settings)
    _verify_import(careflow_python, settings.careflow_source, "careflow")
    _verify_import(roster_python, settings.roster_source, "rostercopiilot")
    return BootstrapResult(
        careflow_python=careflow_python,
        roster_python=roster_python,
        careflow_source=settings.careflow_source,
        roster_source=settings.roster_source,
    )


def _validate_sources(settings: Settings) -> None:
    applications = _load_vendor_applications()
    for package_id, application in applications.items():
        _validate_bundled_payload(application, package_id)

    runtimes = (
        (
            "careflow",
            "CareFlow",
            settings.careflow_source,
            _PACKAGE_ROOT / "runtime_locks" / "careflow.lock",
        ),
        (
            "rostercopiilot",
            "RosterCopiilot",
            settings.roster_source,
            _PACKAGE_ROOT / "runtime_locks" / "rostercopiilot.lock",
        ),
    )

    for package_id, label, source, lock_path in runtimes:
        application = applications.get(package_id)
        if application is None:
            raise RuntimeError(f"Vendor manifest has no {package_id!r} application")

        project_file = source / "pyproject.toml"
        if not project_file.is_file():
            raise FileNotFoundError(f"{label} project not found: {project_file}")
        expected = _manifest_string(application, "version", package_id)
        actual = tomllib.loads(project_file.read_text(encoding="utf-8"))["project"][
            "version"
        ]
        if actual != expected:
            raise RuntimeError(
                f"{label} payload version mismatch: expected {expected}, found {actual}"
            )

        if not lock_path.is_file():
            raise FileNotFoundError(f"Managed runtime lock not found: {lock_path}")
        expected_lock_digest = _manifest_string(
            application, "runtime_lock_sha256", package_id
        )
        actual_lock_digest = _file_digest(lock_path)
        if actual_lock_digest != expected_lock_digest:
            raise RuntimeError(
                f"{label} runtime lock hash mismatch: expected "
                f"{expected_lock_digest}, found {actual_lock_digest}"
            )

        expected_tree_digest = _manifest_string(
            application, "install_tree_sha256", package_id
        )
        actual_tree_digest = _tree_digest(source)
        if actual_tree_digest != expected_tree_digest:
            raise RuntimeError(
                f"{label} source tree hash mismatch: expected "
                f"{expected_tree_digest}, found {actual_tree_digest}"
            )

        _validate_required_resources(application, package_id, label, source)
        _application_wheel(application, package_id)


def _load_vendor_applications() -> dict[str, dict[str, Any]]:
    if not _VENDOR_LOCK.is_file():
        raise FileNotFoundError(f"Vendor manifest not found: {_VENDOR_LOCK}")
    manifest = tomllib.loads(_VENDOR_LOCK.read_text(encoding="utf-8"))
    raw_applications = manifest.get("applications")
    if not isinstance(raw_applications, list):
        raise RuntimeError("Vendor manifest applications must be an array")

    applications: dict[str, dict[str, Any]] = {}
    for item in raw_applications:
        if not isinstance(item, dict):
            raise RuntimeError("Vendor manifest application must be a table")
        package_id = item.get("package_id")
        if not isinstance(package_id, str) or not package_id:
            raise RuntimeError("Vendor manifest application has no package_id")
        if package_id in applications:
            raise RuntimeError(f"Duplicate vendor manifest package_id: {package_id}")
        applications[package_id] = item
    return applications


def _manifest_string(application: dict[str, Any], key: str, package_id: str) -> str:
    value = application.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"Vendor manifest {package_id}.{key} must be a string")
    return value


def _validate_bundled_payload(application: dict[str, Any], package_id: str) -> None:
    relative_value = _manifest_string(application, "payload_path", package_id)
    relative = Path(relative_value)
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError(
            f"Vendor manifest {package_id} has unsafe payload path: {relative_value}"
        )
    payload = (_PACKAGE_ROOT / relative).resolve()
    if not payload.is_relative_to(_PACKAGE_ROOT) or not payload.is_dir():
        raise FileNotFoundError(f"Bundled application payload not found: {payload}")

    expected_digest = _manifest_string(application, "payload_tree_sha256", package_id)
    actual_digest = _tree_digest(payload)
    if actual_digest != expected_digest:
        raise RuntimeError(
            f"Bundled {package_id} payload hash mismatch: expected "
            f"{expected_digest}, found {actual_digest}"
        )

    expected_count = application.get("payload_file_count")
    if not isinstance(expected_count, int) or expected_count < 1:
        raise RuntimeError(
            f"Vendor manifest {package_id}.payload_file_count must be a positive integer"
        )
    actual_count = len(_tree_files(payload))
    if actual_count != expected_count:
        raise RuntimeError(
            f"Bundled {package_id} payload file-count mismatch: expected "
            f"{expected_count}, found {actual_count}"
        )


def _application_wheel(application: dict[str, Any], package_id: str) -> Path:
    relative_value = _manifest_string(application, "application_wheel_path", package_id)
    relative = Path(relative_value)
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError(
            f"Vendor manifest {package_id} has unsafe wheel path: {relative_value}"
        )
    wheel = (_PACKAGE_ROOT / relative).resolve()
    if not wheel.is_relative_to(_PACKAGE_ROOT) or not wheel.is_file():
        raise FileNotFoundError(f"Bundled application wheel not found: {wheel}")
    expected_digest = _manifest_string(
        application, "application_wheel_sha256", package_id
    )
    actual_digest = _file_digest(wheel)
    if actual_digest != expected_digest:
        raise RuntimeError(
            f"Bundled {package_id} wheel hash mismatch: expected "
            f"{expected_digest}, found {actual_digest}"
        )
    return wheel


def _validate_required_resources(
    application: dict[str, Any], package_id: str, label: str, source: Path
) -> None:
    resources = application.get("required_resources")
    if not isinstance(resources, list) or not resources:
        raise RuntimeError(
            f"Vendor manifest {package_id}.required_resources must be a nonempty array"
        )
    source_root = source.resolve()
    for resource in resources:
        if not isinstance(resource, dict):
            raise RuntimeError(f"Vendor manifest {package_id} resource must be a table")
        relative_value = _manifest_string(resource, "path", package_id)
        relative = Path(relative_value)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(
                f"Vendor manifest {package_id} has unsafe resource path: "
                f"{relative_value}"
            )
        path = (source_root / relative).resolve()
        if not path.is_relative_to(source_root) or not path.is_file():
            raise FileNotFoundError(f"Bundled {label} resource not found: {path}")
        expected_digest = _manifest_string(resource, "sha256", package_id)
        actual_digest = _file_digest(path)
        if actual_digest != expected_digest:
            raise RuntimeError(
                f"{label} resource hash mismatch for {relative_value}: expected "
                f"{expected_digest}, found {actual_digest}"
            )


def _ensure_environment(
    environment: Path,
    project: Path,
    requirements_lock: Path,
    application_wheel: Path,
    *,
    upgrade: bool,
) -> Path:
    executable = (
        environment / "Scripts" / "python.exe"
        if sys.platform == "win32"
        else environment / "bin" / "python"
    )
    marker = environment / ".ngopilot-source"
    expected_marker = "\n".join(
        (
            str(project.resolve()),
            _tree_digest(project),
            _file_digest(requirements_lock),
            _file_digest(application_wheel),
        )
    )
    is_current = (
        not upgrade
        and executable.exists()
        and _has_pip(executable)
        and marker.exists()
        and marker.read_text(encoding="utf-8") == expected_marker
    )
    if is_current:
        return executable.absolute()

    environment.parent.mkdir(parents=True, exist_ok=True)
    venv.EnvBuilder(
        with_pip=True,
        clear=environment.exists(),
        symlinks=os.name != "nt",
    ).create(environment)
    subprocess.run(
        [
            str(executable),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--require-hashes",
            "--requirement",
            str(requirements_lock),
        ],
        check=True,
    )
    subprocess.run(
        [
            str(executable),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-index",
            "--no-deps",
            "--force-reinstall",
            str(application_wheel),
        ],
        check=True,
    )
    marker.write_text(expected_marker, encoding="utf-8")
    return executable.absolute()


def _has_pip(executable: Path) -> bool:
    if not executable.exists():
        return False
    completed = subprocess.run(
        [str(executable), "-m", "pip", "--version"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return completed.returncode == 0


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in _tree_files(root):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()


def _tree_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and not _is_generated_source_path(path.relative_to(root))
        and path.suffix.lower() not in {".pyc", ".pyo"}
    )


def _is_generated_source_path(relative: Path) -> bool:
    return (bool(relative.parts) and relative.parts[0] == "logs") or any(
        part in {"__pycache__", "build"} or part.endswith(".egg-info")
        for part in relative.parts
    )


def _seed_careflow_resources(settings: Settings) -> None:
    source_data = settings.careflow_source / "data"
    for directory_name in ("form_templates", "templates"):
        source = source_data / directory_name
        destination = settings.careflow_data / directory_name
        destination.mkdir(parents=True, exist_ok=True)
        if not source.exists():
            continue
        for item in source.iterdir():
            if not item.is_file():
                continue
            target = destination / item.name
            if not target.exists() or _file_digest(target) != _file_digest(item):
                shutil.copy2(item, target)


def _verify_import(python: Path, source: Path, runtime: str) -> None:
    import_root = source if runtime == "careflow" else source / "backend"
    completed = subprocess.run(
        [
            str(python),
            "-c",
            (
                "import sys; "
                f"sys.path.insert(0, {str(import_root)!r}); "
                "import app; "
                "print(app.__file__)"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    resolved = Path(completed.stdout.strip()).resolve()
    if not resolved.is_relative_to(import_root.resolve()):
        raise RuntimeError(
            f"{runtime} worker imported app from the wrong root: {resolved}"
        )
