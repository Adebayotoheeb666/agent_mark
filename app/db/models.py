"""SQLAlchemy models — mirrors Node Architecture & Database Schema Sections 4.2–4.10.

This file is the canonical ORM view of the schema. The Alembic migration
(migrations/versions/001_n1_schema_foundation.py) applies the raw SQL from
migrations/001_n1_schema_foundation.sql so the ORM and the DB stay in sync.
Keeping both is intentional for N1's "schema diff against spec" test.
"""

import uuid
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Interval,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


# --- 4.2 / 4.3 ---

class Institution(Base):
    __tablename__ = "institutions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(Text, nullable=False)
    letterhead_logo: Mapped[bytes | None] = mapped_column(BYTEA)
    primary_locale: Mapped[str] = mapped_column(Text, nullable=False, server_default="en")
    node_public_key: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Term(Base):
    __tablename__ = "terms"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    label: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[Date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Date] = mapped_column(Date, nullable=False)


class Student(Base):
    __tablename__ = "students"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("institutions.id"), nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    external_ref_id: Mapped[str | None] = mapped_column(Text)
    date_enrolled: Mapped[Date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Class(Base):
    __tablename__ = "classes"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("institutions.id"), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    term_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("terms.id"), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("institutions.id"), nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text, unique=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deactivated_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("role IN ('teacher','administrator','advisor','compliance_officer')", name="ck_users_role"),)


class Guardian(Base):
    __tablename__ = "guardians"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    sms_opt_in: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    relationship: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ClassEnrollment(Base):
    __tablename__ = "class_enrollments"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("classes.id"), nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False)
    __table_args__ = (UniqueConstraint("class_id", "student_id", name="uq_class_enrollments"),)


class UserClassScope(Base):
    __tablename__ = "user_class_scopes"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("classes.id"), nullable=False)
    can_finalize: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    __table_args__ = (UniqueConstraint("user_id", "class_id", name="uq_user_class_scopes"),)


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    public_key: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    device_label: Mapped[str | None] = mapped_column(Text)
    enrolled_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    revoked_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(Text)


# --- 4.4 Grading Policy ---

class GradingPolicy(Base):
    __tablename__ = "grading_policies"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("institutions.id"), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    status: Mapped[str] = mapped_column(Text, nullable=False)
    change_summary: Mapped[str | None] = mapped_column(Text)
    categories: Mapped[dict] = mapped_column(JSONB, nullable=False)
    grade_scale: Mapped[dict] = mapped_column(JSONB, nullable=False)
    special_rules: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    __table_args__ = (
        CheckConstraint("status IN ('draft','active','archived')", name="ck_grading_policies_status"),
    )
    # Composite PK (id, version) — SQLAlchemy needs both marked as PK via __table_args__ override:
    # We re-declare id as PK as well via table args hack; simpler: mark id primary_key=True via column above + version.
    # But to get composite PK we need to set primary_key on both. Fixup:
GradingPolicy.__table__.c.id.primary_key = True  # type: ignore[attr-defined]


class GradingPolicyApplicability(Base):
    __tablename__ = "grading_policy_applicability"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    policy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    policy_version: Mapped[int] = mapped_column(nullable=False)
    class_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("classes.id"))
    subject_wide: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    subject: Mapped[str | None] = mapped_column(Text)
    term_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("terms.id"), nullable=False)
    effective_date: Mapped[Date] = mapped_column(Date, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["policy_id", "policy_version"], ["grading_policies.id", "grading_policies.version"]),
        UniqueConstraint("class_id", "term_id", name="uq_policy_applicability_class_term"),
    )


class Assessment(Base):
    __tablename__ = "assessments"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("classes.id"), nullable=False)
    category_id: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    max_score: Mapped[float] = mapped_column(Numeric, nullable=False)
    min_score: Mapped[float] = mapped_column(Numeric, nullable=False, server_default="0")
    due_date: Mapped[Date | None] = mapped_column(Date)
    external_ref_id: Mapped[str | None] = mapped_column(Text)


