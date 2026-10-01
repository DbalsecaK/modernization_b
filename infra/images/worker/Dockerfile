# The worker of the platform (ADR-0024): runs the pipelines and, through the Docker CLI, the sandboxes (15.5). The
# Docker daemon is not in this image: a rootless docker:dind sidecar in Kubernetes, the host's daemon in Compose
# (DOCKER_HOST). The sandbox inputs go under TMPDIR, a directory the daemon sees at the same path.
FROM ghcr.io/astral-sh/uv:0.12.19@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424 AS uv
FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7 AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
# The whole workspace: uv resolves the members from the lock; only the package's dependencies are installed.
COPY pyproject.toml uv.lock ./
COPY apps ./apps
COPY packages ./packages
RUN uv sync --frozen --no-dev --no-editable --package nexti-worker

FROM docker:28.5.1-cli@sha256:9190b0613792e658a7783cf14b2d5ace5941bb68ede7276922ea36ee457d76ad AS docker

FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7
RUN groupadd --system --gid 10001 nexti && useradd --system --uid 10001 --gid nexti --home /app nexti \
 && mkdir -p /sandbox-io && chown nexti:nexti /sandbox-io
COPY --from=build /app/.venv /app/.venv
COPY --from=docker /usr/local/bin/docker /usr/local/bin/docker
ENV PATH=/app/.venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_ENV=production TMPDIR=/sandbox-io
WORKDIR /app
ARG NEXTI_VERSION=dev
ENV NEXTI_VERSION=$NEXTI_VERSION
USER 10001:10001
CMD ["python", "-m", "nexti_worker"]
