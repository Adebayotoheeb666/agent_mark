-- N1 fix (independent-verification finding 2026-09-28): audit_log was not
-- append-only. The 002 triggers cover BEFORE UPDATE / BEFORE DELETE, but row-level
-- triggers never fire on TRUNCATE, and the app's login role is a superuser/table
-- owner, so TRUNCATE audit_log; destroyed every record with no test failing.
-- Statement-level trigger below closes the TRUNCATE path. Caveat, recorded
-- honestly: triggers are defense-in-depth only against a superuser (who can
-- DISABLE TRIGGER); the real fix is the least-privilege app role (004).

CREATE OR REPLACE FUNCTION prevent_audit_log_truncate() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit_log is append-only: TRUNCATE not allowed';
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_log_no_truncate ON audit_log;
CREATE TRIGGER trg_audit_log_no_truncate
  BEFORE TRUNCATE ON audit_log
  FOR EACH STATEMENT EXECUTE FUNCTION prevent_audit_log_truncate();
