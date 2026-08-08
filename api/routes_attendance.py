"""Group 3 — Attendance API. OPTION_B_REWRITE_PLAN.md §2 group 3 / §3.2.

Route mapping (old Jinja -> new JSON, per plan §3.2 pattern):
  GET  /attendance                              -> GET  /api/attendance/setup
  GET  /attendance/subjects-for-semester         -> GET  /api/attendance/subjects
  POST /attendance/open                          -> POST /api/attendance/sessions
  GET  /attendance/register/{id}                 -> GET  /api/attendance/sessions/{id}
  POST /attendance/register/{id}/save            -> POST /api/attendance/sessions/{id}/save
  POST /attendance/register/{id}/mark-all-present -> POST /api/attendance/sessions/{id}/mark-all-present
  GET  /attendance/register/{id}/pdf             -> GET  /api/attendance/sessions/{id}/pdf

Deliberately NOT ported (per Handoff 5 / plan §2's client-state-until-Save
decision, confirmed standing): the old app's per-tap server round trips —
/mark/{roll}/{status}, /toggle/{roll}, /quick-mark. In the JSON API, the
roster is fetched once (GET .../sessions/{id}), every tap/quick-mark/
mark-all-present is pure client-side React state, and only /save commits
to the DB. mark-all-present stays a real endpoint (not client-only)
because it doubles as a legitimate batch DB shortcut mirroring the old
app's own /mark-all-present — but note this version returns the *roster
with every row flipped present* rather than writing to the DB itself; the
actual DB write only ever happens through /save, same single-write-
boundary rule save_register() already enforces. See _serialize_roster's
docstring for why "mark all present" doesn't just call save_register
twice.

Reuses sms_app/services/attendance_service.py and sms_app/services/
sms_service.py unchanged, per plan §3.5 — no business logic rewritten,
only transport changed. Same CRITICAL role-check pattern as
webapp/routes/attendance.py's save() (RED_TEAM_FINDINGS.md): every
mutating route below re-checks role itself, not just relying on a
downstream ownership check, because that ownership check only ever
restricts FACULTY — it does not by itself block a non-FACULTY caller.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel

from sms_app.services.attendance_service import (
    get_or_create_session,
    list_semesters,
    list_subjects,
    load_register,
    save_register,
    session_details,
    session_is_editable,
    subject_details,
    validate_session_payload,
)
from sms_app.services.attendance_pdf import build_attendance_pdf
from sms_app.services.sms_service import queue_absentees_for_session

from api.deps import CurrentUser, get_current_user
from api.envelope import ApiError, ok

router = APIRouter(prefix="/api/attendance", tags=["attendance"])

_STAFF_ROLES = ("HOD", "FACULTY", "ADMIN")


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _require_staff(user: CurrentUser) -> None:
    # — CRITICAL role-check (RED_TEAM_FINDINGS.md; see webapp/routes/attendance.py's
    # save() comment for why this can't be inferred from the ownership check
    # below). Every mutating route in this file calls this first, unconditionally.
    if user.role not in _STAFF_ROLES:
        raise ApiError("Access denied", status_code=403, code="FORBIDDEN")


def _load_session_or_404(session_id: int):
    session = session_details(session_id)
    if not session:
        raise ApiError("Attendance session was not found", status_code=404, code="NOT_FOUND")
    return session


def _require_owner_or_hod(user: CurrentUser, session) -> None:
    # WHY separate from _require_staff: this guards WHICH sessions a given
    # FACULTY may act on; _require_staff guards WHO may act at all. HOD
    # bypasses this check (can act on any faculty's session), FACULTY may
    # only act on their own. Same split as the old app's every handler.
    if user.role == "FACULTY" and session["faculty_username"] != user.username:
        raise ApiError("You do not have access to this session", status_code=403, code="FORBIDDEN")


def _serialize_session(session) -> dict:
    return {
        "id":               session["id"],
        "attendance_date":  session["attendance_date"],
        "semester_id":      session["semester_id"],
        "subject_id":       session["subject_id"],
        "subject_code":     session["subject_code"],
        "subject_name":     session["subject_name"],
        "semester_code":    session["semester_code"],
        "semester_name":    session["semester_name"],
        "faculty_username": session["faculty_username"],
        "faculty_name":     session["faculty_name"],
        "session_type":     session["session_type"],
        "duration_hours":   session["duration_hours"],
        "topic":            session["topic"],
        "created_at":       session["created_at"],
    }


def _serialize_roster(session_id: int, *, force_present: bool = False) -> list[dict]:
    """Shared by GET .../sessions/{id} and POST .../mark-all-present.

    force_present=True is the "Mark all present" case: it does NOT write
    anything — save_register() is the single DB-write boundary for
    attendance (validated by its own 24h/role checks), so a batch
    convenience endpoint that skipped straight to the DB would create a
    second write path with its own copy of those checks to keep in sync.
    Instead this just returns the roster shape with every row flipped
    present=True; the frontend holds that as client state exactly like any
    other tap, and it only becomes real when the user hits Save.
    """
    students, existing = load_register(session_id)
    return [
        {
            "roll_no": s["roll_no"],
            "name": s["name"],
            "present": True if force_present else existing.get(s["roll_no"]) == "Present",
        }
        for s in students
    ]


# ──────────────────────────────────────────────
# GET /api/attendance/setup — semesters + subjects + sensible defaults
# ──────────────────────────────────────────────

@router.get("/setup")
async def setup(user: CurrentUser = Depends(get_current_user)):
    """Everything the Mark Attendance setup screen needs in one call:
    semester list, subjects for a sensibly-defaulted semester, and today's
    date. Mirrors webapp/routes/attendance.py's attendance_setup() default
    logic: first semester that actually has subjects for this user, not
    just the first semester in sort order (which may be empty for them)."""
    _require_staff(user)

    semesters = list_semesters()
    sem_id = None
    for sem in semesters:
        if list_subjects(sem["id"], user.username, user.role):
            sem_id = sem["id"]
            break
    if sem_id is None and semesters:
        sem_id = semesters[0]["id"]

    subjects = list_subjects(sem_id, user.username, user.role) if sem_id else []

    return ok({
        "semesters": [{"id": s["id"], "code": s["code"], "name": s["name"]} for s in semesters],
        "subjects": [
            {"id": s["id"], "code": s["code"], "name": s["name"], "has_lab": bool(s["has_lab"])}
            for s in subjects
        ],
        "default_semester_id": sem_id,
        "today": date.today().isoformat(),
    })


@router.get("/subjects")
async def subjects_for_semester(
    semester_id: int = Query(...),
    user: CurrentUser = Depends(get_current_user),
):
    """Subject list refresh when the semester picker changes — JSON
    equivalent of the old HTMX partial /attendance/subjects-for-semester."""
    _require_staff(user)
    subjects = list_subjects(semester_id, user.username, user.role)
    return ok({
        "subjects": [
            {"id": s["id"], "code": s["code"], "name": s["name"], "has_lab": bool(s["has_lab"])}
            for s in subjects
        ],
    })


# ──────────────────────────────────────────────
# POST /api/attendance/sessions — open (get-or-create) a session
# ──────────────────────────────────────────────

class OpenSessionBody(BaseModel):
    attendance_date: str
    semester_id: int
    subject_id: int
    session_type: str
    duration_hours: int
    topic: str


@router.post("/sessions")
async def open_session(
    body: OpenSessionBody,
    user: CurrentUser = Depends(get_current_user),
):
    _require_staff(user)

    subject = subject_details(body.subject_id)
    if not subject:
        raise ApiError("Select a valid subject", status_code=400, code="VALIDATION_ERROR")
    sess_type = body.session_type.upper()
    duration_hours = 3 if sess_type == "LAB" else body.duration_hours

    try:
        validate_session_payload(
            attendance_date=body.attendance_date, semester_id=body.semester_id,
            subject_id=body.subject_id, faculty_username=user.username,
            session_type=sess_type, duration_hours=duration_hours, topic=body.topic,
        )
        created = get_or_create_session(
            attendance_date=body.attendance_date, semester_id=body.semester_id,
            subject_id=body.subject_id, faculty_username=user.username,
            session_type=sess_type, duration_hours=duration_hours,
            topic=body.topic, actor=user.username,
        )
    except ValueError as exc:
        raise ApiError(str(exc), status_code=400, code="VALIDATION_ERROR")

    # WHY re-fetch via session_details() instead of serializing `created`
    # directly: get_or_create_session() returns the raw attendance_sessions
    # row (has subject_id but not the JOINed subject_code/subject_name/
    # semester_code/faculty_name columns _serialize_session expects).
    # session_details() does that JOIN -- same function every other route
    # in this file uses to build the response shape. Caught by the Group 3
    # TestClient run (IndexError: No item with that key), not assumed.
    session = session_details(created["id"])
    return ok(_serialize_session(session), status_code=201)


# ──────────────────────────────────────────────
# GET /api/attendance/sessions/{id} — session + roster (register screen)
# ──────────────────────────────────────────────

@router.get("/sessions/{session_id}")
async def get_session(
    session_id: int,
    user: CurrentUser = Depends(get_current_user),
):
    _require_staff(user)
    session = _load_session_or_404(session_id)
    _require_owner_or_hod(user, session)

    roster = _serialize_roster(session_id)
    present = sum(r["present"] for r in roster)
    return ok({
        "session":  _serialize_session(session),
        "editable": session_is_editable(session, user.role),
        "roster":   roster,
        "present":  present,
        "absent":   len(roster) - present,
    })


# ──────────────────────────────────────────────
# POST /api/attendance/sessions/{id}/mark-all-present
# ──────────────────────────────────────────────

@router.post("/sessions/{session_id}/mark-all-present")
async def mark_all_present(
    session_id: int,
    user: CurrentUser = Depends(get_current_user),
):
    """Batch convenience only — see _serialize_roster's docstring. Does not
    touch the DB; returns the roster with every row flipped present=True
    for the frontend to hold as client state until Save."""
    _require_staff(user)
    session = _load_session_or_404(session_id)
    _require_owner_or_hod(user, session)

    editable = session_is_editable(session, user.role)
    roster = _serialize_roster(session_id, force_present=editable)
    present = sum(r["present"] for r in roster)
    return ok({
        "editable": editable,
        "roster":   roster,
        "present":  present,
        "absent":   len(roster) - present,
    })


# ──────────────────────────────────────────────
# POST /api/attendance/sessions/{id}/save — the single DB-write boundary
# ──────────────────────────────────────────────

class SaveRegisterBody(BaseModel):
    present_roll_nos: list[str]


@router.post("/sessions/{session_id}/save")
async def save(
    session_id: int,
    body: SaveRegisterBody,
    user: CurrentUser = Depends(get_current_user),
):
    # — CRITICAL role-check, duplicated from _require_staff intentionally
    # inline-obvious here (not just via the helper) because this is the
    # actual write boundary the RED_TEAM_FINDINGS.md regression happened
    # on — see webapp/routes/attendance.py's save() comment for the full
    # story. Do not remove thinking _require_owner_or_hod below covers it;
    # it doesn't (it only ever restricts FACULTY, never blocks a
    # non-FACULTY caller by itself).
    _require_staff(user)
    session = _load_session_or_404(session_id)
    _require_owner_or_hod(user, session)

    students, _ = load_register(session_id)
    present_set = set(body.present_roll_nos)
    attendance = {s["roll_no"]: (s["roll_no"] in present_set) for s in students}

    try:
        save_register(
            session_id=session_id, attendance=attendance, actor=user.username, role=user.role,
            session_type=session["session_type"], duration_hours=session["duration_hours"],
            topic=session["topic"],
        )
    except PermissionError as exc:
        raise ApiError(str(exc), status_code=403, code="EDIT_WINDOW_EXPIRED")
    except ValueError as exc:
        raise ApiError(str(exc), status_code=400, code="VALIDATION_ERROR")

    absent_rolls = [roll for roll, is_present in attendance.items() if not is_present]
    queued_count = 0
    if absent_rolls:
        try:
            queued_count, _ = queue_absentees_for_session(session_id, absent_rolls, actor=user.username)
        except Exception as exc:
            print(f"[Automated SMS Queue] Notice: {exc}")
        try:
            from webapp.sms_worker import process_pending_sms_now
            process_pending_sms_now()
        except Exception as exc:
            print(f"[Automated SMS Gateway] Dispatch notice: {exc}")

    roster = _serialize_roster(session_id)
    present = sum(r["present"] for r in roster)
    return ok({
        "session": _serialize_session(_load_session_or_404(session_id)),
        "roster":  roster,
        "present": present,
        "absent":  len(roster) - present,
        "sms_queued": queued_count,
    })


# ──────────────────────────────────────────────
# GET /api/attendance/sessions/{id}/pdf
# ──────────────────────────────────────────────

@router.get("/sessions/{session_id}/pdf")
async def register_pdf(
    session_id: int,
    kind: str | None = Query(default=None, description="present | absent | omit for full roster"),
    user: CurrentUser = Depends(get_current_user),
):
    """Not gated by the 24h edit lock — printing/viewing an already-saved
    register isn't editing it, same as the old Jinja route."""
    _require_staff(user)
    session = _load_session_or_404(session_id)
    _require_owner_or_hod(user, session)

    roster = _serialize_roster(session_id)
    if kind == "present":
        roster = [r for r in roster if r["present"]]
    elif kind == "absent":
        roster = [r for r in roster if not r["present"]]

    pdf_bytes = build_attendance_pdf(session, roster)
    filename = f"attendance-{session['subject_code']}-{session['attendance_date']}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
