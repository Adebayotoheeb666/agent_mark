"""N2 role/scope matrix tests, including negative server-side rejections."""

import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from tests.n2_helpers import (
    API_PREFIX,
    N2Identity,
    assign_class,
    clear_n2_domain_tables,
    create_class,
    create_guardian,
    create_identity,
    create_institution,
    create_student,
    create_term,
    create_user,
    enroll,
    signed_request,
)

client = TestClient(app)


@pytest.fixture(scope="module")
def fixtures():
    with SessionLocal() as db:
        institution_a = create_institution(db)
        admin_a = create_user(db, institution_a.id, "administrator")
        admin_auth_a = create_identity(db, admin_a)
        compliance_a = create_user(db, institution_a.id, "compliance_officer")
        compliance_auth_a = create_identity(db, compliance_a)
        teacher_a = create_user(db, institution_a.id, "teacher")
        teacher_auth_a = create_identity(db, teacher_a)
        finalizer_a = create_user(db, institution_a.id, "teacher")
        finalizer_auth_a = create_identity(db, finalizer_a)
        advisor_a = create_user(db, institution_a.id, "advisor")
        advisor_auth_a = create_identity(db, advisor_a)

        term_a = create_term(db)
        assigned_class = create_class(db, institution_a.id, term_a.id)
        unassigned_class = create_class(db, institution_a.id, term_a.id)
        assign_class(db, teacher_a.id, assigned_class.id, can_finalize=False)
        assign_class(db, finalizer_a.id, assigned_class.id, can_finalize=True)
        assign_class(db, advisor_a.id, assigned_class.id)

        assigned_student = create_student(db, institution_a.id)
        enroll(db, assigned_class.id, assigned_student.id)
        unassigned_student = create_student(db, institution_a.id)
        enroll(db, unassigned_class.id, unassigned_student.id)
        unenrolled_student = create_student(db, institution_a.id)
        guardian = create_guardian(db, assigned_student.id)

        institution_b = create_institution(db)
        admin_b = create_user(db, institution_b.id, "administrator")
        admin_auth_b = create_identity(db, admin_b)
        term_b = create_term(db)
        class_b = create_class(db, institution_b.id, term_b.id)
        student_b = create_student(db, institution_b.id)
        enroll(db, class_b.id, student_b.id)

        institution_c = create_institution(db)
        admin_c1 = create_user(db, institution_c.id, "administrator")
        admin_auth_c1 = create_identity(db, admin_c1)
        admin_c2 = create_user(db, institution_c.id, "administrator")
        admin_c2_id = admin_c2.id

        inactive_teacher = create_user(db, institution_a.id, "teacher", active=False)
        inactive_auth = create_identity(db, inactive_teacher)

        data = {
            "institution_a": institution_a.id,
            "admin_a": admin_auth_a,
            "compliance_a": compliance_auth_a,
            "teacher_a": teacher_auth_a,
            "finalizer_a": finalizer_auth_a,
            "advisor_a": advisor_auth_a,
            "term_a": term_a.id,
            "assigned_class": assigned_class.id,
            "unassigned_class": unassigned_class.id,
            "assigned_student": assigned_student.id,
            "unassigned_student": unassigned_student.id,
            "unenrolled_student": unenrolled_student.id,
            "guardian": guardian.id,
            "institution_b": institution_b.id,
            "admin_b": admin_auth_b,
            "class_b": class_b.id,
            "student_b": student_b.id,
            "admin_c1": admin_auth_c1,
            "admin_c2": admin_c2_id,
            "inactive": inactive_auth,
        }
        yield data
    # Teardown: leave no rows behind so later modules (notably the bootstrap
    # happy-path test, which requires an empty user table) see a clean slate.
    with SessionLocal() as db:
        clear_n2_domain_tables(db)


