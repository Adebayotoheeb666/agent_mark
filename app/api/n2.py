"""N2 identity, access, and academic-structure API."""

import base64
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.n2_auth import AuthContext, n2_error, require_authenticated_device
from app.api.n2_permissions import (
    ADMINISTRATOR,
    ADVISOR,
    COMPLIANCE_OFFICER,
    READ_ROLES,
    TEACHER,
    ensure_administrator_change_allowed,
    ensure_role,
    ensure_same_institution,
    get_or_404,
    require_class,
    require_device,
    require_device_parent,
    require_guardian,
    require_institution,
    require_scope_parent,
    require_student,
    require_term,
    require_user,
    scoped_class_ids,
    student_class_ids,
)
from app.api.n2_schemas import (
    ClassCreate,
    ClassResponse,
    ClassUpdate,
    DeviceEnroll,
    DeviceResponse,
    DeviceRevokeRequest,
    DeviceUpdate,
    EnrollmentCreate,
    EnrollmentResponse,
    GuardianCreate,
    GuardianResponse,
    GuardianUpdate,
    InstitutionCreate,
    InstitutionResponse,
    InstitutionUpdate,
    Page,
    ScopeCreate,
    ScopeResponse,
    ScopeUpdate,
    StudentCreate,
    StudentResponse,
    StudentUpdate,
    TermCreate,
    TermResponse,
    TermUpdate,
    UserCreate,
    UserResponse,
    UserUpdate,
)
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

router = APIRouter(prefix="/n2", tags=["n2-identity-access"])
RequestContext = Annotated[AuthContext, Depends(require_authenticated_device)]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_b64(raw: bytes | bytearray | memoryview | None) -> str | None:
    if raw is None:
        return None
    return base64.b64encode(bytes(raw)).decode("ascii")


def commit_or_conflict(ctx: AuthContext, action: str) -> None:
    try:
        ctx.db.commit()
    except IntegrityError:
        ctx.db.rollback()
        n2_error(
            status.HTTP_409_CONFLICT,
            "conflict",
            f"Could not {action} because of a duplicate or conflicting record.",
            "Check unique identifiers and existing assignments, then try again.",
        )


def require_present(payload, *fields: str) -> None:
    for field in fields:
        if field in payload.model_fields_set and getattr(payload, field) is None:
            n2_error(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "invalid_request",
                f"{field} may not be null.",
                "Omit the field to leave it unchanged or supply a value.",
            )


def paginate_scalars(db, stmt, limit: int, offset: int):
    total = int(db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)
    items = list(db.scalars(stmt.limit(limit).offset(offset)).all())
    return items, total


def institution_response(obj: Institution) -> InstitutionResponse:
    return InstitutionResponse(
        id=obj.id,
        name=obj.name,
        primary_locale=obj.primary_locale,
        node_public_key_base64=to_b64(obj.node_public_key) or "",
        has_letterhead_logo=obj.letterhead_logo is not None,
        created_at=obj.created_at,
    )


def user_response(obj: User) -> UserResponse:
    return UserResponse(
        id=obj.id,
        institution_id=obj.institution_id,
        full_name=obj.full_name,
        email=obj.email,
        role=obj.role,
        active=obj.active,
        created_at=obj.created_at,
        deactivated_at=obj.deactivated_at,
    )


def scope_response(obj: UserClassScope) -> ScopeResponse:
    return ScopeResponse(id=obj.id, user_id=obj.user_id, class_id=obj.class_id, can_finalize=obj.can_finalize)


def device_response(obj: Device) -> DeviceResponse:
    return DeviceResponse(
        id=obj.id,
        user_id=obj.user_id,
        public_key_base64=to_b64(obj.public_key) or "",
        device_label=obj.device_label,
        enrolled_at=obj.enrolled_at,
        revoked_at=obj.revoked_at,
        revoked_reason=obj.revoked_reason,
    )


def student_response(db, obj: Student) -> StudentResponse:
    return StudentResponse(
        id=obj.id,
        institution_id=obj.institution_id,
        full_name=obj.full_name,
        external_ref_id=obj.external_ref_id,
        date_enrolled=obj.date_enrolled,
        active=obj.active,
        created_at=obj.created_at,
        class_ids=sorted(student_class_ids(db, obj.id)),
    )


