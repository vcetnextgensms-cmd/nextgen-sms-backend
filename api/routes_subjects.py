"""Group 5 — Subjects + Semesters API (§7.5).

Source: webapp/routes/subjects.py — ported to JSON API shape.
HOD-only for every mutating route per spec §7.5.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from sms_app.services.attendance_service import (
    all_subjects_admin, create_subject, delete_subject, list_all_semesters, list_semesters,
    set_semester_active, set_subject_active, set_subject_faculty, update_subject,
)
from database import connect, IntegrityError

from api.deps import CurrentUser, get_current_user
from api.envelope import ApiError, ok

router = APIRouter(tags=["subjects"])


def _require_hod(user: CurrentUser):
    if user.role != "HOD":
        raise ApiError("HOD access only", 403, "FORBIDDEN")


@router.get("/api/subjects")
async def subjects_list(user: CurrentUser = Depends(get_current_user)):
    _require_hod(user)
    semesters = [dict(s) for s in list_semesters()]
    all_semesters = [dict(s) for s in list_all_semesters()]
    grouped_raw = all_subjects_admin()
    # grouped_raw is list of {"id": ..., "code": ..., "name": ..., "subjects": [...]}
    grouped = {}
    for sem in grouped_raw:
        sem_code = sem["code"]
        subj_rows = []
        for s in sem["subjects"]:
            subj_dict = dict(s)
            subj_dict["faculty_usernames"] = [f["username"] for f in s.get("faculty", [])]
            subj_rows.append(subj_dict)
        grouped[sem_code] = subj_rows
    with connect() as c:
        faculty = c.execute(
            "SELECT username, full_name FROM users WHERE role='FACULTY' AND active=1 ORDER BY full_name"
        ).fetchall()
    return ok({
        "semesters": semesters,
        "all_semesters": all_semesters,
        "grouped": grouped,
        "faculty": [dict(f) for f in faculty],
    })


class SubjectCreateBody(BaseModel):
    semester_id: int
    code: str
    name: str
    has_lab: bool = False


class SubjectUpdateBody(BaseModel):
    code: str
    name: str
    has_lab: bool = False


@router.post("/api/subjects", status_code=201)
async def subject_create(body: SubjectCreateBody, user: CurrentUser = Depends(get_current_user)):
    _require_hod(user)
    try:
        create_subject(semester_id=body.semester_id, code=body.code, name=body.name,
                       has_lab=body.has_lab, actor=user.username)
        return ok({"ok": True})
    except IntegrityError:
        raise ApiError("A subject with that code already exists in this semester", 400, "VALIDATION_ERROR")
    except ValueError as e:
        raise ApiError(str(e), 400, "VALIDATION_ERROR")


@router.patch("/api/subjects/{subject_id}")
async def subject_update(subject_id: int, body: SubjectUpdateBody, user: CurrentUser = Depends(get_current_user)):
    _require_hod(user)
    try:
        update_subject(subject_id=subject_id, code=body.code, name=body.name,
                       has_lab=body.has_lab, actor=user.username)
        return ok({"ok": True})
    except IntegrityError:
        raise ApiError("A subject with that code already exists in this semester", 400, "VALIDATION_ERROR")
    except ValueError as e:
        raise ApiError(str(e), 400, "VALIDATION_ERROR")


@router.post("/api/subjects/{subject_id}/toggle-active")
async def subject_toggle_active(subject_id: int, user: CurrentUser = Depends(get_current_user)):
    _require_hod(user)
    with connect() as c:
        row = c.execute("SELECT active FROM subjects WHERE id=?", (subject_id,)).fetchone()
    if not row:
        raise ApiError("Subject not found", 404, "NOT_FOUND")
    set_subject_active(subject_id=subject_id, active=not row["active"], actor=user.username)
    return ok({"active": not row["active"]})


@router.delete("/api/subjects/{subject_id}")
async def subject_delete(subject_id: int, user: CurrentUser = Depends(get_current_user)):
    _require_hod(user)
    try:
        delete_subject(subject_id=subject_id, actor=user.username)
        return ok({"ok": True})
    except ValueError as e:
        raise ApiError(str(e), 400, "VALIDATION_ERROR")



class AssignFacultyBody(BaseModel):
    faculty_usernames: List[str]


@router.post("/api/subjects/{subject_id}/assign-faculty")
async def assign_faculty(subject_id: int, body: AssignFacultyBody, user: CurrentUser = Depends(get_current_user)):
    _require_hod(user)
    try:
        set_subject_faculty(subject_id=subject_id, faculty_usernames=body.faculty_usernames, actor=user.username)
        return ok({"ok": True})
    except ValueError as e:
        raise ApiError(str(e), 400, "VALIDATION_ERROR")


@router.post("/api/semesters/{semester_id}/toggle-active")
async def semester_toggle_active(semester_id: int, user: CurrentUser = Depends(get_current_user)):
    _require_hod(user)
    with connect() as c:
        row = c.execute("SELECT active FROM academic_semesters WHERE id=?", (semester_id,)).fetchone()
    if not row:
        raise ApiError("Semester not found", 404, "NOT_FOUND")
    set_semester_active(semester_id=semester_id, active=not row["active"], actor=user.username)
    return ok({"active": not row["active"]})
