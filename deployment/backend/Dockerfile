# syntax=docker/dockerfile:1.7

FROM rust:1.96.1-bookworm AS agent-builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        clang \
        cmake \
        libclang-dev \
        libdbus-1-dev \
        libssl-dev \
        libxcb1-dev \
        perl \
        pkg-config \
        protobuf-compiler \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build/harness
COPY ["harness bone/", "/build/harness/"]

ENV CARGO_REGISTRIES_CRATES_IO_PROTOCOL=sparse
RUN --mount=type=cache,id=s/8959f8df-dec1-4921-85af-599a6deb4a6a-/usr/local/cargo/registry,target=/usr/local/cargo/registry \
    --mount=type=cache,id=s/8959f8df-dec1-4921-85af-599a6deb4a6a-/usr/local/cargo/git,target=/usr/local/cargo/git \
    --mount=type=cache,id=s/8959f8df-dec1-4921-85af-599a6deb4a6a-/build/harness/target,target=/build/harness/target \
    cargo build --locked --release --package goose-cli --bin ngopilot \
        --no-default-features --features rustls-tls \
    && cp target/release/ngopilot /tmp/ngopilot


FROM python:3.12-slim-bookworm AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        gosu \
        libdbus-1-3 \
        libgomp1 \
        libssl3 \
        libxcb1 \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin ngopilot

COPY --from=agent-builder /tmp/ngopilot /usr/local/bin/ngopilot
COPY MCPcode/ /build/MCPcode/

RUN python -m pip install --no-cache-dir --disable-pip-version-check /build/MCPcode \
    && NGOPILOT_MCP_STATE_DIR=/opt/ngopilot/shared ngopilot-mcp bootstrap \
    && test -x /opt/ngopilot/shared/runtimes/careflow/.venv/bin/python \
    && test -x /opt/ngopilot/shared/runtimes/rostercopiilot/.venv/bin/python \
    && chown -R root:ngopilot /opt/ngopilot/shared \
    && chmod -R g+rX /opt/ngopilot/shared \
    && gosu ngopilot test -x /opt/ngopilot/shared/runtimes/careflow/.venv/bin/python \
    && gosu ngopilot test -x /opt/ngopilot/shared/runtimes/rostercopiilot/.venv/bin/python \
    && rm -rf /build/MCPcode /root/.cache

COPY deployment/backend/ /build/gateway/

RUN --mount=type=cache,id=s/8959f8df-dec1-4921-85af-599a6deb4a6a-/root/.cache/pip,target=/root/.cache/pip \
    python -m pip install --disable-pip-version-check /build/gateway \
    && python -c "from importlib.resources import files; assert files('ngopilot_gateway').joinpath('migrations/001_initial.sql').is_file()" \
    && rm -rf /build/gateway

COPY --chmod=755 deployment/backend/entrypoint.sh /usr/local/bin/ngopilot-entrypoint

ENV APP_ENV=production \
    DATA_ROOT=/data \
    HOME=/home/ngopilot \
    MALLOC_ARENA_MAX=2 \
    MALLOC_MMAP_THRESHOLD_=131072 \
    MALLOC_TRIM_THRESHOLD_=65536 \
    NGOPILOT_MCP_SHARED_STATE_DIR=/opt/ngopilot/shared \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /home/ngopilot
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8080')+'/readyz', timeout=4)" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/ngopilot-entrypoint"]
CMD ["python", "-m", "ngopilot_gateway"]
