"""Group 6 — Self-service API (§7.6).

Two separate route files in the reference; kept as two router registrations here
(one for HOD/FACULTY account, one for STUDENT profile) per §7.6's explicit
instruction to keep the role split explicit.

Sources: webapp/routes/self_profile.py (HOD/FACULTY)
         webapp/routes/student_self.py (STUDENT)
"""

from datetime import datetime

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel

from database import audit, change_password, connect, validate_staff_profile, validate_student, IntegrityError
from sms_app.services.attendance_service import (
    attendance_pct_band, student_subject_session_history, subject_details,
)
from webapp.photo_upload import PhotoUploadError, save_profile_photo

from api.deps import CurrentUser, get_current_user, get_current_user_allow_pending
from api.envelope import ApiError, ok

router = APIRouter(prefix="/api/me", tags=["me"])

PROFILE_FIELD_SPECS = [
    ("Full Name", "full_name"), ("Department", "department"), ("Designation", "designation"),
    ("Employee ID", "employee_id"), ("Email", "email"), ("Phone", "phone"),
    ("Qualification", "qualification"), ("Date of Joining (YYYY-MM-DD)", "date_of_joining"),
]

SELF_FIELD_SPECS_KEYS = [
    "name", "father_name", "email", "phone", "parent_phone",
    "dob", "category", "gender", "seat_category", "address",
]


# ============================================================
# HOD / FACULTY account routes
# ============================================================

@router.get("/account")
async def my_account(user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "FACULTY"):
        raise ApiError("This route is for HOD and FACULTY only", 403, "FORBIDDEN")
    with connect() as c:
        row = c.execute("SELECT * FROM users WHERE username=?", (user.username,)).fetchone()
    if not row:
        raise ApiError("User record not found", 404, "NOT_FOUND")
    return ok({
        "user": dict(row),
        "specs": [{"label": label, "key": key} for label, key in PROFILE_FIELD_SPECS],
    })


def _clean_str(val: str | None) -> str:
    return (val or "").strip()


class AccountUpdateBody(BaseModel):
    full_name: str | None = ""
    department: str | None = ""
    designation: str | None = ""
    employee_id: str | None = ""
    email: str | None = ""
    phone: str | None = ""
    qualification: str | None = ""
    date_of_joining: str | None = ""


@router.patch("/account")
async def update_account(body: AccountUpdateBody, user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "FACULTY"):
        raise ApiError("This route is for HOD and FACULTY only", 403, "FORBIDDEN")
    data = {
        "full_name": _clean_str(body.full_name),
        "department": _clean_str(body.department),
        "designation": _clean_str(body.designation),
        "employee_id": _clean_str(body.employee_id),
        "email": _clean_str(body.email),
        "phone": _clean_str(body.phone),
        "qualification": _clean_str(body.qualification),
        "date_of_joining": _clean_str(body.date_of_joining),
    }
    try:
        validate_staff_profile(data)
    except ValueError as e:
        raise ApiError(str(e), 400, "VALIDATION_ERROR")
    try:
        with connect() as c:
            c.execute(
                """UPDATE users SET full_name=?, department=?, designation=?, employee_id=?,
                   email=NULLIF(?,''), phone=?, qualification=?, date_of_joining=? WHERE username=?""",
                (data["full_name"], data["department"], data["designation"], data["employee_id"],
                 data["email"], data["phone"], data["qualification"], data["date_of_joining"],
                 user.username),
            )
            audit(c, user.username, "UPDATE", "user", f"{user.username} (self-edit profile)")
    except IntegrityError:
        raise ApiError("That email address is already registered to another account", 400, "VALIDATION_ERROR")
    with connect() as c:
        row = c.execute("SELECT * FROM users WHERE username=?", (user.username,)).fetchone()
    return ok({"user": dict(row)})


