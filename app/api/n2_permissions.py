"""N2 role, institution, and class-scope authorization."""

import uuid

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.n2_auth import AuthContext, n2_error
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

TEACHER = "teacher"
ADMINISTRATOR = "administrator"
ADVISOR = "advisor"
COMPLIANCE_OFFICER = "compliance_officer"

READ_ROLES = (ADMINISTRATOR, COMPLIANCE_OFFICER, TEACHER, ADVISOR)
ACADEMIC_WRITE_ROLES = (ADMINISTRATOR, TEACHER)


def ensure_role(ctx: AuthContext, *roles: str, action: str) -> None:
    if ctx.user.role not in roles:
        n2_error(
            status.HTTP_403_FORBIDDEN,
            "forbidden",
            f"The {ctx.user.role} role may not {action}.",
            "Ask an administrator to perform this action or change the assignment.",
        )


def ensure_same_institution(ctx: AuthContext, institution_id: uuid.UUID, resource: str) -> None:
    if ctx.user.institution_id != institution_id:
        n2_error(
            status.HTTP_403_FORBIDDEN,
            "institution_mismatch",
            f"This {resource} belongs to another institution.",
            "Use an identity enrolled in the same institution.",
        )


def active_administrator_count(
    db: Session, institution_id: uuid.UUID, exclude_user_id: uuid.UUID | None = None
) -> int:
    stmt = (
        select(func.count())
        .select_from(User)
        .where(
            User.institution_id == institution_id,
            User.role == ADMINISTRATOR,
            User.active.is_(True),
        )
    )
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    return int(db.scalar(stmt) or 0)


def ensure_administrator_change_allowed(
    db: Session, target: User, new_role: str | None, new_active: bool | None
) -> None:
    role = new_role if new_role is not None else target.role
    active = new_active if new_active is not None else target.active
    removes_admin = target.role == ADMINISTRATOR and target.active and (
        role != ADMINISTRATOR or not active
    )
    if removes_admin and active_administrator_count(db, target.institution_id, target.id) == 0:
        n2_error(
            status.HTTP_409_CONFLICT,
            "conflict",
            "This institution must retain at least one active administrator.",
            "Create or activate another administrator before changing this user.",
        )


def scoped_class_ids(db: Session, user_id: uuid.UUID) -> set[uuid.UUID]:
    return set(
        db.scalars(select(UserClassScope.class_id).where(UserClassScope.user_id == user_id)).all()
    )


def get_or_404(db: Session, model, object_id: uuid.UUID, resource: str):
    obj = db.get(model, object_id)
    if obj is None:
        n2_error(
            status.HTTP_404_NOT_FOUND, "not_found", f"{resource} was not found.", "Check the identifier and try again."
        )
    return obj


def require_institution(ctx: AuthContext, institution_id: uuid.UUID, write: bool) -> Institution:
    institution = get_or_404(ctx.db, Institution, institution_id, "Institution")
    ensure_same_institution(ctx, institution.id, "institution")
    if write:
        ensure_role(ctx, ADMINISTRATOR, action="manage institutions")
    elif ctx.user.role not in READ_ROLES:
        n2_error(status.HTTP_403_FORBIDDEN, "forbidden", "This role may not read institutions.", None)
    return institution


def require_user(ctx: AuthContext, user_id: uuid.UUID, write: bool) -> User:
    target = get_or_404(ctx.db, User, user_id, "User")
    if write:
        ensure_role(ctx, ADMINISTRATOR, action="manage users")
        ensure_same_institution(ctx, target.institution_id, "user")
        return target
    if ctx.user.id == target.id:
        return target
    ensure_role(ctx, ADMINISTRATOR, COMPLIANCE_OFFICER, action="read other users")
    ensure_same_institution(ctx, target.institution_id, "user")
    return target


def require_scope_parent(ctx: AuthContext, user_id: uuid.UUID, write: bool) -> User:
    target = get_or_404(ctx.db, User, user_id, "User")
    if write:
        ensure_role(ctx, ADMINISTRATOR, action="manage class scopes")
        ensure_same_institution(ctx, target.institution_id, "user")
        return target
    if ctx.user.id == target.id:
        return target
    ensure_role(ctx, ADMINISTRATOR, COMPLIANCE_OFFICER, action="read class scopes")
    ensure_same_institution(ctx, target.institution_id, "user")
    return target


