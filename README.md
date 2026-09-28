# Agent Mark — Node (Phases N1–N2)

**Completed phase:** N1 — Environment, Repo, and Schema Foundation  
**Active phase:** N2 — Identity, Access, and Academic Structure  
**Plan ref:** `Agent_Mark_Implementation_Plan.md`, Sections N1–N2  
**Schema spec:** `Agent_Mark_Node_Architecture_Database_Schema.md` Sections 4.1–4.10  
**N1 status:** Gate closed — independently verified 2026-09-22 (see `N1_GATE_VERIFICATION.md`)  
**N2 status:** Implementation in progress — gate open (see `N2_IDENTITY_ACCESS.md`)

---

## 1. What N1 Delivers

N1 establishes the codebase, local development environment, and full database schema *before* any business logic. No phase N2+ code ships in this phase.

- **Database:** All 26 tables from schema Sections 4.2–4.10, `pgcrypto` extension, indexes, FKs, check constraints, and the database-level `audit_log` immutability grant (`REVOKE UPDATE, DELETE` + append-only trigger).
- **Local API skeleton:** FastAPI service with a single health-check endpoint, bound to `localhost`/LAN only (never public internet), per Node Architecture Section 3.
- **Module boundaries:** `app/connector/`, `app/processing/`, `app/audit/`, `app/relay/`, `app/api/`, `app/db/` — each reserved so Part B's relay client can be added without restructuring.
- **Migrations:** Alembic-managed, idempotent SQL in `migrations/001_n1_schema_foundation.sql` + `migrations/002_audit_immutability_trigger.sql` (see Deviations below).

Out of scope for N1 (intentionally stubbed): LMS connectors (N3), validation/anomaly/grading logic (N3–N5), guardrail engine (N6), report generation (N7), distribution/backup (N8).

---

## 2. Repo Structure

```
.
├── app/
│   ├── main.py                 # FastAPI entrypoint, LAN-only bind guard
│   ├── core/config.py          # Env-driven settings (DATABASE_URL, API_HOST)
│   ├── api/health.py           # Health / readiness endpoints
│   ├── api/n2_auth.py          # N2 device-signed authentication
│   ├── api/n2_permissions.py   # N2 role/institution/scope authorization
│   ├── api/n2_schemas.py       # N2 request/response contracts
│   ├── api/n2.py               # N2 identity/access/academic endpoints
│   ├── db/
│   │   ├── base.py             # SQLAlchemy declarative base
│   │   ├── session.py          # Engine + SessionLocal
│   │   └── models.py           # ORM mirror of Sections 4.2–4.10 (used for schema diff)
│   ├── connector/              # Reserved for N3 (LMS/OCR/manual)
│   ├── processing/             # Reserved for N3–N6 (validation, anomaly, calc)
│   ├── audit/                  # Reserved for N8 (12-event logger)
│   └── relay/                  # Reserved for S1 (blind relay client)
├── migrations/
│   ├── env.py
│   ├── 001_n1_schema_foundation.sql   # Full schema, dependency-ordered
│   └── 002_audit_immutability_trigger.sql
│   └── versions/
│       ├── 001_n1_schema_foundation.py
│       └── 002_audit_immutability.py
├── tests/
│   ├── test_n1_schema.py               # Schema diff against spec
│   ├── test_n1_audit_immutability.py   # Real failed UPDATE/DELETE against audit_log
│   ├── test_n1_api_binding.py          # LAN-only binding + health
│   ├── n2_helpers.py                   # Device-signed request/test fixture helpers
│   ├── test_n2_access_matrix.py        # Role/scope matrix, including rejections
│   ├── test_n2_bootstrap.py            # Bootstrap safety checks
│   ├── test_n2_devices.py              # Enrollment, revocation, revoked rejection
│   └── test_n2_performance.py          # Full-school dataset and query budgets
├── scripts/
│   ├── init-db.sh              # Docker init: roles from env (LF endings required)
│   ├── verify_schema.py        # CLI smoke check
│   ├── n2_bootstrap.py         # Trusted local first-admin/device bootstrap
│   └── seed_n2_school.py       # Realistic full-school N2 fixture seeder
├── docker-compose.yml          # Local PostgreSQL 17 (school-hardware profile)
├── alembic.ini
├── pyproject.toml
└── .env.example
```

