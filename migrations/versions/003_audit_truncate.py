"""Close the TRUNCATE path on audit_log (independent-verification finding).

Revision ID: 003_audit_truncate
Revises: 002_audit_immutability
Create Date: 2026-09-28
"""
from pathlib import Path
from alembic import op

revision = "003_audit_truncate"
down_revision = "002_audit_immutability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = (Path(__file__).parent.parent / "003_audit_log_truncate_trigger.sql").read_text(encoding="utf-8")
    # Use raw DBAPI connection to allow multi-statement scripts
    conn = op.get_bind().connection.dbapi_connection  # type: ignore
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_no_truncate ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_log_truncate()")
