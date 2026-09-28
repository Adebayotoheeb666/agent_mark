#!/bin/sh
# Seed init for docker-entrypoint-initdb.d (verification finding 2026-09-28).
# Creates the group role and the least-privilege app login. The app password
# comes from the container environment — compose forwards MARK_API_PASSWORD
# from .env, the single credential source. Never hard-code a real credential.
set -eu

: "${MARK_API_PASSWORD:=mark_api_password}"

psql -v ON_ERROR_STOP=1 \
  -v login_user="$POSTGRES_USER" \
  -v api_password="$MARK_API_PASSWORD" \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'EOSQL'
-- :'var' interpolation does NOT happen inside $$...$$ bodies, so the password
-- is applied with ALTER ROLE outside the DO block, never inside it.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mark_app_role') THEN
    CREATE ROLE mark_app_role NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mark_api') THEN
    CREATE ROLE mark_api LOGIN INHERIT;
  END IF;
END
$$;
ALTER ROLE mark_api WITH PASSWORD :'api_password';
GRANT mark_app_role TO :"login_user";
GRANT mark_app_role TO mark_api;
EOSQL