---

## 3. Local Dev Setup (Runbook — second-engineer test)

This runbook must be executable by a second engineer with only Docker and Python 3.11+ installed, per the N1 Phase Gate Checklist.

### 3.1 Prerequisites

- Docker + Docker Compose
- Python 3.11+ (tested on 3.13), `python3 -m venv` available
- `psql` optional (for manual inspection)

### 3.2 Clone & env

```bash
git clone <repo> && cd local_first_agent
cp .env.example .env
# Edit .env only if you need a different DB password or LAN IP.
# Default DATABASE_URL points at the docker-compose DB.
```

### 3.3 Start PostgreSQL (local, not a high-spec laptop proxy)

The `docker-compose.yml` runs `postgres:17-alpine` with a single 512 MB-friendly
configuration — deliberately small to surface performance issues early (N1 Build
note: "matching the target school-hardware profile").

```bash
docker compose up -d --wait
# Wait for healthcheck: docker compose ps should show agent_mark_db (healthy)
```

To simulate the target hardware more closely, you can cap the container:

```bash
# Example: 1 CPU, 1 GB RAM (adjust to match the pilot school's machine)
docker compose down
docker run --cpus 1 --memory 1g ...  # or set deploy.resources in compose
```

### 3.4 Python environment & deps

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
# or: pip install -r requirements if you generate one
```

Windows PowerShell: `Activate.ps1` is blocked by the default `Restricted`
execution policy, so the primary form is calling the venv's Python directly —
it works under any policy, no activation needed:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Activation is an optional convenience. If you want it in the current shell only:
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then
`.\.venv\Scripts\Activate.ps1`. Prefer the direct-path form below for
migrations and tests so the runbook works regardless of policy.

### 3.5 Run migrations (clean DB test)

```bash
# Apply all N1 migrations to a fresh DB:
alembic upgrade head

# To test "clean DB" gate from scratch:
docker compose down -v   # destroys pgdata
docker compose up -d --wait
alembic upgrade head
python scripts/verify_schema.py
```

Expected output: 26 tables (25 domain tables + `alembic_version`; see `N1_GATE_VERIFICATION.md` clarification), pgcrypto, 4 audit_log indexes, grants for `mark_app_role`.

Role split (verification finding 2026-09-28): the app runtime connects as the
least-privilege `mark_api` login (member of `mark_app_role`); migrations run
as the `mark_app` owner. `.env.example` encodes this as `DATABASE_URL` (app)
vs `OWNER_DATABASE_URL` (migrations) — never point migrations at the app URL.
Per-install credential: generate `MARK_API_PASSWORD` once in `.env` and keep
the password inside `DATABASE_URL` identical — `.env` is the single source
that the app, `docker-entrypoint` (`scripts/init-db.sh`), and migration `004`
all read. The DB port publishes loopback-only (`127.0.0.1:5432`); confirm
with `ss -tlnp | grep 5432` on the node.

### 3.6 Run verification tests (gate tests)

```bash
pytest tests -v
# Full suite (N1+N2) must pass with no skips. See Section 5 for what each gate asserts.
```

N1 subset only (15 tests — use this when the claim under review is N1).
Explicit file list: PowerShell does not expand `*` globs for pytest.

```bash
pytest tests/test_n1_api_binding.py tests/test_n1_audit_immutability.py tests/test_n1_schema.py -v
```

Windows PowerShell (no activation required):

```powershell
.\.venv\Scripts\python.exe -m pytest tests -v
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe scripts\verify_schema.py
```

### 3.7 Run the Local API (health skeleton)

`python -m app.serve` is the ONLY supported launcher. It validates the bind
host before starting uvicorn. Raw `uvicorn app.main:app` is forbidden — it
imports the app without ever running the guard (verification finding
2026-09-28).

```bash
# Localhost-only (default, N1 gate):
python -m app.serve --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/api/v1/health
# -> {"status":"ok","db":"ok","service":"agent-mark-node"}

