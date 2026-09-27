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
