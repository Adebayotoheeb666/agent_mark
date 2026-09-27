-- =============================================================================
-- Agent Mark — Phase N1: Environment, Repo, and Schema Foundation
-- Full database schema per Node Architecture & Database Schema Sections 4.1–4.10
-- Single Alembic-equivalent migration (idempotent where safe).
-- Dependency order: extension → institutions/terms → classes/students/users
--   → associative tables → grading → scores → guardrails → reports → audit → backup
-- =============================================================================

-- 4.1 Extension & Conventions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Ensure application role exists (spec Section 4.9 references mark_app_role).
-- In local docker-compose the login user is mark_app; we make it a member of the role
-- so REVOKE/GRANT on the role applies to the app connection.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mark_app_role') THEN
    CREATE ROLE mark_app_role NOLOGIN;
  END IF;
END
$$;
-- Grant role to current login roles if they exist (idempotent)
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mark_app') THEN
    GRANT mark_app_role TO mark_app;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'postgres') THEN
    GRANT mark_app_role TO postgres;
  END IF;
END
$$;

-- =============================================================================
-- 4.2 Identity & Access  +  4.3 Academic Structure  (interleaved for FK order)
-- =============================================================================

CREATE TABLE IF NOT EXISTS institutions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    letterhead_logo BYTEA,
    primary_locale  TEXT NOT NULL DEFAULT 'en',
    node_public_key BYTEA NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS terms (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    label           TEXT NOT NULL,
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS students (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    institution_id  UUID NOT NULL REFERENCES institutions(id),
    full_name       TEXT NOT NULL,
    external_ref_id TEXT,
    date_enrolled   DATE,
    active          BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS classes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    institution_id  UUID NOT NULL REFERENCES institutions(id),
    label           TEXT NOT NULL,
    subject         TEXT NOT NULL,
    term_id         UUID NOT NULL REFERENCES terms(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    institution_id  UUID NOT NULL REFERENCES institutions(id),
    full_name       TEXT NOT NULL,
    email           TEXT UNIQUE,
    role            TEXT NOT NULL CHECK (role IN ('teacher','administrator','advisor','compliance_officer')),
    active          BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deactivated_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS guardians (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id      UUID NOT NULL REFERENCES students(id),
    full_name       TEXT NOT NULL,
    email           TEXT,
    phone           TEXT,
    sms_opt_in      BOOLEAN NOT NULL DEFAULT false,
    relationship    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS class_enrollments (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    class_id    UUID NOT NULL REFERENCES classes(id),
    student_id  UUID NOT NULL REFERENCES students(id),
    UNIQUE (class_id, student_id)
);

CREATE TABLE IF NOT EXISTS user_class_scopes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id),
    class_id    UUID NOT NULL REFERENCES classes(id),
    can_finalize BOOLEAN NOT NULL DEFAULT false,
    UNIQUE (user_id, class_id)
);

CREATE TABLE IF NOT EXISTS devices (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id),
    public_key      BYTEA NOT NULL,
    device_label    TEXT,
    enrolled_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at      TIMESTAMPTZ,
    revoked_reason  TEXT
);

-- =============================================================================
-- 4.4 Grading Policy
-- =============================================================================

CREATE TABLE IF NOT EXISTS grading_policies (
    id                  UUID NOT NULL,
    version             INTEGER NOT NULL,
    name                TEXT NOT NULL,
    institution_id      UUID NOT NULL REFERENCES institutions(id),
    created_by          UUID NOT NULL REFERENCES users(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    status              TEXT NOT NULL CHECK (status IN ('draft','active','archived')),
    change_summary      TEXT,
    categories          JSONB NOT NULL,
    grade_scale         JSONB NOT NULL,
    special_rules       JSONB NOT NULL DEFAULT '[]',
    approved_by         UUID REFERENCES users(id),
    PRIMARY KEY (id, version)
);

CREATE TABLE IF NOT EXISTS grading_policy_applicability (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id           UUID NOT NULL,
    policy_version      INTEGER NOT NULL,
    class_id            UUID REFERENCES classes(id),
    subject_wide        BOOLEAN NOT NULL DEFAULT false,
    subject             TEXT,
    term_id             UUID NOT NULL REFERENCES terms(id),
    effective_date      DATE NOT NULL,
    FOREIGN KEY (policy_id, policy_version) REFERENCES grading_policies(id, version),
    UNIQUE (class_id, term_id)
);

CREATE TABLE IF NOT EXISTS assessments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    class_id        UUID NOT NULL REFERENCES classes(id),
    category_id     TEXT NOT NULL,
    label           TEXT NOT NULL,
    max_score       NUMERIC NOT NULL,
    min_score       NUMERIC NOT NULL DEFAULT 0,
    due_date        DATE,
    external_ref_id TEXT
);

-- =============================================================================
-- 4.5 Scores & Calculated Grades
-- =============================================================================

CREATE TABLE IF NOT EXISTS raw_scores (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id          UUID NOT NULL REFERENCES students(id),
    assessment_id       UUID NOT NULL REFERENCES assessments(id),
    source_system_id    TEXT NOT NULL,
    raw_score           NUMERIC,
    confidence_score    NUMERIC,
    entered_by          UUID REFERENCES users(id),
    source_timestamp    TIMESTAMPTZ,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    eligible_for_purge_after TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS anomalies (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    raw_score_id        UUID REFERENCES raw_scores(id),
    student_id          UUID NOT NULL REFERENCES students(id),
    anomaly_type        TEXT NOT NULL CHECK (anomaly_type IN
                            ('missingScore','statisticalOutlier','dataEntryRangeError','duplicateSubmission')),
    severity            TEXT NOT NULL CHECK (severity IN ('yellow','orange','red')),
    detail              JSONB NOT NULL,
    flagged_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at         TIMESTAMPTZ,
    resolved_by         UUID REFERENCES users(id),
    resolution          TEXT CHECK (resolution IN ('confirmedCorrect','corrected','escalated')),
    resolution_note     TEXT
);

CREATE TABLE IF NOT EXISTS calculated_grades (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id          UUID NOT NULL REFERENCES students(id),
    class_id            UUID NOT NULL REFERENCES classes(id),
    term_id             UUID NOT NULL REFERENCES terms(id),
    grading_policy_id   UUID NOT NULL,
    grading_policy_version INTEGER NOT NULL,
    category_inputs     JSONB NOT NULL,
    final_score         NUMERIC NOT NULL,
    final_grade_label   TEXT NOT NULL,
    calculated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (grading_policy_id, grading_policy_version) REFERENCES grading_policies(id, version)
);

-- =============================================================================
-- 4.6 Guardrails
-- =============================================================================

CREATE TABLE IF NOT EXISTS guardrail_configurations (
    institution_id      UUID NOT NULL REFERENCES institutions(id),
    version             INTEGER NOT NULL,
    last_modified_by    UUID NOT NULL REFERENCES users(id),
    last_modified_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason_for_change   TEXT,
    category_rules      JSONB NOT NULL,
    PRIMARY KEY (institution_id, version)
);

-- =============================================================================
-- 4.7 Reports  (report_templates before reports; guardrail_evaluations after reports)
-- =============================================================================

CREATE TABLE IF NOT EXISTS report_templates (
    id          UUID NOT NULL,
    version     INTEGER NOT NULL,
    locale      TEXT NOT NULL DEFAULT 'en',
    definition  JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, version)
);

CREATE TABLE IF NOT EXISTS reports (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id              UUID NOT NULL REFERENCES students(id),
    class_id                UUID NOT NULL REFERENCES classes(id),
    term_id                 UUID NOT NULL REFERENCES terms(id),
    calculated_grade_id     UUID NOT NULL REFERENCES calculated_grades(id),
    report_template_id      UUID NOT NULL,
    report_template_version INTEGER NOT NULL,
    sections_generated      TEXT[] NOT NULL,
    sections_templated      TEXT[] NOT NULL,
    content_snapshot        JSONB NOT NULL,
    teacher_note            TEXT,
    status                  TEXT NOT NULL CHECK (status IN
                                ('generated','pending_approval','held_guardrail','approved','distributed','needs_revision')),
    approved_by             UUID REFERENCES users(id),
    approved_at             TIMESTAMPTZ,
    generated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    correlation_id          UUID NOT NULL,
    FOREIGN KEY (report_template_id, report_template_version) REFERENCES report_templates(id, version)
);

CREATE TABLE IF NOT EXISTS guardrail_evaluations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id           UUID REFERENCES reports(id),
    category_id         TEXT NOT NULL CHECK (category_id IN
                            ('CONSEQUENTIAL_BOUNDARY','STATISTICAL_SHIFT','FIRST_TIME_ACTION',
                             'NOVEL_RECIPIENT','POLICY_CHANGE_IMPACT','ROUTINE')),
    threshold_parameters JSONB,
    evaluation_result   TEXT NOT NULL CHECK (evaluation_result IN ('proceed','held','escalated')),
    triggering_condition TEXT,
    evaluated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS override_decisions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    guardrail_evaluation_id UUID NOT NULL REFERENCES guardrail_evaluations(id),
    decision_type           TEXT NOT NULL CHECK (decision_type IN
                                ('explicitApproval','autoProceedOnWindowExpiry','held','rejected')),
    approver_user_id        UUID REFERENCES users(id),
    window_configured       INTERVAL,
    decided_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (decision_type <> 'autoProceedOnWindowExpiry' OR approver_user_id IS NULL)
);

