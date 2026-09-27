"""N2 realistic-dataset performance test for one full school."""

import math
import os
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import ClassEnrollment, Student
from app.db.session import SessionLocal
from app.main import app
from scripts.seed_n2_school import get_counts, seed_school
from tests.n2_helpers import (
    API_PREFIX,
    assign_class,
    clear_n2_domain_tables,
    create_class,
    create_identity,
    create_term,
    create_user,
    signed_request,
)

client = TestClient(app)


def percentile_ms(samples: list[float], percentile: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index] * 1000.0


@pytest.fixture(scope="module")
def performance_setup():
    student_count, class_count, teacher_count = get_counts()
    with SessionLocal() as db:
        seed = seed_school(db, student_count, class_count, teacher_count)
        institution_id = uuid.UUID(seed["institution_id"])
        first_class_id = uuid.UUID(seed["first_class_id"])
        actual_students = int(
            db.scalar(select(func.count()).select_from(Student).where(Student.institution_id == institution_id)) or 0
        )
        actual_enrollments = int(
            db.scalar(
                select(func.count())
                .select_from(ClassEnrollment)
                .join(Student, ClassEnrollment.student_id == Student.id)
                .where(Student.institution_id == institution_id)
            )
            or 0
        )
        term = create_term(db)
        unassigned_class = create_class(db, institution_id, term.id)
        teacher = create_user(db, institution_id, "teacher")
        assign_class(db, teacher.id, first_class_id)
        auth = create_identity(db, teacher)
        data = {
            "institution": institution_id,
            "first_class": first_class_id,
            "unassigned_class": unassigned_class.id,
            "teacher": auth,
            "expected_students": student_count,
            "expected_per_class": math.ceil(student_count / class_count),
            "actual_students": actual_students,
            "actual_enrollments": actual_enrollments,
        }
        yield data
    # Teardown: same house rule — wipe the seeded school so repeat
    # full-suite runs stay clean.
    with SessionLocal() as db:
        clear_n2_domain_tables(db)


def test_full_school_dataset_and_scoped_query_budgets(performance_setup):
    setup = performance_setup
    assert setup["actual_students"] >= setup["expected_students"]
    assert setup["actual_enrollments"] >= setup["expected_students"]

    read_budget = float(os.getenv("N2_PERF_READ_P95_MS", "1000"))
    write_budget = float(os.getenv("N2_PERF_WRITE_P95_MS", "2000"))
    teacher = setup["teacher"]
    first_class = setup["first_class"]
    unassigned_class = setup["unassigned_class"]

    for _ in range(3):
        r = signed_request(
            client,
            "GET",
            f"{API_PREFIX}/classes/{first_class}/students",
            teacher,
            params={"limit": 500, "offset": 0},
        )
        assert r.status_code == 200, r.text

    read_samples = []
    for _ in range(15):
        started = time.perf_counter()
        r = signed_request(
            client,
            "GET",
            f"{API_PREFIX}/classes/{first_class}/students",
            teacher,
            params={"limit": 500, "offset": 0},
        )
        read_samples.append(time.perf_counter() - started)
        assert r.status_code == 200, r.text
        assert r.json()["total"] >= setup["expected_per_class"]
        assert len(r.json()["items"]) == r.json()["total"]

    denied_samples = []
    for _ in range(15):
        started = time.perf_counter()
        r = signed_request(client, "GET", f"{API_PREFIX}/classes/{unassigned_class}/students", teacher)
        denied_samples.append(time.perf_counter() - started)
        assert r.status_code == 403, r.text

    write_samples = []
    for i in range(12):
        started = time.perf_counter()
        r = signed_request(
            client,
            "POST",
            f"{API_PREFIX}/classes/{first_class}/students",
            teacher,
            json_body={"full_name": f"N2 Performance Probe {uuid.uuid4().hex[:8]} {i}"},
        )
        elapsed = time.perf_counter() - started
        assert r.status_code == 201, r.text
        if i >= 2:
            write_samples.append(elapsed)

    read_p95 = percentile_ms(read_samples, 0.95)
    denied_p95 = percentile_ms(denied_samples, 0.95)
    write_p95 = percentile_ms(write_samples, 0.95)
    assert read_p95 < read_budget, f"scoped read p95 {read_p95:.1f}ms exceeds {read_budget:.1f}ms"
    assert denied_p95 < read_budget, f"denied scoped read p95 {denied_p95:.1f}ms exceeds {read_budget:.1f}ms"
    assert write_p95 < write_budget, f"scoped write p95 {write_p95:.1f}ms exceeds {write_budget:.1f}ms"
