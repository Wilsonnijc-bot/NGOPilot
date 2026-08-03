from __future__ import annotations

from pathlib import Path

import pytest

from ngopilot_gateway.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        data_root=tmp_path / "data",
        public_api_url="http://127.0.0.1:8080",
        allowed_origins="http://127.0.0.1:4173",
        database_url="postgresql://unused",
        openrouter_api_key="test-model-key",
        ngopilot_mcp_shared_state_dir=tmp_path / "shared",
    )
