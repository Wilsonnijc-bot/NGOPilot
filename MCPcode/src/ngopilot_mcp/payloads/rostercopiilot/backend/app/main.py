"""FastAPI entrypoint for the RosterCopiilot scheduler-first MVP."""
from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import changes, dataset, demo, export, imports, master_data, schedule

logger = logging.getLogger("rostercopiilot")

# Development origins used when ROSTER_CORS_ORIGINS is not configured. A
# same-origin deployment (frontend and API behind one reverse proxy) needs no
# cross-origin entries and should set ROSTER_CORS_ORIGINS="".
DEFAULT_DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]

# Requests that must stay reachable without the optional API token so that a
# reverse proxy / uptime monitor can poll liveness.
PUBLIC_PATHS = frozenset({"/api/health"})


def _cors_origins() -> list[str]:
    """Resolve allowed CORS origins from the environment.

    Unset  -> development origins (localhost dev servers).
    Set     -> comma-separated allowlist; an empty value means "same-origin
    only" and disables cross-origin access entirely.
    """

    raw = os.getenv("ROSTER_CORS_ORIGINS")
    if raw is None:
        return DEFAULT_DEV_ORIGINS
    return [item.strip() for item in raw.split(",") if item.strip()]


def _docs_enabled() -> bool:
    """Interactive API docs are on for development, off for hardened deploys.

    ROSTER_ENABLE_DOCS wins when set (1/true/yes/on). Otherwise docs are
    disabled only when ROSTER_ENV=production.
    """

    flag = os.getenv("ROSTER_ENABLE_DOCS")
    if flag is not None:
        return flag.strip().lower() in {"1", "true", "yes", "on"}
    return os.getenv("ROSTER_ENV", "development").strip().lower() != "production"


def _extract_bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if header and header.lower().startswith("bearer "):
        return header[7:].strip()
    api_key = request.headers.get("x-api-key")
    return api_key.strip() if api_key else None


_DOCS_ON = _docs_enabled()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    if not os.getenv("ROSTER_API_TOKEN"):
        logger.warning(
            "ROSTER_API_TOKEN is not set: the API has no application-level "
            "authentication. Ensure a reverse-proxy access gate is active "
            "before exposing this service beyond localhost."
        )
    if _DOCS_ON and os.getenv("ROSTER_ENV", "development").strip().lower() == "production":
        logger.warning(
            "Interactive API docs are enabled in a production environment."
        )
    yield


app = FastAPI(
    title="RosterCopiilot API",
    description=(
        "NGO weekly roster scheduling backend: deterministic greedy scheduler, "
        "change-event repair, impact analysis, human review queue, persistent "
        "state, weekly demo build flow, and Excel export."
    ),
    version="0.6.0",
    docs_url="/docs" if _DOCS_ON else None,
    redoc_url="/redoc" if _DOCS_ON else None,
    openapi_url="/openapi.json" if _DOCS_ON else None,
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _api_token_gate(request: Request, call_next):
    """Optional shared-secret gate for direct API access.

    Off by default: when ROSTER_API_TOKEN is unset the API behaves exactly as
    before (the browser demo is gated at the reverse proxy instead). When the
    variable is set, every non-public, non-preflight request must present the
    token via ``Authorization: Bearer <token>`` or ``X-API-Key``.
    """

    token = os.getenv("ROSTER_API_TOKEN")
    if token and request.method != "OPTIONS" and request.url.path not in PUBLIC_PATHS:
        provided = _extract_bearer_token(request)
        if provided is None or not secrets.compare_digest(
            provided.encode("utf-8"), token.encode("utf-8")
        ):
            return JSONResponse(
                status_code=401,
                content={
                    "detail": {
                        "code": "UNAUTHORIZED",
                        "message": "缺少或無效的存取權杖。",
                    }
                },
                headers={"WWW-Authenticate": "Bearer"},
            )
    return await call_next(request)


app.include_router(schedule.router)
app.include_router(changes.router)
app.include_router(dataset.router)
app.include_router(imports.router)
app.include_router(export.router)
app.include_router(demo.router)
app.include_router(master_data.router)


@app.get("/api/health")
def health() -> dict:
    from .services.state import get_state

    state = get_state()
    return {
        "status": "ok",
        "mode": "scheduler-first-demo",
        "service": "RosterCopiilot",
        "seed": state.seed,
        "current_version": state.current_id,
        "engine": "greedy-v1 (deterministic; CP-SAT adapter slot: app.engine)",
    }
