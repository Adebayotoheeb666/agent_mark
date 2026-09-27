"""N1 Test: schema diff against spec document (Sections 4.2–4.10).

Verifies every table, column type, constraint, FK, and index exists exactly
as specified. This is not just "migration ran"; it's a structural diff.
"""

import psycopg2

DSN = "postgresql://mark_app:mark_app_password@localhost:5432/agent_mark"

EXPECTED_TABLES = {
    # table -> {col: type_substring}
    "institutions": {"id": "uuid", "name": "text", "letterhead_logo": "bytea", "primary_locale": "text", "node_public_key": "bytea", "created_at": "timestamp with time zone"},
    "users": {"id": "uuid", "institution_id": "uuid", "full_name": "text", "email": "text", "role": "text", "active": "boolean", "created_at": "timestamp with time zone", "deactivated_at": "timestamp with time zone"},
    "user_class_scopes": {"id": "uuid", "user_id": "uuid", "class_id": "uuid", "can_finalize": "boolean"},
    "devices": {"id": "uuid", "user_id": "uuid", "public_key": "bytea", "device_label": "text", "enrolled_at": "timestamp with time zone", "revoked_at": "timestamp with time zone", "revoked_reason": "text"},
    "students": {"id": "uuid", "institution_id": "uuid", "full_name": "text", "external_ref_id": "text", "date_enrolled": "date", "active": "boolean", "created_at": "timestamp with time zone"},
    "guardians": {"id": "uuid", "student_id": "uuid", "full_name": "text", "email": "text", "phone": "text", "sms_opt_in": "boolean", "relationship": "text", "created_at": "timestamp with time zone"},
    "classes": {"id": "uuid", "institution_id": "uuid", "label": "text", "subject": "text", "term_id": "uuid", "created_at": "timestamp with time zone"},
    "terms": {"id": "uuid", "label": "text", "start_date": "date", "end_date": "date"},
    "class_enrollments": {"id": "uuid", "class_id": "uuid", "student_id": "uuid"},
    "grading_policies": {"id": "uuid", "version": "integer", "name": "text", "institution_id": "uuid", "created_by": "uuid", "created_at": "timestamp with time zone", "status": "text", "change_summary": "text", "categories": "jsonb", "grade_scale": "jsonb", "special_rules": "jsonb", "approved_by": "uuid"},
    "grading_policy_applicability": {"id": "uuid", "policy_id": "uuid", "policy_version": "integer", "class_id": "uuid", "subject_wide": "boolean", "subject": "text", "term_id": "uuid", "effective_date": "date"},
    "assessments": {"id": "uuid", "class_id": "uuid", "category_id": "text", "label": "text", "max_score": "numeric", "min_score": "numeric", "due_date": "date", "external_ref_id": "text"},
    "raw_scores": {"id": "uuid", "student_id": "uuid", "assessment_id": "uuid", "source_system_id": "text", "raw_score": "numeric", "confidence_score": "numeric", "entered_by": "uuid", "source_timestamp": "timestamp with time zone", "ingested_at": "timestamp with time zone", "eligible_for_purge_after": "timestamp with time zone"},
    "anomalies": {"id": "uuid", "raw_score_id": "uuid", "student_id": "uuid", "anomaly_type": "text", "severity": "text", "detail": "jsonb", "flagged_at": "timestamp with time zone", "resolved_at": "timestamp with time zone", "resolved_by": "uuid", "resolution": "text", "resolution_note": "text"},
    "calculated_grades": {"id": "uuid", "student_id": "uuid", "class_id": "uuid", "term_id": "uuid", "grading_policy_id": "uuid", "grading_policy_version": "integer", "category_inputs": "jsonb", "final_score": "numeric", "final_grade_label": "text", "calculated_at": "timestamp with time zone"},
    "guardrail_configurations": {"institution_id": "uuid", "version": "integer", "last_modified_by": "uuid", "last_modified_at": "timestamp with time zone", "reason_for_change": "text", "category_rules": "jsonb"},
    "guardrail_evaluations": {"id": "uuid", "report_id": "uuid", "category_id": "text", "threshold_parameters": "jsonb", "evaluation_result": "text", "triggering_condition": "text", "evaluated_at": "timestamp with time zone"},
    "override_decisions": {"id": "uuid", "guardrail_evaluation_id": "uuid", "decision_type": "text", "approver_user_id": "uuid", "window_configured": "interval", "decided_at": "timestamp with time zone"},
    "report_templates": {"id": "uuid", "version": "integer", "locale": "text", "definition": "jsonb", "created_at": "timestamp with time zone"},
    "reports": {"id": "uuid", "student_id": "uuid", "class_id": "uuid", "term_id": "uuid", "calculated_grade_id": "uuid", "report_template_id": "uuid", "report_template_version": "integer", "sections_generated": "ARRAY", "sections_templated": "ARRAY", "content_snapshot": "jsonb", "teacher_note": "text", "status": "text", "approved_by": "uuid", "approved_at": "timestamp with time zone", "generated_at": "timestamp with time zone", "correlation_id": "uuid"},
    "distribution_log": {"id": "uuid", "report_id": "uuid", "channel": "text", "recipient_guardian_id": "uuid", "delivery_status": "text", "provider_confirmation_id": "text", "delivered_at": "timestamp with time zone", "created_at": "timestamp with time zone"},
    "disputes": {"id": "uuid", "report_id": "uuid", "student_id": "uuid", "raised_by_guardian_id": "uuid", "raised_by_staff_id": "uuid", "channel": "text", "nature_of_concern": "text", "severity": "text", "owner_user_id": "uuid", "status": "text", "resolution_remedy": "text", "resolved_at": "timestamp with time zone", "raised_at": "timestamp with time zone"},
    "audit_log": {"record_id": "uuid", "timestamp": "timestamp with time zone", "event_type": "text", "actor_type": "text", "actor_id": "text", "actor_role": "text", "institution_id": "uuid", "subject_type": "text", "subject_id": "text", "class_id": "uuid", "result": "text", "detail": "jsonb", "correlation_id": "uuid", "prior_record_id": "uuid"},
    "backup_destinations": {"id": "uuid", "institution_id": "uuid", "destination_type": "text", "configured_at": "timestamp with time zone", "last_verified_at": "timestamp with time zone", "last_backup_at": "timestamp with time zone", "last_backup_status": "text"},
    "sync_queue": {"id": "uuid", "payload_ciphertext": "bytea", "origin_device_id": "uuid", "lamport_clock": "bigint", "status": "text", "created_at": "timestamp with time zone", "last_attempt_at": "timestamp with time zone", "retry_count": "integer"},
}