# --- 4.5 Scores ---

class RawScore(Base):
    __tablename__ = "raw_scores"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False)
    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("assessments.id"), nullable=False)
    source_system_id: Mapped[str] = mapped_column(Text, nullable=False)
    raw_score: Mapped[float | None] = mapped_column(Numeric)
    confidence_score: Mapped[float | None] = mapped_column(Numeric)
    entered_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    source_timestamp: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    eligible_for_purge_after: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))


class Anomaly(Base):
    __tablename__ = "anomalies"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    raw_score_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("raw_scores.id"))
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False)
    anomaly_type: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False)
    flagged_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    resolution: Mapped[str | None] = mapped_column(Text)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("anomaly_type IN ('missingScore','statisticalOutlier','dataEntryRangeError','duplicateSubmission')", name="ck_anomalies_type"),
        CheckConstraint("severity IN ('yellow','orange','red')", name="ck_anomalies_severity"),
        CheckConstraint("resolution IN ('confirmedCorrect','corrected','escalated') OR resolution IS NULL", name="ck_anomalies_resolution"),
    )


class CalculatedGrade(Base):
    __tablename__ = "calculated_grades"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("classes.id"), nullable=False)
    term_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("terms.id"), nullable=False)
    grading_policy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    grading_policy_version: Mapped[int] = mapped_column(nullable=False)
    category_inputs: Mapped[list] = mapped_column(JSONB, nullable=False)
    final_score: Mapped[float] = mapped_column(Numeric, nullable=False)
    final_grade_label: Mapped[str] = mapped_column(Text, nullable=False)
    calculated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(["grading_policy_id", "grading_policy_version"], ["grading_policies.id", "grading_policies.version"]),
    )


# --- 4.6 Guardrails ---

class GuardrailConfiguration(Base):
    __tablename__ = "guardrail_configurations"
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("institutions.id"), primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    last_modified_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    last_modified_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    reason_for_change: Mapped[str | None] = mapped_column(Text)
    category_rules: Mapped[list] = mapped_column(JSONB, nullable=False)


class ReportTemplate(Base):
    __tablename__ = "report_templates"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    locale: Mapped[str] = mapped_column(Text, nullable=False, server_default="en")
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("classes.id"), nullable=False)
    term_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("terms.id"), nullable=False)
    calculated_grade_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("calculated_grades.id"), nullable=False)
    report_template_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    report_template_version: Mapped[int] = mapped_column(nullable=False)
    sections_generated: Mapped[list] = mapped_column(Text, nullable=False)  # array stored as TEXT[] via SQL; ORM simplified
    sections_templated: Mapped[list] = mapped_column(Text, nullable=False)
    content_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    teacher_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    approved_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    generated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["report_template_id", "report_template_version"], ["report_templates.id", "report_templates.version"]),
        CheckConstraint("status IN ('generated','pending_approval','held_guardrail','approved','distributed','needs_revision')", name="ck_reports_status"),
    )


class GuardrailEvaluation(Base):
    __tablename__ = "guardrail_evaluations"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    report_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("reports.id"))
    category_id: Mapped[str] = mapped_column(Text, nullable=False)
    threshold_parameters: Mapped[dict | None] = mapped_column(JSONB)
    evaluation_result: Mapped[str] = mapped_column(Text, nullable=False)
    triggering_condition: Mapped[str | None] = mapped_column(Text)
    evaluated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint("category_id IN ('CONSEQUENTIAL_BOUNDARY','STATISTICAL_SHIFT','FIRST_TIME_ACTION','NOVEL_RECIPIENT','POLICY_CHANGE_IMPACT','ROUTINE')", name="ck_guardrail_category"),
        CheckConstraint("evaluation_result IN ('proceed','held','escalated')", name="ck_guardrail_result"),
    )


