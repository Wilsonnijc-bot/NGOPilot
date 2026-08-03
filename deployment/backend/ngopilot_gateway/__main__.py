"""Production entry point."""

from __future__ import annotations

import uvicorn

from .config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "ngopilot_gateway.main:app",
        host="0.0.0.0",
        port=settings.port,
        access_log=False,
        proxy_headers=True,
        forwarded_allow_ips="*",
        ws_max_size=64 * 1024 * 1024,
    )


if __name__ == "__main__":
    main()
