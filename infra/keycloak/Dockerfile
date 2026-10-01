# Keycloak with the platform's login theme (ADR-0022). The theme is built with Keycloakify (Vite, then Maven packages
# the jar) and copied to the providers of the same Keycloak version the Compose ran before M0b.
FROM node:22.21.1-bookworm-slim@sha256:25b3eb23a00590b7499f2a2ce939322727fcce1b15fdd69754fcd09536a3ae2c AS node
FROM maven:3.9.11-eclipse-temurin-21@sha256:6fdc855a6ed81d288ca7ca37ac6ff5e9308b612485c0801d70b25a858c83d237 AS theme
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
WORKDIR /theme
COPY theme/package.json theme/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY theme/ ./
RUN npm run build

FROM quay.io/keycloak/keycloak:26.7.4@sha256:82a77884f3af238beab1e7afd63b5f530e1b5c0590bd7aa60b40a40463e29b2c
COPY --from=theme /theme/dist_keycloak/nexti-keycloak-theme.jar /opt/keycloak/providers/nexti-keycloak-theme.jar
