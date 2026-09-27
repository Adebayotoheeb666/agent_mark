"""N2 bootstrap safety tests."""

import base64
import uuid

import pytest
from sqlalchemy import func, select

from app.db.models import Device, Institution, User
from app.db.session import SessionLocal
from scripts.n2_bootstrap import bootstrap, decode_key


def valid_key_b64() -> str:
    return base64.b64encode(uuid.uuid4().bytes + uuid.uuid4().bytes[:16]).decode("ascii")


def test_bootstrap_rejects_bad_keys_and_names():
    with pytest.raises(ValueError):
        decode_key("not-base64!!!", "device public key")
    with pytest.raises(ValueError):
        decode_key(base64.b64encode(b"too-short").decode("ascii"), "device public key")
    with pytest.raises(ValueError):
        bootstrap("", valid_key_b64(), "Admin", valid_key_b64())


def test_bootstrap_refuses_after_users_exist():
    with SessionLocal() as db:
        temp_user = User(
            institution_id=uuid.uuid4(),
            full_name="N2 Bootstrap Guard",
            email=f"n2-bootstrap-guard-{uuid.uuid4().hex[:8]}@example-school.local",
            role="administrator",
            active=True,
        )
        # The institution FK requires a real institution row.
        temp_institution = Institution(
            name=f"N2 Bootstrap Guard {uuid.uuid4().hex[:8]}",
            primary_locale="en",
            node_public_key=uuid.uuid4().bytes + uuid.uuid4().bytes[:16],
        )
        db.add(temp_institution)
        db.flush()
        temp_user.institution_id = temp_institution.id
        db.add(temp_user)
        db.commit()
        try:
            with pytest.raises(RuntimeError):
                bootstrap("Another School", valid_key_b64(), "Admin", valid_key_b64())
        finally:
            # No ORM relationships are declared between these tables, so the
            # unit of work cannot order the deletes itself: remove the child
            # row first and flush before deleting the parent institution.
            db.delete(temp_user)
            db.flush()
            db.delete(temp_institution)
            db.commit()


def test_bootstrap_success_when_no_users_exist():
    with SessionLocal() as db:
        existing = int(db.scalar(select(func.count()).select_from(User)) or 0)
    if existing > 0:
        pytest.skip("Bootstrap success requires an empty user table; runbook covers the first-bootstrap path.")
    suffix = uuid.uuid4().hex[:8]
    result = bootstrap(
        institution_name=f"N2 Bootstrap School {suffix}",
        node_public_key_base64=valid_key_b64(),
        admin_name="N2 Bootstrap Admin",
        admin_email=f"n2-bootstrap-admin-{suffix}@example-school.local",
        device_label="Bootstrap workstation",
        device_public_key_base64=valid_key_b64(),
    )
    try:
        assert uuid.UUID(result["institution_id"])
        assert uuid.UUID(result["user_id"])
        assert uuid.UUID(result["device_id"])
    finally:
        with SessionLocal() as db:
            # Same child-before-parent ordering note as above.
            db.delete(db.get(Device, uuid.UUID(result["device_id"])))
            db.flush()
            db.delete(db.get(User, uuid.UUID(result["user_id"])))
            db.flush()
            db.delete(db.get(Institution, uuid.UUID(result["institution_id"])))
            db.commit()
