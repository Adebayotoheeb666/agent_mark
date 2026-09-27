#!/usr/bin/env python3
"""Create the first N2 institution, administrator, and enrolled device.

This trusted local setup operation replaces an unauthenticated HTTP bootstrap
endpoint. Run it on the node itself. It refuses to run after any user exists.
"""

import argparse
import base64
import binascii
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db.models import Device, Institution, User
from app.db.session import SessionLocal


def decode_key(value: str, field: str) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError(f"{field} must be base64")
    if len(raw) != 32:
        raise ValueError(f"{field} must be a 32-byte base64 public key")
    return raw


def bootstrap(
    institution_name: str,
    node_public_key_base64: str,
    admin_name: str,
    device_public_key_base64: str,
    admin_email: str | None = None,
    device_label: str | None = None,
) -> dict[str, str]:
    if not institution_name.strip():
        raise ValueError("institution-name is required")
    if not admin_name.strip():
        raise ValueError("admin-name is required")
    node_public_key = decode_key(node_public_key_base64, "node public key")
    device_public_key = decode_key(device_public_key_base64, "device public key")

    with SessionLocal() as db:
        if db.scalar(select(User.id).limit(1)) is not None:
            raise RuntimeError("Bootstrap is disabled because at least one user already exists.")
        if db.scalar(select(Device.id).where(Device.public_key == device_public_key)) is not None:
            raise RuntimeError("This device public key is already enrolled.")
        if admin_email and db.scalar(select(User.id).where(User.email == admin_email)) is not None:
            raise RuntimeError("This administrator email is already used.")

        institution = Institution(
            name=institution_name.strip(),
            primary_locale="en",
            node_public_key=node_public_key,
        )
        db.add(institution)
        db.flush()
        admin = User(
            institution_id=institution.id,
            full_name=admin_name.strip(),
            email=admin_email,
            role="administrator",
            active=True,
        )
        db.add(admin)
        db.flush()
        device = Device(user_id=admin.id, public_key=device_public_key, device_label=device_label)
        db.add(device)
        db.commit()
        db.refresh(institution)
        db.refresh(admin)
        db.refresh(device)
        return {
            "institution_id": str(institution.id),
            "user_id": str(admin.id),
            "device_id": str(device.id),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap the first N2 administrator and device.")
    parser.add_argument("--institution-name", required=True)
    parser.add_argument("--node-public-key-base64", required=True)
    parser.add_argument("--admin-name", required=True)
    parser.add_argument("--admin-email", default=None)
    parser.add_argument("--device-label", default=None)
    parser.add_argument("--device-public-key-base64", required=True)
    args = parser.parse_args(argv)
    try:
        result = bootstrap(
            institution_name=args.institution_name,
            node_public_key_base64=args.node_public_key_base64,
            admin_name=args.admin_name,
            admin_email=args.admin_email,
            device_label=args.device_label,
            device_public_key_base64=args.device_public_key_base64,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