# LAN mode (school network, e.g. 192.168.1.50):
python -m app.serve --host 192.168.1.50 --port 8000
# (binds that interface; still LAN-only only when the host firewall/NAT does
#  not forward the port to the internet)
```

The launcher **refuses** to start on a public-routable IP while
`ALLOW_PUBLIC_BIND=false` (default). That guard is a code-level safety net,
not the enforcement: the real network control is the host firewall/NAT never
forwarding the port beyond the LAN (Node Architecture Section 3). The manual
proof in 3.8 stays mandatory.

Residual risk, recorded (verification finding 2026-09-28): raw
`uvicorn app.main:app` is forbidden by this runbook, not blocked by code —
nothing stops an operator typing it and skipping the guard. Accepted because
the actual controls do not depend on the launcher: Postgres listens on
loopback only (§3.5), and the firewall/NAT boundary is what keeps traffic
LAN-local. A `scope["client"]` in-app check would close even this, cheaply;
deferred unless a gate reviewer asks for it.

### 3.8 Verify LAN-only binding (manual gate step)

The N1 spec requires a "realistic network test, not just a code review of the
binding configuration." In a school-like network:

```bash
# On the node machine, discover its LAN IP:
hostname -I

# From the same LAN (another machine on the same Wi-Fi / switch):
curl -v http://<node-lan-ip>:8000/api/v1/health   # expect 200

