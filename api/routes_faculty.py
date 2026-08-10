"""Group 5 — Faculty API (§7.5).

Source: webapp/routes/faculty.py — ported to JSON API shape.
HOD-only for every route per spec §7.5.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from database import (
    audit, connect, create_user, reset_student_password,
    get_all_role_permissions, update_role_permissions,
    get_user_permissions, update_user_permissions, IntegrityError
)
from sms_app.services.attendance_service import faculty_teaching_hours, subject_faculty_map

from api.deps import CurrentUser, get_current_user
from api.envelope import ApiError, ok

router = APIRouter(prefix="/api/faculty", tags=["faculty"])


def _require_hod(user: CurrentUser):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access required", 403, "FORBIDDEN")


@router.get("")
async def faculty_page(user: CurrentUser = Depends(get_current_user)):
    _require_hod(user)
    hours = faculty_teaching_hours()
    by_subject = subject_faculty_map()
    with connect() as c:
        accounts = c.execute(
            "SELECT id, username, full_name, role, department, designation, email, phone, active, must_change_password, student_roll_no FROM users WHERE role != 'STUDENT' ORDER BY role, username"
        ).fetchall()
    return ok({
        "hours": [dict(h) for h in hours],
        "by_subject": by_subject,
        "accounts": [dict(a) for a in accounts],
        "permissions": get_all_role_permissions(),
    })


@router.get("/permissions")
async def get_permissions(user: CurrentUser = Depends(get_current_user)):
    _require_hod(user)
    return ok({"permissions": get_all_role_permissions()})


class PermissionUpdateBody(BaseModel):
    role: str
    can_view_student_phone: bool = True
    can_edit_students: bool = False
    can_delete_students: bool = False
    can_view_audit_logs: bool = False
    can_view_sms_logs: bool = False
    can_manage_calendar: bool = True
    can_manage_subjects: bool = True


@router.post("/permissions")
async def save_permissions(body: PermissionUpdateBody, user: CurrentUser = Depends(get_current_user)):
    _require_hod(user)
    if body.role not in ("HOD", "FACULTY"):
        raise ApiError("Invalid role specified", 400, "VALIDATION_ERROR")
    update_role_permissions(body.role, body.dict())
    with connect() as c:
        audit(c, user.username, "UPDATE_PERMISSIONS", "role", body.role)
    return ok({"ok": True, "permissions": get_all_role_permissions()})


class UserPermissionUpdateBody(BaseModel):
    can_view_students: bool = True
    can_edit_students: bool = False
    can_delete_students: bool = False
    can_manage_attendance: bool = True
    can_manage_subjects: bool = True
    can_manage_calendar: bool = True
    can_view_sms_logs: bool = False
    can_view_audit_logs: bool = False


@router.get("/accounts/{username}/permissions")
async def get_account_permissions(username: str, user: CurrentUser = Depends(get_current_user)):
    _require_hod(user)
    perms = get_user_permissions(username)
    return ok({"username": username, "permissions": perms})


@router.post("/accounts/{username}/permissions")
async def save_account_permissions(username: str, body: UserPermissionUpdateBody, user: CurrentUser = Depends(get_current_user)):
    _require_hod(user)
    update_user_permissions(username, body.dict())
    with connect() as c:
        audit(c, user.username, "UPDATE_USER_PERMISSIONS", "user", username)
    return ok({"ok": True, "username": username, "permissions": get_user_permissions(username)})


class CreateAccountBody(BaseModel):
    username: str
    full_name: str | None = ""
    password: str
    role: str
    student_roll_no: str | None = ""


@router.post("/create-account", status_code=201)
async def create_account(body: CreateAccountBody, user: CurrentUser = Depends(get_current_user)):
    _require_hod(user)
    try:
        create_user(
            body.username, body.password, body.role,
            (body.full_name or "").strip(), (body.student_roll_no or "").strip() or None,
            user.username,
        )
        with connect() as c:
            new_row = c.execute("SELECT id FROM users WHERE username=? COLLATE NOCASE", (body.username.strip(),)).fetchone()
        return ok({"id": new_row["id"] if new_row else None, "username": body.username.strip()})
    except (ValueError, IntegrityError) as e:
        raise ApiError(str(e), 400, "VALIDATION_ERROR")


@router.post("/accounts/{account_id}/toggle-status")
async def toggle_account_status(account_id: int, user: CurrentUser = Depends(get_current_user)):
    _require_hod(user)
    with connect() as c:
        row = c.execute("SELECT * FROM users WHERE id=?", (account_id,)).fetchone()
        if not row:
            raise ApiError("Account not found", 404, "NOT_FOUND")
        if row["role"] == "HOD" or row["username"] == user.username:
            raise ApiError("HOD / Logged-in accounts cannot be deactivated", 400, "SELF_DEACTIVATE")
        new_active = 0 if row["active"] else 1
        c.execute("UPDATE users SET active=? WHERE id=?", (new_active, account_id))
        audit(c, user.username, "STATUS", "user", f"{row['username']} -> {new_active}")
    return ok({"active": bool(new_active)})


@router.post("/accounts/{account_id}/reset-password")
async def reset_password(account_id: int, user: CurrentUser = Depends(get_current_user)):
    _require_hod(user)
    with connect() as c:
        row = c.execute("SELECT * FROM users WHERE id=?", (account_id,)).fetchone()
    if not row or row["role"] != "STUDENT" or not row["student_roll_no"]:
        raise ApiError("Only linked STUDENT accounts can have their password reset", 400, "VALIDATION_ERROR")
    try:
        username, password = reset_student_password(row["student_roll_no"], user.username)
        return ok({"username": username, "password": password})
    except ValueError as e:
        raise ApiError(str(e), 400, "VALIDATION_ERROR")


@router.delete("/accounts/{account_id}")
async def delete_account(account_id: int, user: CurrentUser = Depends(get_current_user)):
    _require_hod(user)
    with connect() as c:
        row = c.execute("SELECT * FROM users WHERE id=?", (account_id,)).fetchone()
        if not row:
            raise ApiError("Account not found", 404, "NOT_FOUND")
        if row["username"] == user.username or row["username"] == "admin":
            raise ApiError("Logged-in account or primary admin cannot be deleted", 400, "CANNOT_DELETE_ADMIN")
        c.execute("DELETE FROM users WHERE id=?", (account_id,))
        audit(c, user.username, "DELETE", "user", row["username"])
    return ok({"deleted": True, "id": account_id})
