"""N1 Test: audit_log immutability enforced at the database layer.

Per Phase Gate Checklist: UPDATE and DELETE against audit_log using the
application's own database role must be rejected at the DB layer.
"""

import psycopg2
import uuid

# App runtime role (least-privilege mark_api, migration 004): these tests must
# exercise the connection the app actually uses — not the mark_app owner.
APP_DSN = "postgresql://mark_api:mark_api_password@localhost:5432/agent_mark"
# Owner role: used only to prove the trigger layer constrains even the owner.
OWNER_DSN = "postgresql://mark_app:mark_app_password@localhost:5432/agent_mark"
DSN = APP_DSN


def _ensure_institution(cur):
    cur.execute("SELECT id FROM institutions LIMIT 1")
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("INSERT INTO institutions (name, node_public_key) VALUES ('Gate Test School', %s) RETURNING id", (b"\x00\x01",))
    return cur.fetchone()[0]


def test_audit_log_update_rejected_at_db_layer():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    inst_id = _ensure_institution(cur)
    conn.commit()
    cur.execute(
        "INSERT INTO audit_log (event_type, actor_type, actor_id, institution_id, subject_type, subject_id, result, detail) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING record_id",
        ("SOURCE_SYNC_EXECUTED", "system", "test_runner", inst_id, "student", "s-1", "success", '{"probe": true}'),
    )
    rec = cur.fetchone()[0]
    conn.commit()

    # UPDATE must fail
    try:
        cur.execute("UPDATE audit_log SET result='failure' WHERE record_id=%s", (rec,))
        conn.commit()
        assert False, "UPDATE on audit_log should have been rejected but succeeded"
    except psycopg2.Error as e:
        conn.rollback()
        msg = str(e).lower()
        assert "append-only" in msg or "permission denied" in msg or "not allowed" in msg, f"Unexpected error: {e}"

    # DELETE must fail
    try:
        cur.execute("DELETE FROM audit_log WHERE record_id=%s", (rec,))
        conn.commit()
        assert False, "DELETE on audit_log should have been rejected but succeeded"
    except psycopg2.Error as e:
        conn.rollback()
        msg = str(e).lower()
        assert "append-only" in msg or "permission denied" in msg or "not allowed" in msg, f"Unexpected error: {e}"
    conn.close()


def test_audit_log_insert_still_allowed():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT id FROM institutions LIMIT 1")
    inst_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO audit_log (event_type, actor_type, actor_id, institution_id, subject_type, subject_id, result, detail) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING record_id",
        ("REPORT_GENERATED", "system", "test_runner", inst_id, "report", str(uuid.uuid4()), "success", '{"probe": true}'),
    )
    rec = cur.fetchone()[0]
    conn.commit()
    assert rec is not None
    conn.close()


def test_mark_app_role_cannot_update_delete():
    """Verify privilege table directly — for the group role AND the app login.

    The pre-split version of this test only checked the mark_app_role group
    while connecting as the mark_app superuser, so it passed without proving
    anything about the app connection. Both are asserted now.
    """
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT has_table_privilege('mark_app_role', 'audit_log', 'UPDATE'),
               has_table_privilege('mark_app_role', 'audit_log', 'DELETE'),
               has_table_privilege('mark_app_role', 'audit_log', 'INSERT'),
               has_table_privilege('mark_app_role', 'audit_log', 'SELECT')
    """)
    can_update, can_delete, can_insert, can_select = cur.fetchone()
    conn.close()
    assert not can_update, "mark_app_role must not have UPDATE on audit_log"
    assert not can_delete, "mark_app_role must not have DELETE on audit_log"
    assert can_insert, "mark_app_role must have INSERT on audit_log"
    assert can_select, "mark_app_role must have SELECT on audit_log"

    conn = psycopg2.connect(APP_DSN)
    cur = conn.cursor()
    cur.execute("SELECT current_user")
    assert cur.fetchone()[0] == "mark_api", "N1 gate tests must connect as the app role"
    cur.execute("""
        SELECT has_table_privilege('mark_api', 'audit_log', 'UPDATE'),
               has_table_privilege('mark_api', 'audit_log', 'DELETE'),
               has_table_privilege('mark_api', 'audit_log', 'TRUNCATE'),
               has_table_privilege('mark_api', 'audit_log', 'INSERT'),
               has_table_privilege('mark_api', 'audit_log', 'SELECT')
    """)
    api_update, api_delete, api_truncate, api_insert, api_select = cur.fetchone()
    conn.close()
    assert not api_update, "app role must not have UPDATE on audit_log"
    assert not api_delete, "app role must not have DELETE on audit_log"
    assert not api_truncate, "app role must not have TRUNCATE on audit_log"
    assert api_insert, "app role must have INSERT on audit_log"
    assert api_select, "app role must have SELECT on audit_log"


def test_audit_log_truncate_rejected_at_db_layer():
    """TRUNCATE must fail for BOTH roles, each by its own layer.

    App role (mark_api): denied by GRANT (migration 004 role split).
    Owner role (mark_app): denied by the BEFORE TRUNCATE statement trigger
    (migration 003) — row-level triggers never fire on TRUNCATE, which is the
    hole the pre-split suite missed.
    """
    conn = psycopg2.connect(APP_DSN)
    cur = conn.cursor()
    cur.execute("SELECT id FROM institutions LIMIT 1")
    inst_id = cur.fetchone()[0]
    try:
        cur.execute("TRUNCATE audit_log")
        conn.commit()
        assert False, "TRUNCATE on audit_log as the app role should have been rejected"
    except psycopg2.Error as e:
        conn.rollback()
        assert "permission denied" in str(e).lower(), f"Unexpected error: {e}"
    finally:
        conn.close()

    conn = psycopg2.connect(OWNER_DSN)
    cur = conn.cursor()
    try:
        cur.execute("TRUNCATE audit_log")
        conn.commit()
        assert False, "TRUNCATE on audit_log as owner should have been rejected by trigger"
    except psycopg2.Error as e:
        conn.rollback()
        assert "append-only" in str(e).lower(), f"Unexpected error: {e}"
    # Owner row-level layer (migration 002) still armed behind the app-role split.
    cur.execute("SELECT record_id FROM audit_log LIMIT 1")
    rec = cur.fetchone()[0]
    try:
        cur.execute("UPDATE audit_log SET result='failure' WHERE record_id=%s", (rec,))
        conn.commit()
        assert False, "UPDATE on audit_log as owner should have been rejected by trigger"
    except psycopg2.Error as e:
        conn.rollback()
        assert "append-only" in str(e).lower(), f"Unexpected error: {e}"
    conn.close()