def email_taken(db, email: str | None, exclude_user_id: uuid.UUID | None = None) -> bool:
    if email is None:
        return False
    stmt = select(User.id).where(User.email == email)
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    return db.scalar(stmt) is not None


def public_key_taken(db, public_key: bytes) -> bool:
    return db.scalar(select(Device.id).where(Device.public_key == public_key)) is not None


def scope_taken(db, user_id: uuid.UUID, class_id: uuid.UUID, exclude_scope_id=None) -> bool:
    stmt = select(UserClassScope.id).where(
        UserClassScope.user_id == user_id, UserClassScope.class_id == class_id
    )
    if exclude_scope_id is not None:
        stmt = stmt.where(UserClassScope.id != exclude_scope_id)
    return db.scalar(stmt) is not None


def enrollment_taken(db, class_id: uuid.UUID, student_id: uuid.UUID) -> bool:
    return (
        db.scalar(
            select(ClassEnrollment.id).where(
                ClassEnrollment.class_id == class_id, ClassEnrollment.student_id == student_id
            )
        )
        is not None
    )


# --- Institutions ---


@router.post("/institutions", response_model=InstitutionResponse, status_code=status.HTTP_201_CREATED)
def create_institution(payload: InstitutionCreate, ctx: RequestContext):
    ensure_role(ctx, ADMINISTRATOR, action="create institutions")
    institution = Institution(
        name=payload.name,
        primary_locale=payload.primary_locale,
        node_public_key=bytes(payload.node_public_key),
        letterhead_logo=bytes(payload.letterhead_logo) if payload.letterhead_logo is not None else None,
    )
    ctx.db.add(institution)
    commit_or_conflict(ctx, "create this institution")
    ctx.db.refresh(institution)
    return institution_response(institution)


@router.get("/institutions", response_model=Page[InstitutionResponse])
def list_institutions(
    ctx: RequestContext,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    if ctx.user.role not in READ_ROLES:
        n2_error(status.HTTP_403_FORBIDDEN, "forbidden", "This role may not read institutions.", None)
    stmt = (
        select(Institution)
        .where(Institution.id == ctx.user.institution_id)
        .order_by(Institution.name, Institution.id)
    )
    items, total = paginate_scalars(ctx.db, stmt, limit, offset)
    return {"items": [institution_response(item) for item in items], "limit": limit, "offset": offset, "total": total}


@router.get("/institutions/{institution_id}", response_model=InstitutionResponse)
def get_institution(institution_id: uuid.UUID, ctx: RequestContext):
    return institution_response(require_institution(ctx, institution_id, write=False))


@router.put("/institutions/{institution_id}", response_model=InstitutionResponse)
def update_institution(institution_id: uuid.UUID, payload: InstitutionUpdate, ctx: RequestContext):
    institution = require_institution(ctx, institution_id, write=True)
    require_present(payload, "name", "primary_locale")
    fields = payload.model_fields_set
    if "name" in fields:
        institution.name = payload.name
    if "primary_locale" in fields:
        institution.primary_locale = payload.primary_locale
    if "letterhead_logo" in fields:
        institution.letterhead_logo = bytes(payload.letterhead_logo) if payload.letterhead_logo is not None else None
    commit_or_conflict(ctx, "update this institution")
    ctx.db.refresh(institution)
    return institution_response(institution)


# --- Users ---


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, ctx: RequestContext):
    ensure_role(ctx, ADMINISTRATOR, action="manage users")
    ensure_same_institution(ctx, payload.institution_id, "user")
    if email_taken(ctx.db, payload.email):
        n2_error(status.HTTP_409_CONFLICT, "conflict", "This email is already used by another user.", "Use a different email address.")
    user = User(
        institution_id=payload.institution_id,
        full_name=payload.full_name,
        email=payload.email,
        role=payload.role,
        active=payload.active,
        deactivated_at=None if payload.active else utcnow(),
    )
    ctx.db.add(user)
    commit_or_conflict(ctx, "create this user")
    ctx.db.refresh(user)
    return user_response(user)


