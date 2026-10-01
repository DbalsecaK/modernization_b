# The API and BFF of the platform (ADR-0024). Multi-stage: the virtual environment is built with uv from the lock,
# the runtime has only Python, the environment and the migrations. Non-root, read-only root file system.
FROM ghcr.io/astral-sh/uv:0.12.19@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424 AS uv
FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7 AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
# The whole workspace: uv resolves the members from the lock; only the package's dependencies are installed.
COPY pyproject.toml uv.lock ./
COPY apps ./apps
COPY packages ./packages
RUN uv sync --frozen --no-dev --no-editable --package nexti-api

# The migrations also create the tables of the worker's checkpointer (LangGraph), so their environment has both.
FROM build AS build-migrate
RUN rm -rf /app/.venv && uv sync --frozen --no-dev --no-editable --package nexti-api --package nexti-worker

FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7 AS migrate
RUN groupadd --system --gid 10001 nexti && useradd --system --uid 10001 --gid nexti --home /app nexti
COPY --from=build-migrate /app/.venv /app/.venv
COPY apps/api/alembic.ini /app/apps/api/alembic.ini
COPY apps/api/migrations /app/apps/api/migrations
ENV PATH=/app/.venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_ENV=production
WORKDIR /app
USER 10001:10001
CMD ["alembic", "-c", "apps/api/alembic.ini", "upgrade", "head"]

FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7 AS api
RUN groupadd --system --gid 10001 nexti && useradd --system --uid 10001 --gid nexti --home /app nexti
COPY --from=build /app/.venv /app/.venv
COPY apps/api/alembic.ini /app/apps/api/alembic.ini
COPY apps/api/migrations /app/apps/api/migrations
COPY infra/openfga/model.json /app/infra/openfga/model.json
ENV PATH=/app/.venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_ENV=production \
    OPENFGA_MODEL_FILE=/app/infra/openfga/model.json
WORKDIR /app
ARG NEXTI_VERSION=dev
ENV NEXTI_VERSION=$NEXTI_VERSION
USER 10001:10001
EXPOSE 8100
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8100/api/v1/health/live', timeout=4).status == 200 else 1)"]
CMD ["uvicorn", "--factory", "nexti_api.main:create_app", "--host", "0.0.0.0", "--port", "8100", "--proxy-headers", "--forwarded-allow-ips", "*"]
