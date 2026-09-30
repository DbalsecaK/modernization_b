# Sandbox image of the frontend packs (spec 8.4, ADR-0016): TypeScript, esbuild, React, Angular with its AOT compiler,
# jsdom and axe-core, installed at build time with exact versions because the sandbox runs without network. Build
# context: the repository root (docker build -f infra/sandbox/frontend/Dockerfile .). Base image pinned by digest.
FROM node@sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1
WORKDIR /opt/sandbox
COPY infra/sandbox/frontend/package.json infra/sandbox/frontend/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund \
    && node -e "require('esbuild'); require('typescript'); require('jsdom'); require('axe-core')" \
    && node_modules/.bin/ngc --version
COPY packages/ds/src /opt/ds
COPY infra/sandbox/frontend/scripts /opt/sandbox/scripts
LABEL org.opencontainers.image.title="nexti-sandbox-frontend" org.opencontainers.image.description="Sandbox for the generated React and Angular frontends"