def require_device_parent(ctx: AuthContext, user_id: uuid.UUID, write: bool) -> User:
    target = get_or_404(ctx.db, User, user_id, "User")
    if write:
        ensure_role(ctx, ADMINISTRATOR, action="manage devices")
        ensure_same_institution(ctx, target.institution_id, "user")
        return target
    if ctx.user.id == target.id:
        return target
    ensure_role(ctx, ADMINISTRATOR, COMPLIANCE_OFFICER, action="read devices")
    ensure_same_institution(ctx, target.institution_id, "user")
    return target


def require_device(ctx: AuthContext, device_id: uuid.UUID, write: bool) -> Device:
    device = get_or_404(ctx.db, Device, device_id, "Device")
    owner = get_or_404(ctx.db, User, device.user_id, "User")
    if write:
        ensure_role(ctx, ADMINISTRATOR, action="manage devices")
        ensure_same_institution(ctx, owner.institution_id, "device")
        return device
    if ctx.user.id == owner.id:
        return device
    ensure_role(ctx, ADMINISTRATOR, COMPLIANCE_OFFICER, action="read devices")
    ensure_same_institution(ctx, owner.institution_id, "device")
    return device


def require_class(ctx: AuthContext, class_id: uuid.UUID, write: bool) -> Class:
    class_obj = get_or_404(ctx.db, Class, class_id, "Class")
    ensure_same_institution(ctx, class_obj.institution_id, "class")
    if ctx.user.role == ADMINISTRATOR:
        return class_obj
    if write:
        ensure_role(ctx, *ACADEMIC_WRITE_ROLES, action="change class academic data")
        if ctx.user.role != TEACHER or class_obj.id not in scoped_class_ids(ctx.db, ctx.user.id):
            n2_error(
                status.HTTP_403_FORBIDDEN,
                "class_out_of_scope",
                "This class is not assigned to the calling teacher.",
                "Ask an administrator to assign the class or use an assigned class.",
            )
        return class_obj
    if ctx.user.role == COMPLIANCE_OFFICER:
        return class_obj
    if class_obj.id not in scoped_class_ids(ctx.db, ctx.user.id):
        n2_error(
            status.HTTP_403_FORBIDDEN,
            "class_out_of_scope",
            "This class is not assigned to the calling user.",
            "Ask an administrator to assign the class or use an assigned class.",
        )
    return class_obj


def student_class_ids(db: Session, student_id: uuid.UUID) -> set[uuid.UUID]:
    return set(
        db.scalars(select(ClassEnrollment.class_id).where(ClassEnrollment.student_id == student_id)).all()
    )


def require_student(ctx: AuthContext, student_id: uuid.UUID, write: bool) -> tuple[Student, set[uuid.UUID]]:
    student = get_or_404(ctx.db, Student, student_id, "Student")
    enrollment_classes = student_class_ids(ctx.db, student.id)
    if ctx.user.role in (ADMINISTRATOR, COMPLIANCE_OFFICER):
        ensure_same_institution(ctx, student.institution_id, "student")
        if write:
            ensure_role(ctx, ADMINISTRATOR, action="change student records")
        return student, enrollment_classes
    assigned = scoped_class_ids(ctx.db, ctx.user.id)
    if not assigned.intersection(enrollment_classes):
        n2_error(
            status.HTTP_403_FORBIDDEN,
            "class_out_of_scope",
            "This student is not enrolled in a class assigned to the calling user.",
            "Ask an administrator to assign the class or use an assigned class.",
        )
    if write:
        ensure_role(ctx, TEACHER, action="change student records")
    return student, enrollment_classes


def require_guardian(ctx: AuthContext, guardian_id: uuid.UUID, write: bool) -> Guardian:
    guardian = get_or_404(ctx.db, Guardian, guardian_id, "Guardian")
    require_student(ctx, guardian.student_id, write=write)
    return guardian


def require_term(ctx: AuthContext, term_id: uuid.UUID, write: bool) -> Term:
    term = get_or_404(ctx.db, Term, term_id, "Term")
    if write:
        ensure_role(ctx, ADMINISTRATOR, action="manage terms")
        return term
    if ctx.user.role in (ADMINISTRATOR, COMPLIANCE_OFFICER):
        return term
    assigned = scoped_class_ids(ctx.db, ctx.user.id)
    term_ids: set[uuid.UUID] = set()
    if assigned:
        term_ids = set(
            ctx.db.scalars(select(Class.term_id).where(Class.id.in_(sorted(assigned)))).all()
        )
    if term.id not in term_ids:
        n2_error(
            status.HTTP_403_FORBIDDEN,
            "class_out_of_scope",
            "This term is not associated with a class assigned to the calling user.",
            "Ask an administrator to assign the class or use an assigned class.",
        )
    return term