class OverrideDecision(Base):
    __tablename__ = "override_decisions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    guardrail_evaluation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("guardrail_evaluations.id"), nullable=False)
    decision_type: Mapped[str] = mapped_column(Text, nullable=False)
    approver_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    window_configured: Mapped[Interval | None] = mapped_column(Interval)
    decided_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint("decision_type IN ('explicitApproval','autoProceedOnWindowExpiry','held','rejected')", name="ck_override_type"),
        CheckConstraint("decision_type <> 'autoProceedOnWindowExpiry' OR approver_user_id IS NULL", name="ck_override_approver_null"),
    )


class DistributionLog(Base):
    __tablename__ = "distribution_log"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("reports.id"), nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    recipient_guardian_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("guardians.id"))
    delivery_status: Mapped[str] = mapped_column(Text, nullable=False)
    provider_confirmation_id: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint("channel IN ('email','sms','portal','pdf_export')", name="ck_dist_channel"),
        CheckConstraint("delivery_status IN ('delivered','bounced','undeliverable','pending')", name="ck_dist_status"),
    )


class Dispute(Base):
    __tablename__ = "disputes"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("reports.id"), nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False)
    raised_by_guardian_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("guardians.id"))
    raised_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    nature_of_concern: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str | None] = mapped_column(Text)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    resolution_remedy: Mapped[str | None] = mapped_column(Text)
    raised_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("channel IN ('portal','direct_contact','staff_initiated')", name="ck_disputes_channel"),
        CheckConstraint("severity IN ('clarification','data_concern','calculation_process_concern') OR severity IS NULL", name="ck_disputes_severity"),
        CheckConstraint("status IN ('open','resolved','escalated_operator')", name="ck_disputes_status"),
        CheckConstraint("resolution_remedy IN ('explanation_only','score_correction','report_regeneration','report_content_correction','process_fix') OR resolution_remedy IS NULL", name="ck_disputes_remedy"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"
    record_id: Mapped[uuid.UUID] = mapped_column("record_id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    timestamp: Mapped[DateTime] = mapped_column("timestamp", DateTime(timezone=True), nullable=False, server_default=func.now())
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    actor_role: Mapped[str | None] = mapped_column(Text)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("institutions.id"), nullable=False)
    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[str] = mapped_column(Text, nullable=False)
    class_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    result: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    prior_record_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("audit_log.record_id"))
    __table_args__ = (
        CheckConstraint("actor_type IN ('human','system')", name="ck_audit_actor_type"),
        CheckConstraint("subject_type IN ('student','report','gradingPolicy','guardrailConfiguration','syncConnector','auditLog')", name="ck_audit_subject_type"),
        CheckConstraint("result IN ('success','failure','held','escalated')", name="ck_audit_result"),
        Index("idx_audit_institution_time", "institution_id", "timestamp"),
        Index("idx_audit_subject", "subject_type", "subject_id"),
        Index("idx_audit_correlation", "correlation_id"),
        Index("idx_audit_actor", "actor_id"),
    )


class BackupDestination(Base):
    __tablename__ = "backup_destinations"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("institutions.id"), nullable=False)
    destination_type: Mapped[str] = mapped_column(Text, nullable=False)
    configured_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_verified_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    last_backup_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    last_backup_status: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("destination_type IN ('second_on_site_device','blind_offsite_relay')", name="ck_backup_type"),
        CheckConstraint("last_backup_status IN ('success','failed','overdue') OR last_backup_status IS NULL", name="ck_backup_status"),
    )


class SyncQueue(Base):
    __tablename__ = "sync_queue"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    payload_ciphertext: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    origin_device_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"))
    lamport_clock: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_attempt_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    retry_count: Mapped[int] = mapped_column(nullable=False, server_default="0")
    __table_args__ = (
        CheckConstraint("status IN ('queued','sent','acknowledged','failed')", name="ck_sync_status"),
    )