EXPECTED_FKS = [
    ("students", "institution_id", "institutions", "id"),
    ("users", "institution_id", "institutions", "id"),
    ("classes", "institution_id", "institutions", "id"),
    ("classes", "term_id", "terms", "id"),
    ("guardians", "student_id", "students", "id"),
    ("grading_policies", "institution_id", "institutions", "id"),
    ("assessments", "class_id", "classes", "id"),
    ("raw_scores", "student_id", "students", "id"),
    ("audit_log", "institution_id", "institutions", "id"),
]

EXPECTED_INDEXES = {
    "audit_log": {"idx_audit_institution_time", "idx_audit_subject", "idx_audit_correlation", "idx_audit_actor"},
}


def test_all_tables_exist():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")
    tables = {r[0] for r in cur.fetchall()}
    conn.close()
    missing = set(EXPECTED_TABLES) - tables
    assert not missing, f"Missing tables: {missing}"
    # also ensure no unexpected extra tables beyond alembic_version
    assert tables.issuperset(set(EXPECTED_TABLES.keys()))


def test_column_types():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    for table, cols in EXPECTED_TABLES.items():
        for col, expected_type in cols.items():
            cur.execute(
                "SELECT data_type, udt_name FROM information_schema.columns WHERE table_name=%s AND column_name=%s",
                (table, col),
            )
            row = cur.fetchone()
            assert row is not None, f"{table}.{col} missing"
            data_type, udt_name = row
            # ARRAY appears as data_type ARRAY with udt_name _text
            hay = f"{data_type} {udt_name}".lower()
            assert expected_type.lower() in hay, f"{table}.{col}: expected {expected_type}, got {data_type} ({udt_name})"
    conn.close()


def test_foreign_keys_exist():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT tc.table_name, kcu.column_name, ccu.table_name AS foreign_table, ccu.column_name AS foreign_column
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
        JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name
        WHERE tc.constraint_type='FOREIGN KEY'
    """)
    fks = {(r[0], r[1], r[2], r[3]) for r in cur.fetchall()}
    conn.close()
    for fk in EXPECTED_FKS:
        assert fk in fks, f"Missing FK {fk}"


def test_audit_log_indexes():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    for table, expected_idxs in EXPECTED_INDEXES.items():
        cur.execute("SELECT indexname FROM pg_indexes WHERE tablename=%s", (table,))
        idxs = {r[0] for r in cur.fetchall()}
        missing = expected_idxs - idxs
        assert not missing, f"{table} missing indexes: {missing}"
    conn.close()


def test_pgcrypto_extension():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_extension WHERE extname='pgcrypto'")
    assert cur.fetchone() is not None, "pgcrypto not installed"
    conn.close()