def test_admin_full_identity_management(fixtures):
    admin = fixtures["admin_a"]
    term_id = fixtures["term_a"]

    r = signed_request(
        client,
        "POST",
        f"{API_PREFIX}/classes",
        admin,
        json_body={
            "institution_id": str(fixtures["institution_a"]),
            "label": "N2 Admin Class",
            "subject": "Science",
            "term_id": str(term_id),
        },
    )
    assert r.status_code == 201, r.text
    class_id = r.json()["id"]

    r = signed_request(
        client,
        "POST",
        f"{API_PREFIX}/users",
        admin,
        json_body={
            "institution_id": str(fixtures["institution_a"]),
            "full_name": "N2 Managed Teacher",
            "email": f"n2-managed-{uuid.uuid4().hex[:8]}@example-school.local",
            "role": "teacher",
            "active": True,
        },
    )
    assert r.status_code == 201, r.text
    user_id = r.json()["id"]

    r = signed_request(
        client, "POST", f"{API_PREFIX}/users/{user_id}/scopes", admin, json_body={"class_id": class_id, "can_finalize": False}
    )
    assert r.status_code == 201, r.text

    import base64

    raw = base64.b64encode(uuid.uuid4().bytes + uuid.uuid4().bytes[:16]).decode("ascii")
    assert len(base64.b64decode(raw)) == 32
    r = signed_request(
        client,
        "POST",
        f"{API_PREFIX}/devices",
        admin,
        json_body={"user_id": user_id, "public_key": raw, "device_label": "Managed device"},
    )
    assert r.status_code == 201, r.text

    r = signed_request(client, "PUT", f"{API_PREFIX}/users/{user_id}", admin, json_body={"active": False})
    assert r.status_code == 200, r.text
    assert r.json()["active"] is False
    assert r.json()["deactivated_at"] is not None


def test_teacher_assigned_class_access(fixtures):
    teacher = fixtures["teacher_a"]
    assigned_class = fixtures["assigned_class"]
    unassigned_class = fixtures["unassigned_class"]

    r = signed_request(client, "GET", f"{API_PREFIX}/classes", teacher)
    assert r.status_code == 200, r.text
    class_ids = {item["id"] for item in r.json()["items"]}
    assert str(assigned_class) in class_ids
    assert str(unassigned_class) not in class_ids

    r = signed_request(client, "GET", f"{API_PREFIX}/classes/{unassigned_class}", teacher)
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "class_out_of_scope"

    r = signed_request(client, "GET", f"{API_PREFIX}/classes/{assigned_class}/students", teacher)
    assert r.status_code == 200, r.text
    assert r.json()["total"] >= 1

    r = signed_request(client, "GET", f"{API_PREFIX}/students/{fixtures['unassigned_student']}", teacher)
    assert r.status_code == 403, r.text

    r = signed_request(
        client,
        "POST",
        f"{API_PREFIX}/classes/{assigned_class}/students",
        teacher,
        json_body={"full_name": "N2 Teacher-Created Student"},
    )
    assert r.status_code == 201, r.text
    student_id = r.json()["id"]

    r = signed_request(
        client,
        "POST",
        f"{API_PREFIX}/students/{student_id}/guardians",
        teacher,
        json_body={"full_name": "N2 Teacher-Created Guardian"},
    )
    assert r.status_code == 201, r.text

    r = signed_request(
        client,
        "POST",
        f"{API_PREFIX}/classes/{assigned_class}/enrollments",
        teacher,
        json_body={"student_id": str(fixtures["unenrolled_student"])},
    )
    assert r.status_code == 201, r.text

    r = signed_request(client, "GET", f"{API_PREFIX}/students", teacher)
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "class_out_of_scope"

    forbidden_posts = [
        (
            f"{API_PREFIX}/terms",
            {"label": "N2 Forbidden Term", "start_date": "2026-09-01", "end_date": "2026-12-18"},
        ),
        (
            f"{API_PREFIX}/classes",
            {
                "institution_id": str(fixtures["institution_a"]),
                "label": "N2 Forbidden Class",
                "subject": "Science",
                "term_id": str(fixtures["term_a"]),
            },
        ),
        (
            f"{API_PREFIX}/users",
            {
                "institution_id": str(fixtures["institution_a"]),
                "full_name": "N2 Forbidden User",
                "role": "teacher",
                "active": True,
            },
        ),
        (
            f"{API_PREFIX}/devices",
            {
                "user_id": str(teacher.user_id),
                "public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
                "device_label": "N2 Forbidden Device",
            },
        ),
    ]
    for path, body in forbidden_posts:
        r = signed_request(client, "POST", path, teacher, json_body=body)
        assert r.status_code == 403, (path, r.text)
        assert r.json()["detail"]["code"] == "forbidden"


def test_can_finalize_flag_does_not_change_n2_academic_crud(fixtures):
    finalizer = fixtures["finalizer_a"]
    assigned_class = fixtures["assigned_class"]
    r = signed_request(client, "GET", f"{API_PREFIX}/classes/{assigned_class}/students", finalizer)
    assert r.status_code == 200, r.text
    r = signed_request(
        client,
        "POST",
        f"{API_PREFIX}/classes/{assigned_class}/students",
        finalizer,
        json_body={"full_name": "N2 Finalizer-Created Student"},
    )
    assert r.status_code == 201, r.text


