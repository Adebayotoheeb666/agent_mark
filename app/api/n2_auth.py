"""N2 device-signed request authentication.

Devices hold Ed25519 private keys. The node stores only public keys in
`devices.public_key`. Authentication and revocation are checked before role,
scope, or business logic.
"""

import base64
import binascii
import hashlib
import time
import uuid
from dataclasses import dataclass
from typing import NoReturn
from urllib.parse import urlencode

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.models import Device, User
from app.db.session import get_db

USER_HEADER = "x-user-id"
DEVICE_HEADER = "x-device-id"
TIMESTAMP_HEADER = "x-request-timestamp"
SIGNATURE_HEADER = "x-request-signature"
CLOCK_SKEW_SECONDS = 300


def n2_error(status_code: int, code: str, message: str, action: str | None = None) -> NoReturn:
    detail: dict[str, str] = {"code": code, "message": message}
    if action is not None:
        detail["action"] = action
    raise HTTPException(status_code=status_code, detail=detail)


def canonical_query_string(request: Request) -> str:
    items = [(key, value) for key, value in request.query_params.multi_items()]
    return urlencode(sorted(items), doseq=True)


def canonical_request_bytes(request: Request, timestamp: str, body: bytes) -> bytes:
    body_digest = hashlib.sha256(body or b"").hexdigest()
    text = "\n".join(
        (
            timestamp,
            request.method.upper(),
            request.url.path,
            canonical_query_string(request),
            body_digest,
        )
    )
    return text.encode("utf-8")


def _parse_uuid(value: str | None, field: str) -> uuid.UUID:
    try:
        if value is None:
            raise ValueError("missing")
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        n2_error(
            status.HTTP_401_UNAUTHORIZED,
            "authentication_failed",
            f"Missing or invalid {field}.",
            "Sign the request with an enrolled user and device.",
        )


@dataclass
class AuthContext:
    user: User
    device: Device
    db: Session


async def require_authenticated_device(
    request: Request, db: Session = Depends(get_db)
) -> AuthContext:
    user_id = _parse_uuid(request.headers.get(USER_HEADER), "X-User-Id")
    device_id = _parse_uuid(request.headers.get(DEVICE_HEADER), "X-Device-Id")

    user = db.get(User, user_id)
    device = db.get(Device, device_id)
    if user is None or device is None or not user.active or device.user_id != user.id:
        n2_error(
            status.HTTP_401_UNAUTHORIZED,
            "authentication_failed",
            "Unknown, inactive, or mismatched user/device identity.",
            "Use a currently enrolled device belonging to an active user.",
        )

    if device.revoked_at is not None:
        n2_error(
            status.HTTP_403_FORBIDDEN,
            "device_revoked",
            "This device has been revoked and can no longer access the node.",
            "Contact an administrator to enroll a replacement device.",
        )

    timestamp_text = request.headers.get(TIMESTAMP_HEADER)
    try:
        timestamp_value = int(timestamp_text or "")
    except (TypeError, ValueError):
        n2_error(
            status.HTTP_401_UNAUTHORIZED,
            "stale_request",
            "Missing or invalid request timestamp.",
            "Send the current Unix time and sign it with the device key.",
        )
    if abs(time.time() - timestamp_value) > CLOCK_SKEW_SECONDS:
        n2_error(
            status.HTTP_401_UNAUTHORIZED,
            "stale_request",
            "The signed request timestamp is outside the accepted window.",
            "Synchronize the device clock and sign a fresh request.",
        )

    signature_text = request.headers.get(SIGNATURE_HEADER)
    try:
        signature = base64.b64decode(signature_text or "", validate=True)
    except (binascii.Error, ValueError):
        n2_error(
            status.HTTP_401_UNAUTHORIZED,
            "invalid_signature",
            "The request signature is not valid base64.",
            "Sign the canonical request with the enrolled device key.",
        )

    try:
        public_key = Ed25519PublicKey.from_public_bytes(bytes(device.public_key))
    except Exception:
        n2_error(
            status.HTTP_401_UNAUTHORIZED,
            "invalid_signature",
            "The enrolled device key cannot be used for verification.",
            "Ask an administrator to re-enroll this device.",
        )

    body = await request.body()
    try:
        public_key.verify(signature, canonical_request_bytes(request, timestamp_text or "", body))
    except InvalidSignature:
        n2_error(
            status.HTTP_401_UNAUTHORIZED,
            "invalid_signature",
            "The device signature does not match this request.",
            "Sign the exact method, path, query, timestamp, and body.",
        )
    except Exception:
        n2_error(
            status.HTTP_401_UNAUTHORIZED,
            "invalid_signature",
            "The device signature could not be verified.",
            "Sign the exact method, path, query, timestamp, and body.",
        )

    return AuthContext(user=user, device=device, db=db)
