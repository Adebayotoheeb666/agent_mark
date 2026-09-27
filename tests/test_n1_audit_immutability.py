"""N1 Test: audit_log immutability enforced at the database layer.

Per Phase Gate Checklist: UPDATE and DELETE against audit_log using the
application's own database role must be rejected at the DB layer.
"""

import psycopg2
import uuid

DSN = "postgresql://mark_app:mark_app_password@localhost:5432/agent_mark"


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
    """Verify privilege table directly."""
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
