"""Group 2 — Dashboard API. OPTION_B_REWRITE_PLAN.md §2 group 2.

Route mapping (old -> new, per plan §3.2 pattern):
  GET /dashboard           -> GET /api/dashboard          (role-aware)
  GET /attendance-session/{id}/present -> GET /api/dashboard/session/{id}/present
  GET /attendance-session/{id}/absent  -> GET /api/dashboard/session/{id}/absent
  GET /audit-log           -> GET /api/dashboard/audit-log
  GET /sms-log             -> GET /api/dashboard/sms-log
  (new, STUDENT-only)      -> GET /api/dashboard/student/subject/{id}/history
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from database import connect
from sms_app.services.attendance_service import (
    absent_students_for_session,
    attendance_pct_band,
    present_students_for_session,
    session_details,
    sessions_last_n_days,
    student_subject_attendance,
    student_subject_session_history,
)

from api.deps import CurrentUser, get_current_user
from api.envelope import ApiError, ok

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _serialize_session_row(r) -> dict:
    """Convert a row from sessions_last_n_days() to a JSON-safe dict."""
    return {
        "id":             r["id"],
        "attendance_date": r["attendance_date"],
        "session_type":   r["session_type"],
        "duration_hours": r["duration_hours"],
        "created_at":     r["created_at"],
        "topic":          r["topic"] if "topic" in r.keys() else None,
        "subject_name":   r["subject_name"],
        "subject_code":   r["subject_code"],
        "faculty_name":   r["faculty_name"],
        "faculty_username": r["faculty_username"],
        "semester_code":  r["semester_code"] if "semester_code" in r.keys() else None,
        "semester_name":  r["semester_name"] if "semester_name" in r.keys() else None,
        "absent_count":   r["absent_count"],
        "present_count":  r["present_count"],
        "total_marked":   r["total_marked"],
    }


# ──────────────────────────────────────────────
# GET /api/dashboard
# ──────────────────────────────────────────────

@router.get("")
async def dashboard(
    date: str | None = Query(default=None, description="YYYY-MM-DD — filter HOD view to a single day"),
    semester_id: int | None = Query(default=None, description="Filter HOD view to a single semester"),
    year: str | None = Query(default=None, description="Academic year: 1, 2, 3, or 4"),
    user: CurrentUser = Depends(get_current_user),
):
    """Role-aware dashboard root."""
    if user.role == "FACULTY":
        return ok({"role": "FACULTY", "redirect": "/attendance"})

    if user.role == "STUDENT":
        return await _student_dashboard(user)

    # HOD / ADMIN
    return await _hod_dashboard(user, picked_date=date, picked_semester_id=semester_id, picked_year=year)


async def _hod_dashboard(user: CurrentUser, picked_date: str | None, picked_semester_id: int | None = None, picked_year: str | None = None) -> dict:
    grouped_raw = sessions_last_n_days(15, on_date=picked_date, semester_id=picked_semester_id, year=picked_year)
    days: dict[str, list[dict]] = {
        date_str: [_serialize_session_row(r) for r in rows]
        for date_str, rows in grouped_raw.items()
    }
    return ok({
        "role":               "HOD",
        "days":               days,
        "picked_date":        picked_date,
        "picked_semester_id": picked_semester_id,
        "picked_year":        picked_year,
    })


async def _student_dashboard(user: CurrentUser) -> dict:
    with connect() as c:
        s = c.execute(
            "SELECT roll_no, name, department FROM students WHERE roll_no=?",
            (user.student_roll_no,),
        ).fetchone()

    if not s:
        raise ApiError(
            "Your student record was not found. Contact HOD.",
            status_code=404,
            code="STUDENT_NOT_FOUND",
        )

    rows = student_subject_attendance(user.student_roll_no)
    subjects = []
    for r in rows:
        pct, band = attendance_pct_band(r["present_sessions"], r["total_sessions"])
        subjects.append({
            "subject_id":   r["subject_id"],
            "code":         r["subject_code"],
            "name":         r["subject_name"],
            "pct":          pct,
            "band":         band,
            "total":        r["total_sessions"],
            "present":      r["present_sessions"],
        })

    return ok({
        "role":    "STUDENT",
        "student": {"roll_no": s["roll_no"], "name": s["name"], "department": s["department"]},
        "subjects": subjects,
    })


# ──────────────────────────────────────────────
# Session drill-downs (HOD / FACULTY)
# ──────────────────────────────────────────────

@router.get("/session/{session_id}/present")
async def session_present(
    session_id: int,
    user: CurrentUser = Depends(get_current_user),
):
    if user.role not in ("HOD", "FACULTY"):
        raise ApiError("Access denied", status_code=403, code="FORBIDDEN")
    sess = session_details(session_id)
    if not sess:
        raise ApiError("Session not found", status_code=404, code="NOT_FOUND")
    rows = present_students_for_session(session_id)
    return ok({
        "session": {
            "id":              sess["id"],
            "subject_name":    sess["subject_name"],
            "attendance_date": sess["attendance_date"],
            "session_type":    sess["session_type"],
        },
        "students": [{"roll_no": r["roll_no"], "name": r["name"]} for r in rows],
        "kind": "present",
    })


@router.get("/session/{session_id}/absent")
async def session_absent(
    session_id: int,
    user: CurrentUser = Depends(get_current_user),
):
    if user.role not in ("HOD", "FACULTY"):
        raise ApiError("Access denied", status_code=403, code="FORBIDDEN")
    sess = session_details(session_id)
    if not sess:
        raise ApiError("Session not found", status_code=404, code="NOT_FOUND")
    rows = absent_students_for_session(session_id)
    return ok({
        "session": {
            "id":              sess["id"],
            "subject_name":    sess["subject_name"],
            "attendance_date": sess["attendance_date"],
            "session_type":    sess["session_type"],
        },
        "students": [{"roll_no": r["roll_no"], "name": r["name"]} for r in rows],
        "kind": "absent",
    })


# ──────────────────────────────────────────────
# Student subject session history
# ──────────────────────────────────────────────

@router.get("/student/subject/{subject_id}/history")
async def student_subject_history(
    subject_id: int,
    user: CurrentUser = Depends(get_current_user),
):
    if user.role != "STUDENT":
        raise ApiError("Access denied", status_code=403, code="FORBIDDEN")
    if not user.student_roll_no:
        raise ApiError(
            "Your student record was not found. Contact HOD.",
            status_code=404,
            code="STUDENT_NOT_FOUND",
        )
    rows = student_subject_session_history(user.student_roll_no, subject_id)
    return ok({
        "subject_id": subject_id,
        "sessions": [
            {
                "attendance_date": r["attendance_date"],
                "session_type":   r["session_type"],
                "duration_hours": r["duration_hours"],
                "status":         r["status"],
            }
            for r in rows
        ],
    })


# ──────────────────────────────────────────────
# Audit Log & SMS Log (HOD only)
# ──────────────────────────────────────────────

@router.get("/audit-log")
async def audit_log_endpoint(user: CurrentUser = Depends(get_current_user)):
    if user.role != "HOD":
        raise ApiError("HOD access only", status_code=403, code="FORBIDDEN")
    from sms_app.services.attendance_service import recent_audit_logs
    rows = recent_audit_logs(150)
    return ok([dict(r) for r in rows])


@router.get("/sms-log")
async def sms_log_endpoint(user: CurrentUser = Depends(get_current_user)):
    if user.role != "HOD":
        raise ApiError("HOD access only", status_code=403, code="FORBIDDEN")
    from sms_app.services.sms_service import recent_sms
    rows = recent_sms(150)
    return ok([dict(r) for r in rows])


from pydantic import BaseModel
from database import get_setting, set_setting


class SmsSettingsBody(BaseModel):
    sms_enabled: str = "0"
    sms_gateway_type: str = "android"
    sms_android_url: str = "http://100.92.227.240:8080"
    sms_android_user: str = "sms"
    sms_android_password: str = ""
    sms_android_key: str = ""
    sms_modem_port: str = "/dev/ttyUSB0"
    sms_modem_baud: str = "115200"
    sms_daily_cap: str = "62"


class SmsTestBody(BaseModel):
    phone: str
    message: str = "Dear Parent, Student is absent for class today (Database Systems, 2026-07-30). - VCET CSD Data Science Dept"
 
 
@router.get("/sms-settings")
async def get_sms_settings(user: CurrentUser = Depends(get_current_user)):
    if user.role != "HOD":
        raise ApiError("HOD access only", status_code=403, code="FORBIDDEN")
    return ok({
        "sms_enabled": get_setting("sms_enabled", "0"),
        "sms_gateway_type": get_setting("sms_gateway_type", "android"),
        "sms_android_url": get_setting("sms_android_url", "http://100.92.227.240:8080"),
        "sms_android_user": get_setting("sms_android_user", "sms"),
        "sms_android_password": get_setting("sms_android_password", ""),
        "sms_android_key": get_setting("sms_android_key", ""),
        "sms_modem_port": get_setting("sms_modem_port", "/dev/ttyUSB0"),
        "sms_modem_baud": get_setting("sms_modem_baud", "115200"),
        "sms_daily_cap": get_setting("sms_daily_cap", "62"),
    })


@router.post("/sms-settings")
async def save_sms_settings(body: SmsSettingsBody, user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("Access denied", status_code=403, code="FORBIDDEN")
    set_setting("sms_enabled", body.sms_enabled, actor=user.username)
    set_setting("sms_gateway_type", body.sms_gateway_type, actor=user.username)
    set_setting("sms_android_url", body.sms_android_url, actor=user.username)
    set_setting("sms_android_user", body.sms_android_user, actor=user.username)
    set_setting("sms_android_password", body.sms_android_password, actor=user.username)
    set_setting("sms_android_key", body.sms_android_key, actor=user.username)
    set_setting("sms_modem_port", body.sms_modem_port, actor=user.username)
    set_setting("sms_modem_baud", body.sms_modem_baud, actor=user.username)
    set_setting("sms_daily_cap", body.sms_daily_cap, actor=user.username)
    return ok({"ok": True})


@router.post("/sms-test")
async def test_sms_gateway(body: SmsTestBody, user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("Access denied", status_code=403, code="FORBIDDEN")
    from webapp.sms_worker import send_single_sms
    msg = body.message.strip() if body.message and body.message.strip() else "Dear Parent, Student is absent for class today (Database Systems, 2026-07-30). - VCET CSD Data Science Dept"
    try:
        send_single_sms(body.phone, msg)
        return ok({"sent": True, "message": f"Test SMS sent successfully with text: '{msg}'"})
    except Exception as exc:
        raise ApiError(f"Test SMS failed: {exc}", status_code=400, code="SMS_SEND_FAILED")


@router.post("/sms-trigger")
async def trigger_sms_queue(user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("Access denied", status_code=403, code="FORBIDDEN")
    from webapp.sms_worker import process_pending_sms_now
    sent, failed = process_pending_sms_now()
    return ok({"sent_count": sent, "failed_count": failed})