@router.get("/users", response_model=Page[UserResponse])
def list_users(
    ctx: RequestContext,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    if ctx.user.role in (ADMINISTRATOR, COMPLIANCE_OFFICER):
        stmt = (
            select(User)
            .where(User.institution_id == ctx.user.institution_id)
            .order_by(User.full_name, User.id)
        )
    elif ctx.user.role in (TEACHER, ADVISOR):
        stmt = select(User).where(User.id == ctx.user.id)
    else:
        n2_error(status.HTTP_403_FORBIDDEN, "forbidden", "This role may not read users.", None)
    items, total = paginate_scalars(ctx.db, stmt, limit, offset)
    return {"items": [user_response(item) for item in items], "limit": limit, "offset": offset, "total": total}


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(user_id: uuid.UUID, ctx: RequestContext):
    return user_response(require_user(ctx, user_id, write=False))


@router.put("/users/{user_id}", response_model=UserResponse)
def update_user(user_id: uuid.UUID, payload: UserUpdate, ctx: RequestContext):
    user = require_user(ctx, user_id, write=True)
    require_present(payload, "full_name", "role", "active")
    fields = payload.model_fields_set
    if "email" in fields and email_taken(ctx.db, payload.email, exclude_user_id=user.id):
        n2_error(status.HTTP_409_CONFLICT, "conflict", "This email is already used by another user.", "Use a different email address.")
    ensure_administrator_change_allowed(ctx.db, user, payload.role if "role" in fields else None, payload.active if "active" in fields else None)
    if "full_name" in fields:
        user.full_name = payload.full_name
    if "email" in fields:
        user.email = payload.email
    if "role" in fields:
        user.role = payload.role
    if "active" in fields:
        if user.active and payload.active is False:
            user.deactivated_at = utcnow()
        elif not user.active and payload.active is True:
            user.deactivated_at = None
        user.active = payload.active
    commit_or_conflict(ctx, "update this user")
    ctx.db.refresh(user)
    return user_response(user)


# --- Class scopes ---


@router.get("/users/{user_id}/scopes", response_model=Page[ScopeResponse])
def list_scopes(
    user_id: uuid.UUID,
    ctx: RequestContext,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    require_scope_parent(ctx, user_id, write=False)
    stmt = (
        select(UserClassScope)
        .where(UserClassScope.user_id == user_id)
        .order_by(UserClassScope.class_id, UserClassScope.id)
    )
    items, total = paginate_scalars(ctx.db, stmt, limit, offset)
    return {"items": [scope_response(item) for item in items], "limit": limit, "offset": offset, "total": total}


@router.post("/users/{user_id}/scopes", response_model=ScopeResponse, status_code=status.HTTP_201_CREATED)
def create_scope(user_id: uuid.UUID, payload: ScopeCreate, ctx: RequestContext):
    scope_user = require_scope_parent(ctx, user_id, write=True)
    class_obj = get_or_404(ctx.db, Class, payload.class_id, "Class")
    ensure_same_institution(ctx, scope_user.institution_id, "user")
    ensure_same_institution(ctx, class_obj.institution_id, "class")
    if scope_user.institution_id != class_obj.institution_id:
        n2_error(status.HTTP_403_FORBIDDEN, "institution_mismatch", "The user and class belong to different institutions.", "Assign a class from the user's institution.")
    if scope_taken(ctx.db, scope_user.id, class_obj.id):
        n2_error(status.HTTP_409_CONFLICT, "conflict", "This class is already assigned to this user.", "Update the existing assignment instead.")
    scope = UserClassScope(user_id=scope_user.id, class_id=class_obj.id, can_finalize=payload.can_finalize)
    ctx.db.add(scope)
    commit_or_conflict(ctx, "assign this class")
    ctx.db.refresh(scope)
    return scope_response(scope)


@router.put("/users/{user_id}/scopes/{scope_id}", response_model=ScopeResponse)
def update_scope(user_id: uuid.UUID, scope_id: uuid.UUID, payload: ScopeUpdate, ctx: RequestContext):
    require_scope_parent(ctx, user_id, write=True)
    scope = get_or_404(ctx.db, UserClassScope, scope_id, "Class scope")
    if scope.user_id != user_id:
        n2_error(status.HTTP_404_NOT_FOUND, "not_found", "Class scope was not found for this user.", "Check the user and scope identifiers.")
    scope.can_finalize = payload.can_finalize
    commit_or_conflict(ctx, "update this class assignment")
    ctx.db.refresh(scope)
    return scope_response(scope)


@router.delete("/users/{user_id}/scopes/{scope_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scope(user_id: uuid.UUID, scope_id: uuid.UUID, ctx: RequestContext):
    require_scope_parent(ctx, user_id, write=True)
    scope = get_or_404(ctx.db, UserClassScope, scope_id, "Class scope")
    if scope.user_id != user_id:
        n2_error(status.HTTP_404_NOT_FOUND, "not_found", "Class scope was not found for this user.", "Check the user and scope identifiers.")
    ctx.db.delete(scope)
    commit_or_conflict(ctx, "remove this class assignment")
    return None


# --- Devices ---


@router.post("/devices", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
def enroll_device(payload: DeviceEnroll, ctx: RequestContext):
    owner = require_device_parent(ctx, payload.user_id, write=True)
    public_key = bytes(payload.public_key)
    if public_key_taken(ctx.db, public_key):
        n2_error(status.HTTP_409_CONFLICT, "conflict", "This device public key is already enrolled.", "Use the existing device record or enroll a newly generated key.")
    device = Device(user_id=owner.id, public_key=public_key, device_label=payload.device_label)
    ctx.db.add(device)
    commit_or_conflict(ctx, "enroll this device")
    ctx.db.refresh(device)
    return device_response(device)


@router.get("/devices", response_model=Page[DeviceResponse])
def list_devices(
    ctx: RequestContext,
    user_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    if user_id is not None:
        owner = require_device_parent(ctx, user_id, write=False)
        stmt = select(Device).where(Device.user_id == owner.id).order_by(Device.enrolled_at, Device.id)
    elif ctx.user.role in (ADMINISTRATOR, COMPLIANCE_OFFICER):
        stmt = (
            select(Device)
            .join(User, Device.user_id == User.id)
            .where(User.institution_id == ctx.user.institution_id)
            .order_by(Device.enrolled_at, Device.id)
        )
    elif ctx.user.role in (TEACHER, ADVISOR):
        stmt = (
            select(Device)
            .where(Device.user_id == ctx.user.id)
            .order_by(Device.enrolled_at, Device.id)
        )
    else:
        n2_error(status.HTTP_403_FORBIDDEN, "forbidden", "This role may not read devices.", None)
    items, total = paginate_scalars(ctx.db, stmt, limit, offset)
    return {"items": [device_response(item) for item in items], "limit": limit, "offset": offset, "total": total}


@router.get("/devices/{device_id}", response_model=DeviceResponse)
def get_device(device_id: uuid.UUID, ctx: RequestContext):
    return device_response(require_device(ctx, device_id, write=False))


@router.put("/devices/{device_id}", response_model=DeviceResponse)
def update_device(device_id: uuid.UUID, payload: DeviceUpdate, ctx: RequestContext):
    device = require_device(ctx, device_id, write=True)
    if "device_label" in payload.model_fields_set:
        device.device_label = payload.device_label
    commit_or_conflict(ctx, "update this device")
    ctx.db.refresh(device)
    return device_response(device)


@router.post("/devices/{device_id}/revoke", response_model=DeviceResponse)
def revoke_device(device_id: uuid.UUID, payload: DeviceRevokeRequest, ctx: RequestContext):
    device = require_device(ctx, device_id, write=True)
    if device.revoked_at is not None:
        n2_error(status.HTTP_409_CONFLICT, "device_already_revoked", "This device has already been revoked.", "Enroll a replacement device if access is still required.")
    device.revoked_at = utcnow()
    device.revoked_reason = payload.reason
    commit_or_conflict(ctx, "revoke this device")
    ctx.db.refresh(device)
    return device_response(device)


# --- Terms ---


@router.post("/terms", response_model=TermResponse, status_code=status.HTTP_201_CREATED)
def create_term(payload: TermCreate, ctx: RequestContext):
    ensure_role(ctx, ADMINISTRATOR, action="manage terms")
    term = Term(label=payload.label, start_date=payload.start_date, end_date=payload.end_date)
    ctx.db.add(term)
    commit_or_conflict(ctx, "create this term")
    ctx.db.refresh(term)
    return term


@router.get("/terms", response_model=Page[TermResponse])
def list_terms(
    ctx: RequestContext,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    if ctx.user.role in (ADMINISTRATOR, COMPLIANCE_OFFICER):
        stmt = select(Term).order_by(Term.start_date, Term.id)
    elif ctx.user.role in (TEACHER, ADVISOR):
        assigned = scoped_class_ids(ctx.db, ctx.user.id)
        if not assigned:
            return {"items": [], "limit": limit, "offset": offset, "total": 0}
        stmt = (
            select(Term)
            .join(Class, Class.term_id == Term.id)
            .where(Class.id.in_(sorted(assigned)))
            .distinct()
            .order_by(Term.start_date, Term.id)
        )
    else:
        n2_error(status.HTTP_403_FORBIDDEN, "forbidden", "This role may not read terms.", None)
    items, total = paginate_scalars(ctx.db, stmt, limit, offset)
    return {"items": items, "limit": limit, "offset": offset, "total": total}


@router.get("/terms/{term_id}", response_model=TermResponse)
def get_term(term_id: uuid.UUID, ctx: RequestContext):
    return require_term(ctx, term_id, write=False)


@router.put("/terms/{term_id}", response_model=TermResponse)
def update_term(term_id: uuid.UUID, payload: TermUpdate, ctx: RequestContext):
    term = require_term(ctx, term_id, write=True)
    require_present(payload, "label", "start_date", "end_date")
    fields = payload.model_fields_set
    start_date = payload.start_date if "start_date" in fields else term.start_date
    end_date = payload.end_date if "end_date" in fields else term.end_date
    if end_date < start_date:
        n2_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "conflict", "The term end date must be on or after the start date.", "Correct the term dates and try again.")
    if "label" in fields:
        term.label = payload.label
    if "start_date" in fields:
        term.start_date = payload.start_date
    if "end_date" in fields:
        term.end_date = payload.end_date
    commit_or_conflict(ctx, "update this term")
    ctx.db.refresh(term)
    return term


# --- Classes ---


@router.post("/classes", response_model=ClassResponse, status_code=status.HTTP_201_CREATED)
def create_class(payload: ClassCreate, ctx: RequestContext):
    ensure_role(ctx, ADMINISTRATOR, action="manage classes")
    ensure_same_institution(ctx, payload.institution_id, "class")
    get_or_404(ctx.db, Term, payload.term_id, "Term")
    class_obj = Class(
        institution_id=payload.institution_id,
        label=payload.label,
        subject=payload.subject,
        term_id=payload.term_id,
    )
    ctx.db.add(class_obj)
    commit_or_conflict(ctx, "create this class")
    ctx.db.refresh(class_obj)
    return class_obj


@router.get("/classes", response_model=Page[ClassResponse])
def list_classes(
    ctx: RequestContext,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    if ctx.user.role in (ADMINISTRATOR, COMPLIANCE_OFFICER):
        stmt = (
            select(Class)
            .where(Class.institution_id == ctx.user.institution_id)
            .order_by(Class.label, Class.id)
        )
    elif ctx.user.role in (TEACHER, ADVISOR):
        assigned = scoped_class_ids(ctx.db, ctx.user.id)
        if not assigned:
            return {"items": [], "limit": limit, "offset": offset, "total": 0}
        stmt = (
            select(Class)
            .where(Class.id.in_(sorted(assigned)))
            .order_by(Class.label, Class.id)
        )
    else:
        n2_error(status.HTTP_403_FORBIDDEN, "forbidden", "This role may not read classes.", None)
    items, total = paginate_scalars(ctx.db, stmt, limit, offset)
    return {"items": items, "limit": limit, "offset": offset, "total": total}


@router.get("/classes/{class_id}", response_model=ClassResponse)
def get_class(class_id: uuid.UUID, ctx: RequestContext):
    return require_class(ctx, class_id, write=False)


@router.put("/classes/{class_id}", response_model=ClassResponse)
def update_class(class_id: uuid.UUID, payload: ClassUpdate, ctx: RequestContext):
    ensure_role(ctx, ADMINISTRATOR, action="manage classes")
    class_obj = require_class(ctx, class_id, write=False)
    require_present(payload, "label", "subject", "term_id")
    fields = payload.model_fields_set
    if "term_id" in fields:
        get_or_404(ctx.db, Term, payload.term_id, "Term")
        class_obj.term_id = payload.term_id
    if "label" in fields:
        class_obj.label = payload.label
    if "subject" in fields:
        class_obj.subject = payload.subject
    commit_or_conflict(ctx, "update this class")
    ctx.db.refresh(class_obj)
    return class_obj


# --- Students and enrollments ---


def student_list_stmt(class_id: uuid.UUID | None):
    stmt = (
        select(Student)
        .join(ClassEnrollment, ClassEnrollment.student_id == Student.id)
        .where(ClassEnrollment.class_id == class_id)
        .order_by(Student.full_name, Student.id)
    )
    return stmt


@router.get("/classes/{class_id}/students", response_model=Page[StudentResponse])
def list_class_students(
    class_id: uuid.UUID,
    ctx: RequestContext,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    class_obj = require_class(ctx, class_id, write=False)
    items, total = paginate_scalars(ctx.db, student_list_stmt(class_obj.id), limit, offset)
    return {
        "items": [student_response(ctx.db, item) for item in items],
        "limit": limit,
        "offset": offset,
        "total": total,
    }


@router.post("/classes/{class_id}/students", response_model=StudentResponse, status_code=status.HTTP_201_CREATED)
def create_class_student(class_id: uuid.UUID, payload: StudentCreate, ctx: RequestContext):
    class_obj = require_class(ctx, class_id, write=True)
    student = Student(
        institution_id=class_obj.institution_id,
        full_name=payload.full_name,
        external_ref_id=payload.external_ref_id,
        date_enrolled=payload.date_enrolled,
        active=payload.active,
    )
    ctx.db.add(student)
    ctx.db.flush()
    ctx.db.add(ClassEnrollment(class_id=class_obj.id, student_id=student.id))
    commit_or_conflict(ctx, "create this student")
    ctx.db.refresh(student)
    return student_response(ctx.db, student)


@router.get("/students", response_model=Page[StudentResponse])
def list_students(
    ctx: RequestContext,
    class_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    if class_id is not None:
        class_obj = require_class(ctx, class_id, write=False)
        items, total = paginate_scalars(ctx.db, student_list_stmt(class_obj.id), limit, offset)
    elif ctx.user.role in (ADMINISTRATOR, COMPLIANCE_OFFICER):
        stmt = (
            select(Student)
            .where(Student.institution_id == ctx.user.institution_id)
            .order_by(Student.full_name, Student.id)
        )
        items, total = paginate_scalars(ctx.db, stmt, limit, offset)
    else:
        n2_error(
            status.HTTP_403_FORBIDDEN,
            "class_out_of_scope",
            "Student queries must specify an assigned class.",
            "Repeat the request with an assigned class_id.",
        )
    return {
        "items": [student_response(ctx.db, item) for item in items],
        "limit": limit,
        "offset": offset,
        "total": total,
    }


@router.get("/students/{student_id}", response_model=StudentResponse)
def get_student(student_id: uuid.UUID, ctx: RequestContext):
    student, _ = require_student(ctx, student_id, write=False)
    return student_response(ctx.db, student)


@router.put("/students/{student_id}", response_model=StudentResponse)
def update_student(student_id: uuid.UUID, payload: StudentUpdate, ctx: RequestContext):
    student, _ = require_student(ctx, student_id, write=True)
    require_present(payload, "full_name", "active")
    fields = payload.model_fields_set
    if "full_name" in fields:
        student.full_name = payload.full_name
    if "external_ref_id" in fields:
        student.external_ref_id = payload.external_ref_id
    if "date_enrolled" in fields:
        student.date_enrolled = payload.date_enrolled
    if "active" in fields:
        student.active = payload.active
    commit_or_conflict(ctx, "update this student")
    ctx.db.refresh(student)
    return student_response(ctx.db, student)


@router.get("/classes/{class_id}/enrollments", response_model=Page[EnrollmentResponse])
def list_enrollments(
    class_id: uuid.UUID,
    ctx: RequestContext,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    class_obj = require_class(ctx, class_id, write=False)
    stmt = (
        select(ClassEnrollment)
        .where(ClassEnrollment.class_id == class_obj.id)
        .order_by(ClassEnrollment.student_id, ClassEnrollment.id)
    )
    items, total = paginate_scalars(ctx.db, stmt, limit, offset)
    return {"items": items, "limit": limit, "offset": offset, "total": total}


@router.post("/classes/{class_id}/enrollments", response_model=EnrollmentResponse, status_code=status.HTTP_201_CREATED)
def create_enrollment(class_id: uuid.UUID, payload: EnrollmentCreate, ctx: RequestContext):
    class_obj = require_class(ctx, class_id, write=True)
    student = get_or_404(ctx.db, Student, payload.student_id, "Student")
    ensure_same_institution(ctx, student.institution_id, "student")
    if student.institution_id != class_obj.institution_id:
        n2_error(status.HTTP_403_FORBIDDEN, "institution_mismatch", "The student and class belong to different institutions.", "Enroll a student from the class institution.")
    if enrollment_taken(ctx.db, class_obj.id, student.id):
        n2_error(status.HTTP_409_CONFLICT, "conflict", "This student is already enrolled in this class.", "Use the existing enrollment.")
    enrollment = ClassEnrollment(class_id=class_obj.id, student_id=student.id)
    ctx.db.add(enrollment)
    commit_or_conflict(ctx, "enroll this student")
    ctx.db.refresh(enrollment)
    return enrollment


@router.delete("/classes/{class_id}/enrollments/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_enrollment(class_id: uuid.UUID, student_id: uuid.UUID, ctx: RequestContext):
    class_obj = require_class(ctx, class_id, write=True)
    enrollment = ctx.db.scalar(
        select(ClassEnrollment).where(
            ClassEnrollment.class_id == class_obj.id, ClassEnrollment.student_id == student_id
        )
    )
    if enrollment is None:
        n2_error(status.HTTP_404_NOT_FOUND, "not_found", "Enrollment was not found.", "Check the class and student identifiers.")
    ctx.db.delete(enrollment)
    commit_or_conflict(ctx, "remove this enrollment")
    return None


# --- Guardians ---


@router.get("/students/{student_id}/guardians", response_model=Page[GuardianResponse])
def list_guardians(
    student_id: uuid.UUID,
    ctx: RequestContext,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    student, _ = require_student(ctx, student_id, write=False)
    stmt = (
        select(Guardian)
        .where(Guardian.student_id == student.id)
        .order_by(Guardian.full_name, Guardian.id)
    )
    items, total = paginate_scalars(ctx.db, stmt, limit, offset)
    return {"items": items, "limit": limit, "offset": offset, "total": total}


@router.post("/students/{student_id}/guardians", response_model=GuardianResponse, status_code=status.HTTP_201_CREATED)
def create_guardian(student_id: uuid.UUID, payload: GuardianCreate, ctx: RequestContext):
    student, _ = require_student(ctx, student_id, write=True)
    guardian = Guardian(
        student_id=student.id,
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        sms_opt_in=payload.sms_opt_in,
        relationship=payload.relationship,
    )
    ctx.db.add(guardian)
    commit_or_conflict(ctx, "create this guardian")
    ctx.db.refresh(guardian)
    return guardian


@router.get("/guardians/{guardian_id}", response_model=GuardianResponse)
def get_guardian(guardian_id: uuid.UUID, ctx: RequestContext):
    return require_guardian(ctx, guardian_id, write=False)


@router.put("/guardians/{guardian_id}", response_model=GuardianResponse)
def update_guardian(guardian_id: uuid.UUID, payload: GuardianUpdate, ctx: RequestContext):
    guardian = require_guardian(ctx, guardian_id, write=True)
    require_present(payload, "full_name", "sms_opt_in")
    fields = payload.model_fields_set
    if "full_name" in fields:
        guardian.full_name = payload.full_name
    if "email" in fields:
        guardian.email = payload.email
    if "phone" in fields:
        guardian.phone = payload.phone
    if "sms_opt_in" in fields:
        guardian.sms_opt_in = payload.sms_opt_in
    if "relationship" in fields:
        guardian.relationship = payload.relationship
    commit_or_conflict(ctx, "update this guardian")
    ctx.db.refresh(guardian)
    return guardian
