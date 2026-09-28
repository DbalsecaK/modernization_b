#!/bin/sh
# Creates the database roles and one database per service. Runs once, on an empty data volume.
#
# Platform roles (spec 14.2, ADR-0001):
#   platform_owner  owns the platform schema and runs the Alembic migrations.
#   platform_app    the API at runtime: not the owner, no BYPASSRLS, so Row-Level Security always applies.
#   authz_relay     the OpenFGA outbox relay; it only gets the grants a later migration gives it.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v owner_pw="$PLATFORM_OWNER_PASSWORD" \
  -v app_pw="$PLATFORM_APP_PASSWORD" \
  -v relay_pw="$AUTHZ_RELAY_PASSWORD" \
  -v keycloak_pw="$KEYCLOAK_DB_PASSWORD" \
  -v openfga_pw="$OPENFGA_DB_PASSWORD" \
  -v langfuse_pw="$LANGFUSE_DB_PASSWORD" <<'EOSQL'
-- CREATEDB lets the test suite create throwaway databases (development only).
CREATE ROLE platform_owner LOGIN CREATEDB PASSWORD :'owner_pw';
CREATE ROLE platform_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'app_pw';
CREATE ROLE authz_relay LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'relay_pw';
-- The owner grants runtime roles on the tables it creates (also in test databases).
GRANT platform_app, authz_relay TO platform_owner;

CREATE DATABASE platform OWNER platform_owner;
REVOKE ALL ON DATABASE platform FROM PUBLIC;
GRANT CONNECT ON DATABASE platform TO platform_app, authz_relay;

CREATE ROLE keycloak LOGIN PASSWORD :'keycloak_pw';
CREATE DATABASE keycloak OWNER keycloak;
REVOKE ALL ON DATABASE keycloak FROM PUBLIC;

CREATE ROLE openfga LOGIN PASSWORD :'openfga_pw';
CREATE DATABASE openfga OWNER openfga;
REVOKE ALL ON DATABASE openfga FROM PUBLIC;

CREATE ROLE langfuse LOGIN PASSWORD :'langfuse_pw';
CREATE DATABASE langfuse OWNER langfuse;
REVOKE ALL ON DATABASE langfuse FROM PUBLIC;
EOSQL

# Only the owner creates objects in the platform schema.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname platform <<'EOSQL'
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO platform_owner;
EOSQL
