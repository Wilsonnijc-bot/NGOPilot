"""Password and opaque bearer-token authentication."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field, field_validator

from .config import Settings
from .db import Database

password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
bearer = HTTPBearer(auto_error=False)


def normalize_email(value: str) -> str:
    return value.strip().lower()


def token_digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(password_hasher.hash, password)


async def verify_password(password_hash: str, password: str) -> bool:
    try:
        return await asyncio.to_thread(password_hasher.verify, password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=1024)


class Registration(Credentials):
    name: str | None = Field(default=None, max_length=120)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class UserResponse(BaseModel):
    id: UUID
    email: str
    name: str | None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserResponse


@dataclass(frozen=True, slots=True)
class AuthContext:
    user_id: UUID
    auth_session_id: UUID
    email: str
    display_name: str | None
    created_at: datetime
    expires_at: datetime

    @classmethod
    def from_record(cls, row: asyncpg.Record) -> "AuthContext":
        return cls(
            user_id=row["user_id"],
            auth_session_id=row["auth_session_id"],
            email=row["email_normalized"],
            display_name=row["display_name"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
        )

    def user_response(self) -> UserResponse:
        return UserResponse(
            id=self.user_id,
            email=self.email,
            name=self.display_name,
            created_at=self.created_at,
        )


def database(request: Request) -> Database:
    return request.app.state.db


def settings(request: Request) -> Settings:
    return request.app.state.settings


async def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Database = Depends(database),
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    row = await db.auth_context(token_digest(credentials.credentials))
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    return AuthContext.from_record(row)


async def issue_token(
    db: Database,
    app_settings: Settings,
    user: asyncpg.Record,
) -> TokenResponse:
    token = secrets.token_urlsafe(32)
    auth_session = await db.create_auth_session(
        user["id"], token_digest(token), app_settings.auth_token_ttl_hours
    )
    return TokenResponse(
        access_token=token,
        expires_at=auth_session["expires_at"],
        user=UserResponse(
            id=user["id"],
            email=user["email_normalized"],
            name=user["display_name"],
            created_at=user["created_at"],
        ),
    )


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: Registration,
    db: Database = Depends(database),
    app_settings: Settings = Depends(settings),
) -> TokenResponse:
    if not app_settings.registration_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Registration is closed")
    email = normalize_email(str(payload.email))
    password_hash = await hash_password(payload.password)
    try:
        user = await db.create_user(email, password_hash, payload.name)
    except asyncpg.UniqueViolationError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Account already exists"
        ) from error
    return await issue_token(db, app_settings, user)


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: Credentials,
    db: Database = Depends(database),
    app_settings: Settings = Depends(settings),
) -> TokenResponse:
    email = normalize_email(str(payload.email))
    user = await db.user_for_login(email)
    valid = user is not None and await verify_password(user["password_hash"], payload.password)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )
    return await issue_token(db, app_settings, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    auth: AuthContext = Depends(require_auth),
    db: Database = Depends(database),
) -> None:
    await db.revoke_auth_session(auth.auth_session_id)


@router.get("/me", response_model=UserResponse)
async def me(auth: AuthContext = Depends(require_auth)) -> UserResponse:
    return auth.user_response()
