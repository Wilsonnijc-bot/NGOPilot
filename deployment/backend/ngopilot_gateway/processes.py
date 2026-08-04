"""Lifecycle management for one isolated ACP process per user."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import shutil
import socket
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Awaitable, Callable
from uuid import UUID

import httpx

from .config import Settings

logger = logging.getLogger(__name__)

RUNTIME_NAMES = ("careflow", "rostercopiilot")
DISABLED_CLOUD_EXTENSIONS = (
    "analyze",
    "apps",
    "developer",
    "extensionmanager",
    "skills",
    "summon",
    "todo",
    "tom",
)


def executable_available(command: str) -> bool:
    if os.path.sep in command:
        path = Path(command)
        return path.is_file() and os.access(path, os.X_OK)
    return shutil.which(command) is not None


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as stream:
        stream.bind(("127.0.0.1", 0))
        return int(stream.getsockname()[1])


def _redact(value: str, *secrets_to_hide: str) -> str:
    redacted = value
    for secret_value in secrets_to_hide:
        if secret_value:
            redacted = redacted.replace(secret_value, "[REDACTED]")
    return redacted


@dataclass(slots=True)
class ManagedProcess:
    user_id: UUID
    process: asyncio.subprocess.Process
    port: int
    secret: str
    tenant_root: Path
    refs: int = 0
    idle_task: asyncio.Task[None] | None = None
    stderr_task: asyncio.Task[None] | None = None

    @property
    def websocket_url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/acp"

    @property
    def alive(self) -> bool:
        return self.process.returncode is None


class TenantProcessManager:
    def __init__(
        self,
        settings: Settings,
        *,
        restore_cache: Callable[[UUID], Awaitable[None]] | None = None,
        evict_cache: Callable[[UUID], Awaitable[None]] | None = None,
    ):
        self.settings = settings
        self._restore_cache = restore_cache
        self._evict_cache = evict_cache
        self._processes: dict[UUID, ManagedProcess] = {}
        self._locks: dict[UUID, asyncio.Lock] = {}

    def tenant_root(self, user_id: UUID) -> Path:
        return self.settings.data_root / "tenants" / str(user_id)

    def _lock(self, user_id: UUID) -> asyncio.Lock:
        lock = self._locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[user_id] = lock
        return lock

    async def acquire(self, user_id: UUID) -> ManagedProcess:
        async with self._lock(user_id):
            managed = self._processes.get(user_id)
            if managed is not None and managed.alive:
                if managed.idle_task is not None:
                    managed.idle_task.cancel()
                    managed.idle_task = None
                managed.refs += 1
                return managed

            if managed is not None:
                await self._stop(managed)
            managed = await self._start(user_id)
            managed.refs = 1
            self._processes[user_id] = managed
            return managed

    async def release(self, user_id: UUID) -> None:
        async with self._lock(user_id):
            managed = self._processes.get(user_id)
            if managed is None:
                return
            managed.refs = max(0, managed.refs - 1)
            if managed.refs != 0 or managed.idle_task is not None:
                return
            if self.settings.ngopilot_process_idle_seconds == 0:
                await self._stop(managed)
                self._processes.pop(user_id, None)
                return
            managed.idle_task = asyncio.create_task(
                self._stop_after_idle(user_id, managed),
                name=f"ngopilot-idle-{user_id}",
            )

    async def _stop_after_idle(self, user_id: UUID, expected: ManagedProcess) -> None:
        try:
            await asyncio.sleep(self.settings.ngopilot_process_idle_seconds)
            async with self._lock(user_id):
                current = self._processes.get(user_id)
                if current is expected and current.refs == 0:
                    current.idle_task = None
                    await self._stop(current)
                    self._processes.pop(user_id, None)
        except asyncio.CancelledError:
            return

    async def stop_all(self) -> None:
        processes = list(self._processes.values())
        self._processes.clear()
        for managed in processes:
            if managed.idle_task is not None:
                managed.idle_task.cancel()
                managed.idle_task = None
        await asyncio.gather(*(self._stop(item) for item in processes), return_exceptions=True)

    def live_count(self) -> int:
        return sum(1 for item in self._processes.values() if item.alive)

    def shared_assets_available(self) -> bool:
        shared = self.settings.ngopilot_mcp_shared_state_dir
        runtimes_ready = all(
            (shared / "runtimes" / name / ".venv" / "bin" / "python").is_file()
            for name in RUNTIME_NAMES
        )
        resources_ready = all(
            (shared / "app-data" / "careflow" / name).is_dir()
            for name in ("form_templates", "templates")
        )
        return runtimes_ready and resources_ready

    async def _start(self, user_id: UUID) -> ManagedProcess:
        if self._restore_cache is not None:
            await self._restore_cache(user_id)
        tenant_root = self.tenant_root(user_id)
        env = self._prepare_tenant(tenant_root)
        port = _free_loopback_port()
        secret = secrets.token_urlsafe(32)
        env["NGOPILOT_SERVER__SECRET_KEY"] = secret

        process = await asyncio.create_subprocess_exec(
            self.settings.ngopilot_bin,
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--platform",
            "desktop",
            "--with-builtin",
            "memory",
            cwd=tenant_root,
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        managed = ManagedProcess(
            user_id=user_id,
            process=process,
            port=port,
            secret=secret,
            tenant_root=tenant_root,
        )
        managed.stderr_task = asyncio.create_task(
            self._drain_stderr(managed), name=f"ngopilot-stderr-{user_id}"
        )
        try:
            await self._wait_until_ready(managed)
        except Exception:
            await self._stop(managed)
            raise
        logger.info("Started tenant ACP process for user %s", user_id)
        return managed

    def _prepare_tenant(self, tenant_root: Path) -> dict[str, str]:
        goose_root = tenant_root / "goose"
        workflow_root = tenant_root / "workflow"
        uploads_root = tenant_root / "uploads"
        temp_root = tenant_root / "tmp"
        for directory in (
            tenant_root,
            goose_root / "config",
            goose_root / "data",
            goose_root / "state",
            workflow_root,
            uploads_root,
            temp_root,
        ):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            directory.chmod(0o700)

        self._prepare_tenant_assets(workflow_root)
        config = {
            "GOOSE_PROVIDER": self.settings.goose_provider,
            "GOOSE_MODEL": self.settings.goose_model,
            "GOOSE_MODE": "auto",
            "GOOSE_DISABLE_KEYRING": True,
            "extensions": {
                **{name: {"enabled": False} for name in DISABLED_CLOUD_EXTENSIONS},
                "ngopilot": {
                    "enabled": True,
                    "type": "stdio",
                    "name": "NGOPilot",
                    "description": "CareFlow and roster workflows for NGO operations.",
                    "cmd": self.settings.ngopilot_mcp_bin,
                    "args": ["serve", "--transport", "stdio"],
                    "envs": {},
                    "env_keys": [],
                    "timeout": 2100,
                    "bundled": True,
                    "available_tools": [],
                },
            },
        }
        config_path = goose_root / "config" / "config.yaml"
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        config_path.chmod(0o600)

        env = os.environ.copy()
        env.update(
            {
                "GOOSE_PATH_ROOT": str(goose_root),
                "GOOSE_PROVIDER": self.settings.goose_provider,
                "GOOSE_MODEL": self.settings.goose_model,
                "GOOSE_DISABLE_KEYRING": "true",
                "OPENROUTER_API_KEY": self.settings.openrouter_api_key,
                "NGOPILOT_MCP_STATE_DIR": str(workflow_root),
                "NGOPILOT_MCP_ALLOWED_INPUT_ROOTS": str(uploads_root),
                "TMPDIR": str(temp_root),
                "GOOSE_DISABLE_NOSTR_SHARING": "true",
            }
        )
        env.setdefault("RUST_LOG", "warn")
        return env

    def _prepare_tenant_assets(self, workflow_root: Path) -> None:
        shared = self.settings.ngopilot_mcp_shared_state_dir
        for name in RUNTIME_NAMES:
            source = shared / "runtimes" / name / ".venv"
            destination = workflow_root / "runtimes" / name / ".venv"
            python = source / "bin" / "python"
            if not source.is_dir() or not python.is_file() or not os.access(python, os.X_OK):
                raise RuntimeError(f"Shared MCP runtime is unavailable: {name}")
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if destination.is_symlink():
                if destination.resolve() != source.resolve():
                    raise RuntimeError(
                        f"Tenant runtime link points to an unexpected target: {name}"
                    )
                continue
            if destination.exists():
                continue
            destination.symlink_to(source, target_is_directory=True)

        shared_resources = shared / "resources"
        tenant_resources = workflow_root / "resources"
        if shared_resources.is_dir() and not tenant_resources.exists():
            tenant_resources.symlink_to(shared_resources, target_is_directory=True)

        shared_careflow = shared / "app-data" / "careflow"
        tenant_careflow = workflow_root / "app-data" / "careflow"
        for name in ("form_templates", "templates"):
            source = shared_careflow / name
            destination = tenant_careflow / name
            if not source.is_dir():
                raise RuntimeError(f"Shared CareFlow resources are unavailable: {name}")
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copytree(source, destination)

    async def _wait_until_ready(self, managed: ManagedProcess) -> None:
        deadline = monotonic() + self.settings.ngopilot_process_startup_seconds
        url = f"http://127.0.0.1:{managed.port}/health"
        async with httpx.AsyncClient(timeout=1) as client:
            while monotonic() < deadline:
                if not managed.alive:
                    raise RuntimeError(
                        f"Tenant ACP process exited with status {managed.process.returncode}"
                    )
                try:
                    response = await client.get(url)
                    if response.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.15)
        raise RuntimeError("Tenant ACP process did not become ready")

    async def _drain_stderr(self, managed: ManagedProcess) -> None:
        if managed.process.stderr is None:
            return
        try:
            while line := await managed.process.stderr.readline():
                logger.info(
                    "tenant-agent[%s]: %s",
                    managed.user_id,
                    _redact(
                        line.decode("utf-8", errors="replace").rstrip()[:2000],
                        managed.secret,
                        self.settings.openrouter_api_key,
                    ),
                )
        except asyncio.CancelledError:
            return

    async def _stop(self, managed: ManagedProcess) -> None:
        if managed.idle_task is not None and managed.idle_task is not asyncio.current_task():
            managed.idle_task.cancel()
            managed.idle_task = None
        if managed.alive:
            managed.process.terminate()
            try:
                await asyncio.wait_for(managed.process.wait(), timeout=10)
            except TimeoutError:
                managed.process.kill()
                await managed.process.wait()
        if managed.stderr_task is not None:
            managed.stderr_task.cancel()
            await asyncio.gather(managed.stderr_task, return_exceptions=True)
            managed.stderr_task = None
        logger.info("Stopped tenant ACP process for user %s", managed.user_id)
        if self._evict_cache is not None:
            try:
                await self._evict_cache(managed.user_id)
            except Exception:
                # A failed snapshot must retain the local cache for a later retry.
                logger.exception("Failed to persist tenant cache for user %s", managed.user_id)