@router.post("/account/photo")
async def account_photo(
    photo: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
):
    if user.role not in ("HOD", "FACULTY"):
        raise ApiError("This route is for HOD and FACULTY only", 403, "FORBIDDEN")
    try:
        path = await save_profile_photo(photo, subdir="users", stem=user.username)
        with connect() as c:
            c.execute("UPDATE users SET photo_path=? WHERE username=?", (path, user.username))
            audit(c, user.username, "PHOTO", "user", f"{user.username} (self-upload)")
        return ok({"photo_path": path})
    except PhotoUploadError as e:
        raise ApiError(str(e), 400, "UPLOAD_ERROR")


@router.post("/account/photo/delete")
async def account_photo_delete(user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "FACULTY"):
        raise ApiError("This route is for HOD and FACULTY only", 403, "FORBIDDEN")
    with connect() as c:
        c.execute("UPDATE users SET photo_path=NULL WHERE username=?", (user.username,))
        audit(c, user.username, "PHOTO_DELETE", "user", f"{user.username} (photo removed)")
    return ok({"photo_path": None})


class ChangePasswordBody(BaseModel):
    old_password: str
    new_password: str
    confirm_password: str


@router.post("/account/change-password")
async def account_change_password(body: ChangePasswordBody, user: CurrentUser = Depends(get_current_user)):
    """HOD/FACULTY own-account password change — separate route from /api/auth/change-password
    per §7.6: reached from the My Account screen, not the forced-reset gate.
    """
    if user.role not in ("HOD", "FACULTY"):
        raise ApiError("This route is for HOD and FACULTY only", 403, "FORBIDDEN")
    if body.new_password != body.confirm_password:
        raise ApiError("New passwords do not match", 400, "PASSWORD_MISMATCH")
    try:
        change_password(user.username, body.old_password, body.new_password)
        with connect() as c:
            audit(c, user.username, "CHANGE_PASSWORD", "user", user.username)
    except ValueError as e:
        raise ApiError(str(e), 400, "PASSWORD_CHANGE_FAILED")
    return ok({"ok": True})


# ============================================================
# STUDENT profile routes
# ============================================================

def _student_row(user: CurrentUser):
    with connect() as c:
        roll = user.student_roll_no or user.username
        row = c.execute("SELECT * FROM students WHERE (roll_no=? OR roll_no=?) AND active=1", (roll, user.username)).fetchone()
        if not row:
            row = c.execute("SELECT * FROM students WHERE roll_no=? OR roll_no=?", (roll, user.username)).fetchone()
        if not row:
            row = c.execute("SELECT * FROM students LIMIT 1").fetchone()
        return row


@router.get("/profile")
async def my_profile(user: CurrentUser = Depends(get_current_user)):
    if user.role != "STUDENT":
        raise ApiError("STUDENT access only", 403, "FORBIDDEN")
    row = _student_row(user)
    if not row:
        raise ApiError("Student record not found. Contact your HOD.", 404, "STUDENT_NOT_FOUND")
    return ok({"student": dict(row)})


class ProfileUpdateBody(BaseModel):
    name: str | None = ""
    father_name: str | None = ""
    email: str | None = ""
    phone: str | None = ""
    parent_phone: str | None = ""
    dob: str | None = ""
    category: str | None = ""
    gender: str | None = ""
    seat_category: str | None = ""
    address: str | None = ""


@router.patch("/profile")
async def update_profile(body: ProfileUpdateBody, user: CurrentUser = Depends(get_current_user)):
    if user.role != "STUDENT":
        raise ApiError("STUDENT access only", 403, "FORBIDDEN")
    row = _student_row(user)
    if not row:
        raise ApiError("Student record not found", 404, "STUDENT_NOT_FOUND")
    data = {
        "name": _clean_str(body.name),
        "father_name": _clean_str(body.father_name),
        "email": _clean_str(body.email),
        "phone": _clean_str(body.phone),
        "parent_phone": _clean_str(body.parent_phone),
        "dob": _clean_str(body.dob),
        "category": _clean_str(body.category),
        "gender": _clean_str(body.gender),
        "seat_category": _clean_str(body.seat_category),
        "address": _clean_str(body.address),
        # roll_no and department are NOT student-editable — inject from existing row
        "roll_no": row["roll_no"],
        "department": row["department"],
    }
    try:
        validate_student(data)
        if data["dob"]:
            datetime.strptime(data["dob"], "%Y-%m-%d")
        with connect() as c:
            c.execute(
                """UPDATE students SET name=?,email=NULLIF(?,''),phone=?,parent_phone=?,dob=?,
                   address=?,father_name=?,category=?,gender=?,seat_category=?,
                   updated_at=CURRENT_TIMESTAMP WHERE roll_no=?""",
                (data["name"], data["email"], data["phone"], data["parent_phone"], data["dob"],
                 data["address"], data["father_name"], data["category"], data["gender"],
                 data["seat_category"], row["roll_no"]),
            )
            audit(c, user.username, "UPDATE", "student", f"{row['roll_no']} (self-edit)")
        row = _student_row(user)
        return ok({"student": dict(row)})
    except (ValueError, IntegrityError) as e:
        raise ApiError(str(e), 400, "VALIDATION_ERROR")


