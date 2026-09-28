-- Seed init for docker-entrypoint-initdb.d
-- Creates the application role so the N1 migration's REVOKE/GRANT statements succeed on first boot.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mark_app_role') THEN
    CREATE ROLE mark_app_role NOLOGIN;
  END IF;
END
$$;
GRANT mark_app_role TO mark_app;
-- N2 (verification finding 2026-09-28): least-privilege app login. The 004
-- migration converges the same state idempotently; this only ensures the role
-- exists before migrations run. Default password must match DATABASE_URL in
-- .env.example — change both together, never one side alone.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mark_api') THEN
    CREATE ROLE mark_api LOGIN INHERIT PASSWORD 'mark_api_password';
  END IF;
END
$$;
GRANT mark_app_role TO mark_api;
