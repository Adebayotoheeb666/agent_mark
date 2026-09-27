#!/usr/bin/env python3
"""Quick CLI to verify N1 schema against spec — run without pytest."""

import psycopg2

DSN = "postgresql://mark_app:mark_app_password@localhost:5432/agent_mark"

conn = psycopg2.connect(DSN)
cur = conn.cursor()
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
tables = [r[0] for r in cur.fetchall()]
print(f"Tables ({len(tables)}):", tables)
cur.execute("SELECT extname FROM pg_extension")
print("Extensions:", [r[0] for r in cur.fetchall()])
cur.execute("SELECT version_num FROM alembic_version")
print("Alembic:", cur.fetchone())
# Check audit_log grants
cur.execute("SELECT grantee, privilege_type FROM information_schema.role_table_grants WHERE table_name='audit_log' ORDER BY grantee, privilege_type")
for row in cur.fetchall():
    print("GRANT", row)
# Check triggers
cur.execute("SELECT trigger_name, action_statement FROM information_schema.triggers WHERE event_object_table='audit_log'")
for row in cur.fetchall():
    print("TRIGGER", row)
conn.close()
print("OK — schema verification complete.")
