"""Least-privilege app role split (independent-verification finding).

Revision ID: 004_app_role_split
Revises: 003_audit_truncate
Create Date: 2026-09-28

App runtime connects as mark_api (member of mark_app_role); migrations keep
running as the mark_app owner.
"""
from pathlib import Path
from alembic import op

revision = "004_app_role_split"
down_revision = "003_audit_truncate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = (Path(__file__).parent.parent / "004_app_role_split.sql").read_text(encoding="utf-8")
    # Use raw DBAPI connection to allow multi-statement DO blocks
    conn = op.get_bind().connection.dbapi_connection  # type: ignore
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def downgrade() -> None:
    # Remove app-role membership/grants; keep the role itself so a
    # downgrade never strands a live app connection mid-flight.
    op.execute("REVOKE mark_app_role FROM mark_api")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM mark_app_role")
    op.execute("GRANT SELECT, INSERT ON audit_log TO mark_app_role")