CREATE TABLE IF NOT EXISTS distribution_log (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id           UUID NOT NULL REFERENCES reports(id),
    channel             TEXT NOT NULL CHECK (channel IN ('email','sms','portal','pdf_export')),
    recipient_guardian_id UUID REFERENCES guardians(id),
    delivery_status     TEXT NOT NULL CHECK (delivery_status IN ('delivered','bounced','undeliverable','pending')),
    provider_confirmation_id TEXT,
    delivered_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============================================================================
-- 4.8 Disputes
-- =============================================================================

CREATE TABLE IF NOT EXISTS disputes (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id           UUID NOT NULL REFERENCES reports(id),
    student_id          UUID NOT NULL REFERENCES students(id),
    raised_by_guardian_id UUID REFERENCES guardians(id),
    raised_by_staff_id  UUID REFERENCES users(id),
    channel             TEXT NOT NULL CHECK (channel IN ('portal','direct_contact','staff_initiated')),
    nature_of_concern   TEXT NOT NULL,
    severity            TEXT CHECK (severity IN ('clarification','data_concern','calculation_process_concern')),
    owner_user_id       UUID REFERENCES users(id),
    status              TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','escalated_operator')),
    resolution_remedy   TEXT CHECK (resolution_remedy IN
                            ('explanation_only','score_correction','report_regeneration',
                             'report_content_correction','process_fix')),
    resolved_at         TIMESTAMPTZ,
    raised_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============================================================================
-- 4.9 Audit Log (append-only)
-- =============================================================================

CREATE TABLE IF NOT EXISTS audit_log (
    record_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    "timestamp"     TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type      TEXT NOT NULL,
    actor_type      TEXT NOT NULL CHECK (actor_type IN ('human','system')),
    actor_id        TEXT NOT NULL,
    actor_role      TEXT,
    institution_id  UUID NOT NULL REFERENCES institutions(id),
    subject_type    TEXT NOT NULL CHECK (subject_type IN
                        ('student','report','gradingPolicy','guardrailConfiguration','syncConnector','auditLog')),
    subject_id      TEXT NOT NULL,
    class_id        UUID,
    result          TEXT NOT NULL CHECK (result IN ('success','failure','held','escalated')),
    detail          JSONB NOT NULL,
    correlation_id  UUID,
    prior_record_id UUID REFERENCES audit_log(record_id)
);

CREATE INDEX IF NOT EXISTS idx_audit_institution_time ON audit_log (institution_id, "timestamp");
CREATE INDEX IF NOT EXISTS idx_audit_subject ON audit_log (subject_type, subject_id);
CREATE INDEX IF NOT EXISTS idx_audit_correlation ON audit_log (correlation_id);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log (actor_id);

-- Enforce true immutability at the database layer (Section 4.9)
-- Revoke UPDATE/DELETE from the application role; grant only INSERT+SELECT
REVOKE UPDATE, DELETE ON audit_log FROM mark_app_role;
GRANT INSERT, SELECT ON audit_log TO mark_app_role;
-- Also revoke from the login user directly (defense in depth — covers direct connection)
REVOKE UPDATE, DELETE ON audit_log FROM mark_app;
GRANT INSERT, SELECT ON audit_log TO mark_app;
-- Ensure future grants on the table don't re-allow UPDATE/DELETE via PUBLIC
REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC;

-- =============================================================================
-- 4.10 Backup & Sync
-- =============================================================================

CREATE TABLE IF NOT EXISTS backup_destinations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    institution_id      UUID NOT NULL REFERENCES institutions(id),
    destination_type    TEXT NOT NULL CHECK (destination_type IN ('second_on_site_device','blind_offsite_relay')),
    configured_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_verified_at    TIMESTAMPTZ,
    last_backup_at      TIMESTAMPTZ,
    last_backup_status  TEXT CHECK (last_backup_status IN ('success','failed','overdue'))
);

CREATE TABLE IF NOT EXISTS sync_queue (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payload_ciphertext BYTEA NOT NULL,
    origin_device_id UUID REFERENCES devices(id),
    lamport_clock   BIGINT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','sent','acknowledged','failed')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_attempt_at TIMESTAMPTZ,
    retry_count     INTEGER NOT NULL DEFAULT 0
);
