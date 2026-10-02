# Sandbox image of the frontend packs (spec 8.4, ADR-0016, ADR-0028): TypeScript, esbuild, React, Angular with its AOT
# compiler, Next.js (its types; no `next build` in the sandbox), jsdom and axe-core, installed at build time with exact
# versions because the sandbox runs without network. Build context: the repository root
# (docker build -f infra/sandbox/frontend/Dockerfile .). Base image pinned by digest. Next's native compiler (SWC) and
# image optimizer (sharp) are removed after the install: the sandbox never runs `next build` or `next dev`.
FROM node@sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1
WORKDIR /opt/sandbox
COPY infra/sandbox/frontend/package.json infra/sandbox/frontend/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund \
    && node -e "require('esbuild'); require('typescript'); require('jsdom'); require('axe-core'); require('next/package.json')" \
    && node_modules/.bin/ngc --version \
    && rm -rf node_modules/@next/swc-* node_modules/@img node_modules/sharp \
    && npm cache clean --force
COPY packages/ds/src /opt/ds
COPY infra/sandbox/frontend/scripts /opt/sandbox/scripts
LABEL org.opencontainers.image.title="nexti-sandbox-frontend" org.opencontainers.image.description="Sandbox for the generated React, Angular and Next.js frontends"
