FROM python:3.11-slim

ARG CAREFLOW_VERSION=0.4.8

LABEL org.opencontainers.image.title="CareFlow Backend" \
      org.opencontainers.image.version="${CAREFLOW_VERSION}" \
      org.opencontainers.image.description="CareFlow FastAPI backend"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CAREFLOW_VERSION="${CAREFLOW_VERSION}"

WORKDIR /app

# 系統依賴：PIL 字型 + 編譯 wheel
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-noto-cjk \
        libfreetype6-dev \
        libjpeg-dev \
        zlib1g-dev \
        gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app

RUN pip install --no-cache-dir . --root-user-action=ignore \
    && mkdir -p \
        /app/data/uploads \
        /app/data/exports \
        /app/data/samples \
        /app/data/templates \
        /app/data/asset

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
