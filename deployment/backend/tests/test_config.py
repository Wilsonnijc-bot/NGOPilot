from __future__ import annotations

import pytest
from pydantic import ValidationError

from ngopilot_gateway.config import Settings


def test_websocket_ticket_url_uses_secure_scheme() -> None:
    settings = Settings(
        app_env="test",
        public_api_url="https://api.example.test/base",
        allowed_origins="https://app.example.test",
    )

    assert settings.websocket_ticket_url("ticket-value") == (
        "wss://api.example.test/base/acp?ticket=ticket-value"
    )


def test_production_requires_cloud_secrets() -> None:
    with pytest.raises(ValidationError, match="missing production settings"):
        Settings(
            app_env="production",
            public_api_url="https://api.example.test",
            allowed_origins="https://app.example.test",
        )


@pytest.mark.parametrize(
    "origin",
    ["*", "https://app.example.test/path", "https://app.example.test?query=1"],
)
def test_cors_requires_exact_origins(origin: str) -> None:
    with pytest.raises(ValidationError, match="ALLOWED_ORIGINS"):
        Settings(
            app_env="test",
            public_api_url="https://api.example.test",
            allowed_origins=origin,
        )
