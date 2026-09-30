# Sandbox image of the generated prototypes (spec 7.4, ADR-0013): Node, esbuild, React and the NexTI design system,
# installed at build time with exact versions because the sandbox runs without network. Build context: the
# repository root (docker build -f infra/sandbox/web/Dockerfile .). Base image pinned by digest.
FROM node@sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1
WORKDIR /opt/sandbox
COPY infra/sandbox/web/package.json infra/sandbox/web/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund && node -e "require('esbuild')"
COPY packages/ds/src /opt/ds
COPY infra/sandbox/web/entry.tsx infra/sandbox/web/build.mjs /opt/sandbox/
LABEL org.opencontainers.image.title="nexti-sandbox-web" org.opencontainers.image.description="Sandbox for the generated prototypes"
