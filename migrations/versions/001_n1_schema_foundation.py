"""N1 schema foundation — Sections 4.1–4.10.

Revision ID: 001_n1_foundation
Revises: None
Create Date: 2026-09-22
"""
from pathlib import Path
from alembic import op

revision = "001_n1_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = Path(__file__).parent.parent / "001_n1_schema_foundation.sql"
    sql = sql_path.read_text(encoding="utf-8")
    # Execute as single script; psycopg splits on semicolons correctly via op.execute.
    # Use raw connection to allow DO blocks and multiple statements.
    conn = op.get_bind()
    conn.exec_driver_sql(sql)


def downgrade() -> None:
    # N1 is foundation — downgrade drops everything in reverse dependency order.
    # Kept explicit for local dev reset; not used in production.
    tables = [
        "sync_queue",
        "backup_destinations",
        "audit_log",
        "disputes",
        "distribution_log",
        "override_decisions",
        "guardrail_evaluations",
        "reports",
        "report_templates",
        "guardrail_configurations",
        "calculated_grades",
        "anomalies",
        "raw_scores",
        "assessments",
        "grading_policy_applicability",
        "grading_policies",
        "devices",
        "user_class_scopes",
        "class_enrollments",
        "guardians",
        "users",
        "classes",
        "students",
        "terms",
        "institutions",
    ]
    for t in tables:
        op.execute(f'DROP TABLE IF EXISTS "{t}" CASCADE')
    op.execute('DROP EXTENSION IF EXISTS "pgcrypto"')
