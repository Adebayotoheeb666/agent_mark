"""Enforce audit_log immutability via trigger (N1 gate fix)."""
from pathlib import Path
from alembic import op

revision = "002_audit_immutability"
down_revision = "001_n1_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = (Path(__file__).parent.parent / "002_audit_immutability_trigger.sql").read_text(encoding="utf-8")
    # Use raw DBAPI connection to allow multi-statement DO blocks
    conn = op.get_bind().connection.dbapi_connection  # type: ignore
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_no_update ON audit_log")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_no_delete ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_log_mutation()")
