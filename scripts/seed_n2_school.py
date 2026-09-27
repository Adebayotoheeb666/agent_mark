#!/usr/bin/env python3
"""Seed one realistic full-school N2 dataset for performance verification."""

import argparse
import json
import os
import sys
import uuid
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import func, select

from app.db.models import (
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
from app.db.session import SessionLocal

MARKER = "N2 Performance School"


def get_counts(args=None) -> tuple[int, int, int]:
    students = int(os.getenv("N2_SEED_STUDENTS", "1200" if args is None else args.students))
    classes = int(os.getenv("N2_SEED_CLASSES", "30" if args is None else args.classes))
    teachers = int(os.getenv("N2_SEED_TEACHERS", "30" if args is None else args.teachers))
    if min(students, classes, teachers) <= 0:
        raise ValueError("Seed counts must be positive")
    return students, classes, teachers


def seed_school(db, student_count: int, class_count: int, teacher_count: int) -> dict:
    for institution in db.scalars(select(Institution).where(Institution.name.like(f"{MARKER}%"))).all():
        existing = int(
            db.scalar(select(func.count()).select_from(Student).where(Student.institution_id == institution.id)) or 0
        )
        if existing >= student_count:
            first_class = db.scalar(
                select(Class).where(Class.institution_id == institution.id).order_by(Class.label, Class.id)
            )
            return {
                "institution_id": str(institution.id),
                "first_class_id": str(first_class.id) if first_class is not None else None,
                "reused": True,
            }

    suffix = uuid.uuid4().hex[:8]
    institution = Institution(
        name=f"{MARKER} {suffix}",
        primary_locale="en",
        node_public_key=os.urandom(32),
    )
    db.add(institution)
    db.flush()

    terms = [
        Term(label="2026 Fall Term", start_date=date(2026, 9, 1), end_date=date(2026, 12, 18)),
        Term(label="2027 Spring Term", start_date=date(2027, 1, 11), end_date=date(2027, 4, 30)),
    ]
    db.add_all(terms)
    db.flush()

    class_rows = [
        {
            "id": uuid.uuid4(),
            "institution_id": institution.id,
            "label": f"Grade 9 Section {i + 1:02d}",
            "subject": "Mathematics",
            "term_id": terms[i % len(terms)].id,
        }
        for i in range(class_count)
    ]
    db.bulk_insert_mappings(Class, class_rows)

    teacher_rows = []
    scope_rows = []
    device_rows = []
    for i in range(teacher_count):
        user_id = uuid.uuid4()
        teacher_rows.append(
            {
                "id": user_id,
                "institution_id": institution.id,
                "full_name": f"Performance Teacher {i + 1:03d}",
                "email": f"performance-teacher-{suffix}-{i + 1:03d}@example-school.local",
                "role": "teacher",
                "active": True,
            }
        )
        class_id = class_rows[i % class_count]["id"]
        scope_rows.append({"id": uuid.uuid4(), "user_id": user_id, "class_id": class_id, "can_finalize": i % 5 == 0})
        public_key = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
        device_rows.append(
            {"id": uuid.uuid4(), "user_id": user_id, "public_key": public_key, "device_label": f"Teacher device {i + 1:03d}"}
        )
    db.bulk_insert_mappings(User, teacher_rows)
    db.bulk_insert_mappings(UserClassScope, scope_rows)
    db.bulk_insert_mappings(Device, device_rows)

    student_rows = []
    guardian_rows = []
    enrollment_rows = []
    for i in range(student_count):
        student_id = uuid.uuid4()
        class_id = class_rows[i % class_count]["id"]
        student_rows.append(
            {
                "id": student_id,
                "institution_id": institution.id,
                "full_name": f"Performance Student {i + 1:05d}",
                "external_ref_id": f"n2-perf-{suffix}-{i + 1:05d}",
                "date_enrolled": date(2026, 9, 1),
                "active": True,
            }
        )
        guardian_rows.append(
            {
                "id": uuid.uuid4(),
                "student_id": student_id,
                "full_name": f"Performance Guardian {i + 1:05d}",
                "email": None,
                "phone": None,
                "sms_opt_in": False,
                "relationship": "guardian",
            }
        )
        enrollment_rows.append({"id": uuid.uuid4(), "class_id": class_id, "student_id": student_id})
    db.bulk_insert_mappings(Student, student_rows)
    db.bulk_insert_mappings(Guardian, guardian_rows)
    db.bulk_insert_mappings(ClassEnrollment, enrollment_rows)
    db.commit()

    first_class = db.scalar(
        select(Class).where(Class.institution_id == institution.id).order_by(Class.label, Class.id)
    )
    return {
        "institution_id": str(institution.id),
        "first_class_id": str(first_class.id),
        "reused": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed a realistic N2 school dataset.")
    parser.add_argument("--students", default="1200")
    parser.add_argument("--classes", default="30")
    parser.add_argument("--teachers", default="30")
    args = parser.parse_args(argv)
    try:
        student_count, class_count, teacher_count = get_counts(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    with SessionLocal() as db:
        print(json.dumps(seed_school(db, student_count, class_count, teacher_count), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
