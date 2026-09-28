-- N2 fix (independent-verification finding 2026-09-28): least-privilege app role.
--
-- Until now the app connected as mark_app (superuser/table owner), so every
-- REVOKE on audit_log was bypassed and only the triggers constrained it.
-- From here: migrations keep running as mark_app (owner), while the app
-- runtime connects as mark_api, a LOGIN role that inherits exactly the
-- mark_app_role grants below — SELECT+INSERT on audit_log, CRUD elsewhere.
--
-- Default password 'mark_api_password' must match DATABASE_URL in
-- .env.example / app/core/config.py (local-dev default; override both
-- together in real deployments).
-- Assumption: audit_log is created once by 001 and never recreated, so the
-- lockdown below targets the existing table; future tables pick up CRUD via
-- the default privileges (needed by N3+).
-- NOTE (N4/N6 tracked item): grading_policies, guardrail_configurations and
-- report_templates are append-only-by-version per spec but keep full CRUD for
-- the app role here. Same layered treatment (grant split + trigger) to follow
-- when those phases land; not an N1/N2 blocker.

-- Default password comes from MARK_API_PASSWORD in the migration environment
-- (see versions/004_app_role_split.py), defaulting to 'mark_api_password' for
-- local dev. Single source: .env holds MARK_API_PASSWORD and DATABASE_URL
-- together; the migration and docker-entrypoint both consume it. Never store a
-- real credential here.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mark_api') THEN
    CREATE ROLE mark_api LOGIN INHERIT PASSWORD '__MARK_API_PASSWORD__';
  ELSE
    ALTER ROLE mark_api WITH LOGIN INHERIT PASSWORD '__MARK_API_PASSWORD__';
  END IF;
END
$$;

-- Membership: the single inheritance path for app privileges.
GRANT mark_app_role TO mark_api;

-- Base privileges for the app role (owner runs migrations; app runs CRUD).
GRANT USAGE ON SCHEMA public TO mark_app_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO mark_app_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO mark_app_role;

-- Future tables created by later migrations (as mark_app) inherit CRUD.
ALTER DEFAULT PRIVILEGES FOR ROLE mark_app IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO mark_app_role;
ALTER DEFAULT PRIVILEGES FOR ROLE mark_app IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO mark_app_role;

-- audit_log lockdown, AFTER the broad grants above (order matters).
REVOKE ALL ON audit_log FROM mark_app_role;
REVOKE ALL ON audit_log FROM PUBLIC;
GRANT SELECT, INSERT ON audit_log TO mark_app_role;
