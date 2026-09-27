"""N2 request/response schemas for identity, access, and academic structure."""

import base64
import binascii
from datetime import date, datetime
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Role = Literal["teacher", "administrator", "advisor", "compliance_officer"]
T = TypeVar("T")


def _decode_base64(value: str | bytes | None, field: str, max_bytes: int) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        raw = value
    else:
        text = value.strip()
        if text == "":
            return None
        try:
            raw = base64.b64decode(text, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError(f"{field} must be base64")
    if len(raw) > max_bytes:
        raise ValueError(f"{field} is too large")
    return raw


def _decode_key(value: str | bytes | None, field: str) -> bytes:
    raw = _decode_base64(value, field, 256)
    if raw is None or len(raw) != 32:
        raise ValueError(f"{field} must be a 32-byte base64 public key")
    return raw


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text if text != "" else None


def _normalize_email(value: str | None) -> str | None:
    text = _normalize_optional_text(value)
    if text is None:
        return None
    if "@" not in text or "." not in text.rsplit("@", 1)[-1]:
        raise ValueError("email must be a valid address")
    return text


class InstitutionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    primary_locale: str = Field(default="en", min_length=1, max_length=16)
    node_public_key: bytes = Field()
    letterhead_logo: bytes | None = Field(default=None)

    @field_validator("node_public_key", mode="before")
    @classmethod
    def _decode_node_key(cls, value: str | bytes | None) -> bytes:
        return _decode_key(value, "node_public_key")

    @field_validator("letterhead_logo", mode="before")
    @classmethod
    def _decode_logo(cls, value: str | bytes | None) -> bytes | None:
        return _decode_base64(value, "letterhead_logo", 5_000_000)


class InstitutionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    primary_locale: str | None = Field(default=None, min_length=1, max_length=16)
    letterhead_logo: bytes | None = Field(default=None)

    @field_validator("letterhead_logo", mode="before")
    @classmethod
    def _decode_logo(cls, value: str | bytes | None) -> bytes | None:
        return _decode_base64(value, "letterhead_logo", 5_000_000)


class InstitutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    primary_locale: str
    node_public_key_base64: str
    has_letterhead_logo: bool
    created_at: datetime


class UserCreate(BaseModel):
    institution_id: UUID
    full_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=254)
    role: Role
    active: bool = Field(default=True)

    @field_validator("email", mode="before")
    @classmethod
    def _normalize_user_email(cls, value: str | None) -> str | None:
        return _normalize_email(value)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=254)
    role: Role | None = Field(default=None)
    active: bool | None = Field(default=None)

    @field_validator("email", mode="before")
    @classmethod
    def _normalize_user_email(cls, value: str | None) -> str | None:
        return _normalize_email(value)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    institution_id: UUID
    full_name: str
    email: str | None
    role: str
    active: bool
    created_at: datetime
    deactivated_at: datetime | None


class ScopeCreate(BaseModel):
    class_id: UUID
    can_finalize: bool = Field(default=False)


class ScopeUpdate(BaseModel):
    can_finalize: bool


class ScopeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    class_id: UUID
    can_finalize: bool


class DeviceEnroll(BaseModel):
    user_id: UUID
    public_key: bytes = Field()
    device_label: str | None = Field(default=None, max_length=200)

    @field_validator("device_label", mode="before")
    @classmethod
    def _normalize_label(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("public_key", mode="before")
    @classmethod
    def _decode_public_key(cls, value: str | bytes | None) -> bytes:
        return _decode_key(value, "public_key")


class DeviceUpdate(BaseModel):
    device_label: str | None = Field(default=None, max_length=200)

    @field_validator("device_label", mode="before")
    @classmethod
    def _normalize_label(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)


class DeviceRevokeRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def _normalize_reason(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)


class DeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    public_key_base64: str
    device_label: str | None
    enrolled_at: datetime
    revoked_at: datetime | None
    revoked_reason: str | None


class TermCreate(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _check_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class TermUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    start_date: date | None = Field(default=None)
    end_date: date | None = Field(default=None)

    @model_validator(mode="after")
    def _check_dates(self):
        if self.start_date is not None and self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class TermResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    label: str
    start_date: date
    end_date: date


class ClassCreate(BaseModel):
    institution_id: UUID
    label: str = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=1, max_length=200)
    term_id: UUID


class ClassUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    subject: str | None = Field(default=None, min_length=1, max_length=200)
    term_id: UUID | None = Field(default=None)


class ClassResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    institution_id: UUID
    label: str
    subject: str
    term_id: UUID
    created_at: datetime


class StudentCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    external_ref_id: str | None = Field(default=None, max_length=200)
    date_enrolled: date | None = Field(default=None)
    active: bool = Field(default=True)


class StudentUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    external_ref_id: str | None = Field(default=None, max_length=200)
    date_enrolled: date | None = Field(default=None)
    active: bool | None = Field(default=None)


class StudentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    institution_id: UUID
    full_name: str
    external_ref_id: str | None
    date_enrolled: date | None
    active: bool
    created_at: datetime
    class_ids: list[UUID] = Field(default_factory=list)


class GuardianCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=64)
    sms_opt_in: bool = Field(default=False)
    relationship: str | None = Field(default=None, max_length=100)

    @field_validator("email", mode="before")
    @classmethod
    def _normalize_guardian_email(cls, value: str | None) -> str | None:
        return _normalize_email(value)

    @field_validator("phone", "relationship", mode="before")
    @classmethod
    def _normalize_guardian_text(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)


class GuardianUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=64)
    sms_opt_in: bool | None = Field(default=None)
    relationship: str | None = Field(default=None, max_length=100)

    @field_validator("email", mode="before")
    @classmethod
    def _normalize_guardian_email(cls, value: str | None) -> str | None:
        return _normalize_email(value)

    @field_validator("phone", "relationship", mode="before")
    @classmethod
    def _normalize_guardian_text(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)


class GuardianResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    student_id: UUID
    full_name: str
    email: str | None
    phone: str | None
    sms_opt_in: bool
    relationship: str | None
    created_at: datetime


class EnrollmentCreate(BaseModel):
    student_id: UUID


class EnrollmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    class_id: UUID
    student_id: UUID


class Page(BaseModel, Generic[T]):
    items: list[T]
    limit: int
    offset: int
    total: int
