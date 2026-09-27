-- N1 fix: enforce audit_log immutability at the trigger level as well as grants.
-- Reason: in local docker-compose POSTGRES_USER (mark_app) is a superuser/table owner,
-- so REVOKE alone does not prevent UPDATE/DELETE by the owner. A trigger guarantees
-- immutability even for superusers/owners, fulfilling the spec's intent
-- (Section 4.9: "revoke UPDATE, DELETE at the database layer") in a way that
-- actually fails the N1 "actual failed-write test" when the app connects as the owner.

-- Re-assert REVOKE (idempotent) — owner/superuser still bypasses grants,
-- so trigger below is the real enforcement. Grants are kept for defense-in-depth
-- when a least-privileged app role is used in production (per spec Section 4.9).
REVOKE UPDATE, DELETE ON audit_log FROM mark_app_role;
GRANT INSERT, SELECT ON audit_log TO mark_app_role;
REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC;

-- Trigger-based immutability (defense in depth, works even for owners/superusers)
CREATE OR REPLACE FUNCTION prevent_audit_log_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit_log is append-only: % not allowed (record_id=%)', TG_OP, COALESCE(OLD.record_id::text, NEW.record_id::text);
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_log_no_update ON audit_log;
CREATE TRIGGER trg_audit_log_no_update
  BEFORE UPDATE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_mutation();

DROP TRIGGER IF EXISTS trg_audit_log_no_delete ON audit_log;
CREATE TRIGGER trg_audit_log_no_delete
  BEFORE DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_mutation();
