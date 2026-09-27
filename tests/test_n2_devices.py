"""N2 device enrollment, revocation, and revoked-device rejection tests."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from tests.n2_helpers import (
    API_PREFIX,
    N2Identity,
    clear_n2_domain_tables,
    create_identity,
    create_institution,
    create_user,
    generate_keypair,
    signed_request,
)

client = TestClient(app)


@pytest.fixture(scope="module")
def fixtures():
    with SessionLocal() as db:
        institution = create_institution(db)
        admin = create_user(db, institution.id, "administrator")
        admin_auth = create_identity(db, admin)
        teacher = create_user(db, institution.id, "teacher")
        teacher_auth = create_identity(db, teacher)
        data = {
            "institution": institution.id,
            "admin": admin_auth,
            "teacher": teacher_auth,
        }
        yield data
    # Teardown: same house rule as test_n2_access_matrix — leave no rows
    # behind so repeat full-suite runs stay clean.
    with SessionLocal() as db:
        clear_n2_domain_tables(db)


def test_admin_enrolls_lists_and_updates_device(fixtures):
    admin = fixtures["admin"]
    _, public_b64 = generate_keypair()
    r = signed_request(
        client,
        "POST",
        f"{API_PREFIX}/devices",
        admin,
        json_body={
            "user_id": str(fixtures["teacher"].user_id),
            "public_key": public_b64,
            "device_label": "N2 Enrollment Test Device",
        },
    )
    assert r.status_code == 201, r.text
    device = r.json()
    assert device["public_key_base64"] == public_b64
    assert device["revoked_at"] is None

    r = signed_request(client, "PUT", f"{API_PREFIX}/devices/{device['id']}", admin, json_body={"device_label": "Updated label"})
    assert r.status_code == 200, r.text
    assert r.json()["device_label"] == "Updated label"

    r = signed_request(client, "GET", f"{API_PREFIX}/devices", admin, params={"user_id": str(fixtures["teacher"].user_id)})
    assert r.status_code == 200, r.text
    assert device["id"] in {item["id"] for item in r.json()["items"]}


def test_duplicate_device_key_rejected(fixtures):
    admin = fixtures["admin"]
    _, public_b64 = generate_keypair()
    body = {"user_id": str(fixtures["teacher"].user_id), "public_key": public_b64}
    r = signed_request(client, "POST", f"{API_PREFIX}/devices", admin, json_body=body)
    assert r.status_code == 201, r.text
    r = signed_request(client, "POST", f"{API_PREFIX}/devices", admin, json_body=body)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "conflict"


def test_non_admin_cannot_enroll_or_revoke(fixtures):
    teacher = fixtures["teacher"]
    _, public_b64 = generate_keypair()
    r = signed_request(
        client,
        "POST",
        f"{API_PREFIX}/devices",
        teacher,
        json_body={"user_id": str(teacher.user_id), "public_key": public_b64},
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "forbidden"

    r = signed_request(
        client, "POST", f"{API_PREFIX}/devices/{teacher.device_id}/revoke", teacher, json_body={"reason": "lost"}
    )
    assert r.status_code == 403, r.text


def test_revoked_device_rejection_is_distinguishable(fixtures):
    admin = fixtures["admin"]
    with SessionLocal() as db:
        doomed_teacher = create_user(db, fixtures["institution"], "teacher")
        doomed_user_id = doomed_teacher.id
    doomed_private, doomed_public_b64 = generate_keypair()
    r = signed_request(
        client,
        "POST",
        f"{API_PREFIX}/devices",
        admin,
        json_body={"user_id": str(doomed_user_id), "public_key": doomed_public_b64, "device_label": "Doomed device"},
    )
    assert r.status_code == 201, r.text
    device_id = r.json()["id"]
    doomed_auth = N2Identity(user_id=doomed_user_id, device_id=uuid.UUID(device_id), private_key=doomed_private)

    r = signed_request(client, "GET", f"{API_PREFIX}/users/{doomed_user_id}", doomed_auth)
    assert r.status_code == 200, r.text

    r = signed_request(
        client, "POST", f"{API_PREFIX}/devices/{device_id}/revoke", admin, json_body={"reason": "lost device"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["revoked_at"] is not None
    assert r.json()["revoked_reason"] == "lost device"

    r = signed_request(client, "GET", f"{API_PREFIX}/users/{doomed_user_id}", doomed_auth)
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "device_revoked"

    unknown_auth = N2Identity(user_id=uuid.uuid4(), device_id=uuid.uuid4(), private_key=doomed_private)
    r = signed_request(client, "GET", f"{API_PREFIX}/users/{doomed_user_id}", unknown_auth)
    assert r.status_code == 401, r.text
    assert r.json()["detail"]["code"] == "authentication_failed"

    r = signed_request(
        client, "POST", f"{API_PREFIX}/devices/{device_id}/revoke", admin, json_body={"reason": "again"}
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "device_already_revoked"