def test_advisor_scoped_read_only(fixtures):
    advisor = fixtures["advisor_a"]
    assigned_student = fixtures["assigned_student"]
    unassigned_student = fixtures["unassigned_student"]

    r = signed_request(client, "GET", f"{API_PREFIX}/students/{assigned_student}", advisor)
    assert r.status_code == 200, r.text
    r = signed_request(client, "GET", f"{API_PREFIX}/students/{unassigned_student}", advisor)
    assert r.status_code == 403, r.text

    r = signed_request(
        client,
        "PUT",
        f"{API_PREFIX}/students/{assigned_student}",
        advisor,
        json_body={"full_name": "N2 Advisor Edit"},
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "forbidden"

    r = signed_request(client, "GET", f"{API_PREFIX}/users", advisor)
    assert r.status_code == 200, r.text
    assert [item["id"] for item in r.json()["items"]] == [str(advisor.user_id)]


def test_compliance_read_only_institution_wide(fixtures):
    compliance = fixtures["compliance_a"]
    checks = [
        ("GET", f"{API_PREFIX}/users", None),
        ("GET", f"{API_PREFIX}/classes", None),
        ("GET", f"{API_PREFIX}/terms", None),
        ("GET", f"{API_PREFIX}/students", None),
        ("GET", f"{API_PREFIX}/students/{fixtures['unassigned_student']}", None),
        ("GET", f"{API_PREFIX}/guardians/{fixtures['guardian']}", None),
    ]
    for method, path, body in checks:
        r = signed_request(client, method, path, compliance, json_body=body)
        assert r.status_code == 200, (method, path, r.text)

    r = signed_request(
        client,
        "PUT",
        f"{API_PREFIX}/students/{fixtures['unassigned_student']}",
        compliance,
        json_body={"full_name": "N2 Compliance Edit"},
    )
    assert r.status_code == 403, r.text


def test_cross_institution_access_denied(fixtures):
    admin_a = fixtures["admin_a"]
    teacher_a = fixtures["teacher_a"]
    compliance_a = fixtures["compliance_a"]

    r = signed_request(client, "GET", f"{API_PREFIX}/classes/{fixtures['class_b']}", admin_a)
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "institution_mismatch"

    r = signed_request(client, "GET", f"{API_PREFIX}/students/{fixtures['student_b']}", teacher_a)
    assert r.status_code == 403, r.text

    r = signed_request(client, "GET", f"{API_PREFIX}/users/{fixtures['admin_b'].user_id}", compliance_a)
    assert r.status_code == 403, r.text


def test_last_active_administrator_is_protected(fixtures):
    admin_c1 = fixtures["admin_c1"]
    admin_c2 = fixtures["admin_c2"]

    r = signed_request(client, "PUT", f"{API_PREFIX}/users/{admin_c2}", admin_c1, json_body={"active": False})
    assert r.status_code == 200, r.text

    r = signed_request(
        client, "PUT", f"{API_PREFIX}/users/{admin_c1.user_id}", admin_c1, json_body={"active": False}
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "conflict"

    r = signed_request(
        client, "PUT", f"{API_PREFIX}/users/{admin_c1.user_id}", admin_c1, json_body={"role": "teacher"}
    )
    assert r.status_code == 409, r.text


def test_authentication_failures_are_generic(fixtures):
    teacher = fixtures["teacher_a"]

    r = client.get(f"{API_PREFIX}/classes")
    assert r.status_code == 401, r.text

    unknown = N2Identity(user_id=uuid.uuid4(), device_id=uuid.uuid4(), private_key=teacher.private_key)
    r = signed_request(client, "GET", f"{API_PREFIX}/classes", unknown)
    assert r.status_code == 401, r.text
    assert r.json()["detail"]["code"] == "authentication_failed"

    r = signed_request(client, "GET", f"{API_PREFIX}/classes", fixtures["inactive"])
    assert r.status_code == 401, r.text

    mismatched = N2Identity(user_id=teacher.user_id, device_id=fixtures["admin_a"].device_id, private_key=fixtures["admin_a"].private_key)
    r = signed_request(client, "GET", f"{API_PREFIX}/classes", mismatched)
    assert r.status_code == 401, r.text

    r = signed_request(client, "GET", f"{API_PREFIX}/classes", teacher, timestamp=int(time.time()) - 10_000)
    assert r.status_code == 401, r.text
    assert r.json()["detail"]["code"] == "stale_request"

    r = client.get(
        f"{API_PREFIX}/classes",
        headers={
            "X-User-Id": str(teacher.user_id),
            "X-Device-Id": str(teacher.device_id),
            "X-Request-Timestamp": str(int(time.time())),
            "X-Request-Signature": "not-base64!!!",
        },
    )
    assert r.status_code == 401, r.text
    assert r.json()["detail"]["code"] == "invalid_signature"
