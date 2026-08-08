"""Group 5 — Academic Calendar API (§7.5).

Source: webapp/routes/academic_calendar.py — ported to JSON API shape.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile

from database import connect
from sms_app.services.attendance_service import (
    academic_calendar_for_semesters, faculty_semester_ids, save_calendar_upload, delete_calendar_upload,
)
from webapp.photo_upload import PhotoUploadError, save_calendar_file

from api.deps import CurrentUser, get_current_user
from api.envelope import ApiError, ok

router = APIRouter(prefix="/api/academic-calendar", tags=["academic-calendar"])


@router.get("")
async def academic_calendar(user: CurrentUser = Depends(get_current_user)):
    if user.role == "HOD":
        rows = academic_calendar_for_semesters(None)
    elif user.role == "FACULTY":
        rows = academic_calendar_for_semesters(faculty_semester_ids(user.username))
    else:  # STUDENT
        with connect() as c:
            student = c.execute(
                "SELECT current_semester_id FROM students WHERE roll_no=?",
                (user.student_roll_no,)
            ).fetchone()
        sem_id = student["current_semester_id"] if student else None
        rows = academic_calendar_for_semesters([sem_id]) if sem_id else []

    semesters = []
    for r in rows:
        d = dict(r)
        d["id"] = r["semester_id"]
        semesters.append(d)

    return ok({
        "semesters": semesters,
        "can_edit": user.role == "HOD",
    })


@router.post("/{semester_id}/upload/{kind}")
async def calendar_upload(
    semester_id: int,
    kind: str,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
):
    if user.role != "HOD":
        raise ApiError("HOD access only", 403, "FORBIDDEN")
    if kind not in ("timetable", "calendar"):
        raise ApiError(f"kind must be 'timetable' or 'calendar', got '{kind}'", 400, "VALIDATION_ERROR")
    with connect() as c:
        sem = c.execute("SELECT code FROM academic_semesters WHERE id=?", (semester_id,)).fetchone()
    if not sem:
        raise ApiError("Semester not found", 404, "NOT_FOUND")
    try:
        path = await save_calendar_file(file, semester_code=sem["code"], kind=kind)
        save_calendar_upload(semester_id=semester_id, kind=kind, path=path, actor=user.username)
        return ok({"path": path, "semester_id": semester_id, "kind": kind})
    except PhotoUploadError as e:
        raise ApiError(str(e), 400, "UPLOAD_ERROR")


@router.post("/{semester_id}/delete/{kind}")
async def calendar_delete(
    semester_id: int,
    kind: str,
    user: CurrentUser = Depends(get_current_user),
):
    if user.role != "HOD":
        raise ApiError("HOD access only", 403, "FORBIDDEN")
    if kind not in ("timetable", "calendar"):
        raise ApiError(f"kind must be 'timetable' or 'calendar', got '{kind}'", 400, "VALIDATION_ERROR")
    with connect() as c:
        sem = c.execute("SELECT code FROM academic_semesters WHERE id=?", (semester_id,)).fetchone()
    if not sem:
        raise ApiError("Semester not found", 404, "NOT_FOUND")
    delete_calendar_upload(semester_id=semester_id, kind=kind, actor=user.username)
    return ok({"semester_id": semester_id, "kind": kind, "deleted": True})