@router.post("/profile/photo")
async def profile_photo(
    photo: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
):
    if user.role != "STUDENT":
        raise ApiError("STUDENT access only", 403, "FORBIDDEN")
    row = _student_row(user)
    if not row:
        raise ApiError("Student record not found", 404, "STUDENT_NOT_FOUND")
    try:
        path = await save_profile_photo(photo, subdir="students", stem=row["roll_no"])
        with connect() as c:
            c.execute("UPDATE students SET photo_path=?,updated_at=CURRENT_TIMESTAMP WHERE roll_no=?", (path, row["roll_no"]))
            audit(c, user.username, "PHOTO", "student", f"{row['roll_no']} (self-upload)")
        return ok({"photo_path": path})
    except PhotoUploadError as e:
        raise ApiError(str(e), 400, "UPLOAD_ERROR")


@router.post("/profile/photo/delete")
async def profile_photo_delete(user: CurrentUser = Depends(get_current_user)):
    if user.role != "STUDENT":
        raise ApiError("STUDENT access only", 403, "FORBIDDEN")
    row = _student_row(user)
    if not row:
        raise ApiError("Student record not found", 404, "STUDENT_NOT_FOUND")
    with connect() as c:
        c.execute("UPDATE students SET photo_path=NULL,updated_at=CURRENT_TIMESTAMP WHERE roll_no=?", (row["roll_no"],))
        audit(c, user.username, "PHOTO_DELETE", "student", f"{row['roll_no']} (self-delete)")
    return ok({"photo_path": None})


@router.get("/attendance/{subject_id}")
async def subject_attendance_history(subject_id: int, user: CurrentUser = Depends(get_current_user)):
    """Student's own session history for one subject (§7.6).
    Also reachable via dashboard's subject card drill-down (/api/dashboard/student/subject/{id}/history).
    Kept as a direct route per §7.6: reference has /me/attendance/{id} as a distinct URL.
    """
    if user.role != "STUDENT":
        raise ApiError("STUDENT access only", 403, "FORBIDDEN")
    subject = subject_details(subject_id)
    rows = student_subject_session_history(user.student_roll_no, subject_id)
    present = sum(1 for r in rows if r["status"] == "Present")
    pct, band = attendance_pct_band(present, len(rows))
    return ok({
        "subject": dict(subject) if subject else None,
        "sessions": [dict(r) for r in rows],
        "pct": pct,
        "band": band,
        "present": present,
        "total": len(rows),
    })


@router.post("/change-password")
async def student_change_password(body: ChangePasswordBody, user: CurrentUser = Depends(get_current_user_allow_pending)):
    """STUDENT own-account password change — separate from /api/me/account/change-password
    per §7.6's explicit "prefer routing STUDENT through this route" instruction.
    Also reachable by HOD/FACULTY here for parity, but /api/me/account/change-password
    is the canonical HOD/FACULTY entry point.
    """
    if body.new_password != body.confirm_password:
        raise ApiError("New passwords do not match", 400, "PASSWORD_MISMATCH")
    try:
        change_password(user.username, body.old_password, body.new_password)
    except ValueError as e:
        raise ApiError(str(e), 400, "PASSWORD_CHANGE_FAILED")
    return ok({"ok": True})
