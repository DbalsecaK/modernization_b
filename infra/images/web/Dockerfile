# The web of the platform (ADR-0024): the React build served by nginx without root, with the API behind the same
# origin (/api and /auth), so the BFF's session cookie and Origin check work as in development.
FROM node:24.21.0@sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1 AS build
RUN corepack enable
WORKDIR /src
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
COPY tools/lint/package.json tools/lint/package.json
COPY tools/codegen/package.json tools/codegen/package.json
RUN pnpm install --frozen-lockfile --filter @nexti/web...
COPY apps/web apps/web
COPY packages/ds packages/ds
RUN pnpm --filter @nexti/web exec vite build

FROM nginxinc/nginx-unprivileged:1.29.2-alpine@sha256:031d8c8ab79d2d171a2a383aa50a06f527791c05ba1aeae9ca05d7b9779caf8e
COPY infra/images/web/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY infra/images/web/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /src/apps/web/dist /usr/share/nginx/html
ENV API_UPSTREAM=http://api:8100
EXPOSE 8080
