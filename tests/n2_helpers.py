"""Shared N2 test helpers for device-signed API requests and fixtures."""

import base64
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlencode

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import delete, select

from app.db.models import (
    AuditLog,
    Class,
    ClassEnrollment,
    Device,
    Guardian,
    Institution,
    Student,
    Term,
    User,
    UserClassScope,
)

API_PREFIX = "/api/v1/n2"


@dataclass
class N2Identity:
    user_id: uuid.UUID
    device_id: uuid.UUID
    private_key: Ed25519PrivateKey


def generate_keypair() -> tuple[Ed25519PrivateKey, str]:
    private_key = Ed25519PrivateKey.generate()
    public_b64 = base64.b64encode(private_key.public_key().public_bytes_raw()).decode("ascii")
    return private_key, public_b64


def canonical_query(params: dict | None) -> str:
    if not params:
        return ""
    items: list[tuple[str, str]] = []
    for key, value in params.items():
        values = value if isinstance(value, (list, tuple)) else [value]
        for item in values:
            items.append((key, str(item)))
    return urlencode(sorted(items), doseq=True)


def canonical_body(payload) -> bytes:
    if payload is None:
        return b""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def signed_request(client, method: str, path: str, identity: N2Identity, params=None, json_body=None, timestamp=None):
    timestamp_text = str(timestamp if timestamp is not None else int(time.time()))
    query = canonical_query(params)
    body = canonical_body(json_body)
    canonical = "\n".join(
        (timestamp_text, method.upper(), path, query, hashlib.sha256(body).hexdigest())
    ).encode("utf-8")
    signature = base64.b64encode(identity.private_key.sign(canonical)).decode("ascii")
    headers = {
        "X-User-Id": str(identity.user_id),
        "X-Device-Id": str(identity.device_id),
        "X-Request-Timestamp": timestamp_text,
        "X-Request-Signature": signature,
    }
    url = path if not query else f"{path}?{query}"
    if json_body is None:
        return client.request(method, url, content=body, headers=headers)
    headers["Content-Type"] = "application/json"
    return client.request(method, url, content=body, headers=headers)


def unique_suffix() -> str:
    return uuid.uuid4().hex[:8]


def create_institution(db, name: str | None = None) -> Institution:
    institution = Institution(
        name=name or f"N2 Test Institution {unique_suffix()}",
        primary_locale="en",
        node_public_key=os.urandom(32),
    )
    db.add(institution)
    db.commit()
    db.refresh(institution)
    return institution


def create_user(db, institution_id: uuid.UUID, role: str, active: bool = True, email: str | None = None) -> User:
    user = User(
        institution_id=institution_id,
        full_name=f"N2 {role} {unique_suffix()}",
        email=email or f"n2-{role}-{unique_suffix()}@example-school.local",
        role=role,
        active=active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_identity(db, user: User, revoked: bool = False) -> N2Identity:
    private_key, _ = generate_keypair()
    device = Device(
        user_id=user.id,
        public_key=private_key.public_key().public_bytes_raw(),
        device_label=f"{user.role} device {unique_suffix()}",
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    if revoked:
        from datetime import datetime, timezone

        device.revoked_at = datetime.now(timezone.utc)
        device.revoked_reason = "lost device"
        db.commit()
        db.refresh(device)
    return N2Identity(user_id=user.id, device_id=device.id, private_key=private_key)


def create_term(db, label: str | None = None) -> Term:
    term = Term(
        label=label or f"N2 Term {unique_suffix()}",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 12, 18),
    )
    db.add(term)
    db.commit()
    db.refresh(term)
    return term


def create_class(db, institution_id: uuid.UUID, term_id: uuid.UUID, label: str | None = None) -> Class:
    class_obj = Class(
        institution_id=institution_id,
        label=label or f"N2 Class {unique_suffix()}",
        subject="Mathematics",
        term_id=term_id,
    )
    db.add(class_obj)
    db.commit()
    db.refresh(class_obj)
    return class_obj


def assign_class(db, user_id: uuid.UUID, class_id: uuid.UUID, can_finalize: bool = False) -> UserClassScope:
    scope = UserClassScope(user_id=user_id, class_id=class_id, can_finalize=can_finalize)
    db.add(scope)
    db.commit()
    db.refresh(scope)
    return scope


def create_student(db, institution_id: uuid.UUID, name: str | None = None) -> Student:
    student = Student(
        institution_id=institution_id,
        full_name=name or f"N2 Student {unique_suffix()}",
        external_ref_id=f"n2-{unique_suffix()}",
        date_enrolled=date(2026, 9, 1),
        active=True,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def enroll(db, class_id: uuid.UUID, student_id: uuid.UUID) -> ClassEnrollment:
    enrollment = ClassEnrollment(class_id=class_id, student_id=student_id)
    db.add(enrollment)
    db.commit()
    db.refresh(enrollment)
    return enrollment


def create_guardian(db, student_id: uuid.UUID) -> Guardian:
    guardian = Guardian(
        student_id=student_id,
        full_name=f"N2 Guardian {unique_suffix()}",
        email=None,
        phone=None,
        sms_opt_in=False,
        relationship="guardian",
    )
    db.add(guardian)
    db.commit()
    db.refresh(guardian)
    return guardian


def clear_n2_domain_tables(db) -> None:
    """Delete every row created by N2 fixtures/tests, child tables first.

    House rule: every module-scoped N2 fixture tears down with this, so a
    full-suite run never leaks rows into later modules — notably users into
    the bootstrap happy-path test, which requires an empty user table.

    N1's append-only audit_log is never touched; institutions still
    referenced by audit rows are preserved (audit_log.institution_id FK).
    One table per commit: the models declare no ORM relationships, so the
    unit of work cannot order multi-table deletes itself (same cause as the
    test_n2_bootstrap teardown fix).
    """
    for model in (Guardian, ClassEnrollment, UserClassScope, Device, Student, Class, User, Term):
        db.execute(delete(model))
        db.commit()
    audited = select(AuditLog.institution_id).distinct()
    db.execute(delete(Institution).where(Institution.id.not_in(audited)))
    db.commit()
