"""FastAPI application and public cloud boundary."""

from __future__ import annotations

import hashlib
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Request,
    UploadFile,
    WebSocket,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .acp_proxy import proxy_websocket
from .auth import AuthContext, database, require_auth
from .auth import router as auth_router
from .config import Settings, get_settings
from .db import Database, apply_migrations
from .processes import TenantProcessManager, executable_available
from .storage import StorageService

logger = logging.getLogger(__name__)


class TicketResponse(BaseModel):
    url: str
    expires_at: datetime


class ArtifactUrlResponse(BaseModel):
    url: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    expires_in: int


def migration_directory() -> Path:
    return Path(__file__).resolve().parent / "migrations"


def create_app(settings_override: Settings | None = None) -> FastAPI:
    app_settings = settings_override or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app_settings.data_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        await apply_migrations(app_settings.database_url, migration_directory())
        db = Database(app_settings)
        await db.connect()
        storage = StorageService(app_settings, db)
        processes = TenantProcessManager(
            app_settings,
            restore_cache=storage.restore_tenant_cache,
            evict_cache=storage.persist_and_evict_tenant_cache,
        )
        app.state.settings = app_settings
        app.state.db = db
        app.state.processes = processes
        app.state.storage = storage
        try:
            await storage.evict_stale_tenant_caches()
            yield
        finally:
            await processes.stop_all()
            await storage.close()
            await db.close()

    app = FastAPI(
        title="NGOPilot Gateway",
        version="0.1.0",
        docs_url=None if app_settings.app_env == "production" else "/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    origins = app_settings.cors_origins
    if "*" in origins:
        raise ValueError("ALLOWED_ORIGINS cannot contain '*' when credentials are enabled")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(auth_router)

    @app.middleware("http")
    async def response_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/auth") or request.url.path == "/api/ws-tickets":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health", include_in_schema=False)
    @app.get("/healthz", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", include_in_schema=False)
    @app.get("/readyz", include_in_schema=False)
    async def readiness(request: Request):
        checks: dict[str, bool] = {
            "database": False,
            "data_root": False,
            "agent_binary": executable_available(app_settings.ngopilot_bin),
            "mcp_binary": executable_available(app_settings.ngopilot_mcp_bin),
            "shared_mcp_assets": request.app.state.processes.shared_assets_available(),
            "model_key": bool(app_settings.openrouter_api_key),
            "object_storage": app_settings.s3_configured,
        }
        try:
            checks["database"] = await request.app.state.db.ping()
        except Exception:
            checks["database"] = False
        probe = app_settings.data_root / f".ready-{uuid4()}"
        try:
            with probe.open("x", encoding="utf-8") as stream:
                stream.write("ok")
            checks["data_root"] = True
        except OSError:
            checks["data_root"] = False
        finally:
            if probe.exists():
                probe.unlink()
        ready = all(checks.values())
        payload = {
            "status": "ready" if ready else "not_ready",
            "checks": checks,
        }
        return JSONResponse(
            payload,
            status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @app.post("/api/ws-tickets", response_model=TicketResponse)
    async def create_ticket(
        auth: AuthContext = Depends(require_auth),
        db: Database = Depends(database),
    ) -> TicketResponse:
        ticket = secrets.token_urlsafe(32)
        expires_at = await db.create_ws_ticket(
            auth.user_id,
            auth.auth_session_id,
            hashlib.sha256(ticket.encode("utf-8")).digest(),
            app_settings.ws_ticket_ttl_seconds,
        )
        return TicketResponse(url=app_settings.websocket_ticket_url(ticket), expires_at=expires_at)

    @app.post("/api/uploads", status_code=status.HTTP_201_CREATED)
    async def upload(
        file: UploadFile = File(...),
        upload_id: str = Form(...),
        placeholder: str = Form(...),
        auth: AuthContext = Depends(require_auth),
    ) -> dict[str, object]:
        return await app.state.storage.store_upload(auth.user_id, upload_id, placeholder, file)

    @app.get("/api/artifacts/url", response_model=ArtifactUrlResponse)
    async def artifact_url(
        path: str,
        auth: AuthContext = Depends(require_auth),
    ) -> ArtifactUrlResponse:
        payload = await app.state.storage.artifact_download_url(auth.user_id, path)
        return ArtifactUrlResponse.model_validate(payload)

    @app.websocket("/acp")
    async def acp(websocket: WebSocket, ticket: str | None = None) -> None:
        origin = (websocket.headers.get("origin") or "").rstrip("/")
        if origin not in app_settings.cors_origins:
            await websocket.close(code=4403)
            return
        if not ticket:
            await websocket.close(code=4401)
            return
        row = await app.state.db.consume_ws_ticket(hashlib.sha256(ticket.encode("utf-8")).digest())
        if row is None:
            await websocket.close(code=4401)
            return
        try:
            user_id = UUID(str(row["user_id"]))
            await proxy_websocket(
                websocket,
                user_id,
                app_settings,
                app.state.db,
                app.state.processes,
                app.state.storage,
            )
        except Exception as error:
            logger.error("ACP connection failed: %s", type(error).__name__)
            # The process or upstream connection can fail before the socket is accepted.
            try:
                await websocket.close(code=1011)
            except RuntimeError:
                pass

    return app


app = create_app()
