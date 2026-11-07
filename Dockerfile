# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca SSL_CERT_FILE=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir uv==0.13.5 && uv sync --frozen --no-dev --no-install-project
COPY agent ./agent
COPY api ./api
COPY training ./training
COPY inference ./inference
COPY scripts ./scripts
COPY data/dataset.csv.dvc ./data/dataset.csv.dvc
COPY dvc.yaml ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export SSL_CERT_FILE=/run/secrets/proxy_ca; fi; \
    uv sync --frozen --no-dev --no-editable
ENV PATH=/app/.venv/bin:$PATH
RUN mkdir -p /app/.runtime && chown -R 1000:1000 /app
USER 1000:1000
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