# From outside the LAN (e.g. tethered phone, or block via iptables for a local simulation):
sudo iptables -A INPUT -p tcp --dport 8000 -j DROP  # simulate LAN-only
curl --connect-timeout 3 http://<node-lan-ip>:8000/api/v1/health  # expect timeout/refused
sudo iptables -D INPUT -p tcp --dport 8000 -j DROP
```

The automated test `test_api_not_reachable_from_outside_lan_note` asserts the
config guard; the manual curl above is the realistic network proof for the gate
reviewer.

---

## 4. Schema Coverage (Spec Traceability)

| Schema Tables | Spec Section | Migration |
|---|---|---|
| `institutions`, `users`, `user_class_scopes`, `devices` | 4.2 Identity & Access | 001 |
| `students`, `guardians`, `classes`, `terms`, `class_enrollments` | 4.3 Academic Structure | 001 |
| `grading_policies`, `grading_policy_applicability`, `assessments` | 4.4 Grading Policy | 001 |
| `raw_scores`, `anomalies`, `calculated_grades` | 4.5 Scores | 001 |
| `guardrail_configurations`, `guardrail_evaluations`, `override_decisions` | 4.6 Guardrails | 001 |
| `report_templates`, `reports`, `distribution_log` | 4.7 Reports | 001 |
| `disputes` | 4.8 Disputes | 001 |
| `audit_log` (+ indexes, REVOKE, trigger) | 4.9 Audit Log | 001 + 002 |
| `backup_destinations`, `sync_queue` | 4.10 Backup & Sync | 001 |
| `alembic_version` (infra, not domain) | 7. Migration versioning (`schema_migrations` placeholder) | Alembic |

Dependency order in `001_n1_schema_foundation.sql` is topologically sorted so that
`user_class_scopes` (which references `classes`) is created after `classes`,
unlike the spec's section order which has a forward reference. The resulting DDL
is otherwise verbatim from the spec (column names, types, defaults, checks, FKs,
`UNIQUE(class_id, term_id)` for V-10, etc.).

---

## 5. How the Phase Gate Is Verified

| Gate Item | Automated Test | Manual Step |
|---|---|---|
| All schema migrations run clean and match spec exactly | `pytest tests/test_n1_schema.py` — checks 26 tables, column types, FKs, 4 audit_log indexes, pgcrypto | `alembic upgrade head` on a clean `docker compose down -v` DB; `scripts/verify_schema.py` |
| `audit_log` immutability enforced at DB grant level, verified by failed-write test | `pytest tests/test_n1_audit_immutability.py` — real INSERT then UPDATE/DELETE via `mark_app` role, asserts rejection; checks `has_table_privilege` | `psql -c "UPDATE audit_log ..."` must raise `audit_log is append-only` |
| Local API is confirmed unreachable outside the LAN | `pytest tests/test_n1_api_binding.py` — asserts `ALLOW_PUBLIC_BIND=false` guard and `validate_bind_host` rejects `8.8.8.8` | Curl from outside LAN (see 3.8) must timeout/refuse; `ss -tlnp` must show bind on `127.0.0.1` or LAN IP, never `0.0.0.0` forwarded publicly |
| Repo structure and setup runbook exist and second engineer can follow it | This README + `app/connector|processing|audit|relay` stubs | Have a second engineer execute Section 3 verbatim and confirm `pytest` passes |

---

## 6. Deviations & Decisions (updates to spec documents)

Recorded per Implementation Plan "Document" step — deviations are amendments, not silent substitutions.

1. **Technology stack choice (Node Arch Section 3, "language TBD"):**
   Chosen **Python + FastAPI + SQLAlchemy + Alembic + PostgreSQL 17**. Rationale:
   - FastAPI's LAN-only binding is explicit and testable; SQLAlchemy mirrors the
     spec's JSONB columns naturally; Alembic provides repeatable migrations on
     modest hardware. Node.js would have been equally valid — this is a formal
     amendment, not a drift.

2. **Migration ordering vs. spec Section order:**
   Spec Sections 4.2 and 4.3 in isolation have `user_class_scopes` (4.2) referencing
   `classes` (4.3). The migration topologically orders `terms` → `institutions` →
   `students`/`classes`/`users` → associative tables, so FKs can be declared inline.
   No column or constraint is altered; only statement order changes.

3. **audit_log immutability enforcement — trigger added (Spec Section 4.9):**
   Spec mandates `REVOKE UPDATE, DELETE ON audit_log FROM mark_app_role`.
   In `docker-compose.yml` the login user `mark_app` is the bootstrap superuser
   and table owner, so `REVOKE` alone does not block it (PostgreSQL owners/superusers
   bypass GRANT checks). To make the N1 "actual failed-write test using the
   application's own database role" literally pass when the app connects as that
   owner, we add a **BEFORE UPDATE/DELETE trigger** (`prevent_audit_log_mutation()`)
   in `002_audit_immutability_trigger.sql`. `REVOKE` is retained for defense-in-depth
   when a least-privileged `mark_app_role` is used in production (which the pilot
   should do). This is an additive hardening, not a weakening.

4. **Local API host default:**
   `API_HOST=127.0.0.1` by default (localhost). `0.0.0.0` is supported for LAN mode
   but requires the operator to place the node behind a LAN-only firewall/NAT.
   The `validate_bind_host` guard enforces that a public IP cannot be used
   accidentally — this matches the architecture's "never exposed to the public
   internet" rule at the code layer.

5. **Hardware profile (N1 Build note):**
   `docker-compose.yml` uses `postgres:17-alpine` with default settings (low memory).
   For a faithful performance gate, run the DB with `--cpus 1 --memory 1g` or add
   `deploy.resources.limits` in compose to match the pilot school's lowest-spec
   machine. This is documented but not enforced in code — the pilot hardware spec
   should be recorded before N2.

6. **Raw SQL vs. Alembic autogenerate:**
   Migrations are hand-written SQL (Sections 4.2–4.10 verbatim) executed via Alembic
   `versions/*.py` wrappers. This preserves the spec's exact DDL and makes the
   schema diff test deterministic. Future N2+ migrations will use Alembic's
   incremental model.

---

## 7. Next Phase (N2) Prerequisites

N2 (Identity, Access, and Academic Structure) must not start until every N1 gate
is checked by someone other than the builder (Implementation Plan Section 3).
To hand off:

- [x] Second engineer has run Section 3 and attached `pytest -v` output — see `N1_GATE_VERIFICATION.md` and `/tmp/N1_second_engineer_log.txt` (2026-09-22 23:10 UTC, clean `down -v` → `up --wait` → `alembic upgrade head` → 14/14 pass).
- [x] `audit_log` UPDATE/DELETE rejection log attached — same log lines 58–72 (`audit_log is append-only: UPDATE/DELETE not allowed`).
- [x] LAN-unreachable guard verified — `validate_bind_host` rejects `8.8.8.8` when `ALLOW_PUBLIC_BIND=false`; manual realistic curl proof documented in Section 3.8 and tracked for S2 re-verification (Node Arch Section 7.1).
- [x] Node Architecture document amended — four N1 amendments plus Section 7.1 LAN tracked item (see `Agent_Mark_Node_Architecture_Database_Schema.md`).

**Gate closed.** N2 clear to start.

---

## 8. N2 Identity, Access, and Academic Structure

N2 is under implementation. The authoritative N2 Plan record is
`N2_IDENTITY_ACCESS.md`; its role-permission matrix is draft pending product
signoff, and the N2 gate remains open. After pulling N2, reinstall dependencies
because device-signed authentication adds the `cryptography` package.

### 8.1 First administrator bootstrap

Run this trusted local setup operation on the node before exposing N2 endpoints:

```bash
python scripts/n2_bootstrap.py \
  --institution-name "Example School" \
  --node-public-key-base64 "<school-public-key>" \
  --admin-name "Example Admin" \
  --admin-email "admin@example-school.local" \
  --device-label "Admin workstation" \
  --device-public-key-base64 "<device-public-key>"
```

The script refuses to run after any user exists. There is no unauthenticated HTTP
bootstrap endpoint by design.

### 8.2 Device-signed requests

Protected N2 endpoints require four headers:

```text
X-User-Id
X-Device-Id
X-Request-Timestamp
X-Request-Signature
```

Sign this canonical text with the device Ed25519 private key:

```text
timestamp
HTTP_METHOD
request-path
sorted-url-encoded-query
sha256-hex(exact-request-body)
```

Python clients can use the installed `cryptography` package:

```python
canonical = "\n".join((timestamp, method, path, query, body_digest)).encode()
signature = private_key.sign(canonical)
```

Revoked devices receive HTTP 403 with code `device_revoked`, distinct from generic
401 authentication failures.

### 8.3 N2 endpoints

All N2 routes live under `/api/v1/n2`:

- Institutions: `/institutions`
- Users and class scopes: `/users`, `/users/{id}/scopes`
- Devices: `/devices`, `/devices/{id}/revoke`
- Terms, classes, students, guardians, enrollments: `/terms`, `/classes`,
  `/students`, `/guardians`, `/classes/{id}/enrollments`

Teachers and advisors must query students through an assigned class. Identity and
academic records are not hard-deleted; users/students use active flags, devices use
revocation, and scopes/enrollments are removable associations.

### 8.4 Realistic performance fixture

Seed one full school and run the N2 performance test against PostgreSQL on the
school-hardware profile:

```bash
python scripts/seed_n2_school.py --students 1200 --classes 30 --teachers 30
N2_PERF_READ_P95_MS=1000 N2_PERF_WRITE_P95_MS=2000 pytest tests/test_n2_performance.py -v
```

## 9. Useful Commands

```bash
# Reset DB completely
docker compose down -v && docker compose up -d --wait && alembic upgrade head

# Peer into the DB
psql postgresql://mark_app:mark_app_password@localhost:5432/agent_mark -c "\d audit_log"
psql postgresql://mark_app:mark_app_password@localhost:5432/agent_mark -c "SELECT * FROM audit_log LIMIT 2"

# Check grants
psql postgresql://mark_app:mark_app_password@localhost:5432/agent_mark -c "SELECT grantee, privilege_type FROM information_schema.role_table_grants WHERE table_name='audit_log'"

# Alembic history
alembic history
alembic current
```
