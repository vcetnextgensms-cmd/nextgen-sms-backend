"""Group 4 — Students API (§7.4).

Source: webapp/routes/students.py — ported to JSON API shape.
Backend for StudentsListPage, StudentFormPage, StudentViewPage which already exist
in frontend/src/pages/students/ and call through frontend/src/api/students.ts.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel

from database import (
    audit, connect, ensure_student_login, mask_aadhaar,
    validate_student, IntegrityError,
)
from field_encryption import decrypt_field, encrypt_field
from sms_app.services.attendance_service import list_semesters
from webapp.photo_upload import PhotoUploadError, save_profile_photo

from api.deps import CurrentUser, get_current_user
from api.envelope import ApiError, ok

router = APIRouter(prefix="/api/students", tags=["students"])

FIELD_SPECS = [
    ("Roll Number", "roll_no"), ("Full Name", "name"), ("Father Name", "father_name"),
    ("Email", "email"), ("Student Phone Number", "phone"), ("Parent Phone Number", "parent_phone"),
    ("Date of Birth (YYYY-MM-DD)", "dob"),
    ("Category", "category"), ("Gender", "gender"), ("Seat Category", "seat_category"),
    ("APAAR ID", "apaar_id"), ("Aadhaar Number", "aadhaar_number"),
    ("Certificates Submitted", "certificates_submitted"), ("Certificates Due", "certificates_due"),
    ("Consultant Name", "consultant_name"), ("Address", "address"),
]

EDUCATION_SPECS = [
    ("10th School Name", "tenth_school"), ("10th Year of Passing", "tenth_year"), ("10th Marks (%)", "tenth_marks"),
    ("12th / Junior College Name", "twelfth_school"), ("12th Year of Passing", "twelfth_year"), ("12th Marks (%)", "twelfth_marks"),
    ("Diploma College Name (if applicable)", "diploma_college"), ("Diploma Year of Passing", "diploma_year"), ("Diploma Marks (%)", "diploma_marks"),
]


def _decrypt_row(row) -> dict:
    """Return a dict with aadhaar_number/apaar_id decrypted.
    Row dictionary is immutable — must copy to dict first.
    """
    if row is None:
        return None
    d = dict(row)
    d["aadhaar_number"] = decrypt_field(d.get("aadhaar_number"))
    d["apaar_id"] = decrypt_field(d.get("apaar_id"))
    return d


def _serialize_list_row(row) -> dict:
    """For the list endpoint — decrypt then mask aadhaar.
    WHY decrypt before mask: mask_aadhaar on ciphertext silently returns
    "XXXX XXXX XXXX" without error — live-confirmed failure mode.
    """
    d = _decrypt_row(row)
    return {
        "id": d["id"],
        "roll_no": d["roll_no"],
        "name": d["name"],
        "email": d.get("email") or "",
        "phone": d.get("phone") or "",
        "aadhaar_masked": mask_aadhaar(d.get("aadhaar_number")),
        "active": bool(d["active"]),
    }


def _serialize_full(row) -> dict:
    """Full student record — aadhaar_number/apaar_id returned decrypted
    (HOD-detail-view exception per §4.4).
    """
    d = _decrypt_row(row)
    return {k: (d.get(k) or "") if isinstance(d.get(k), str) or d.get(k) is None else d[k]
            for k in d if k not in ("password",)}


@router.get("")
async def students_list(
    q: str = "",
    status: str = "Active",
    user: CurrentUser = Depends(get_current_user),
):
    if user.role == "STUDENT":
        raise ApiError("Access denied", 403, "FORBIDDEN")
    like = f"%{q.strip()}%"
    sql = (
        "SELECT * FROM students WHERE department='CSD' "
        "AND (name LIKE ? OR roll_no LIKE ? OR email LIKE ? OR phone LIKE ? OR parent_phone LIKE ?)"
    )
    args: list[Any] = [like, like, like, like, like]
    if status != "All":
        sql += " AND active=?"
        args.append(1 if status == "Active" else 0)
    sql += " ORDER BY id"
    with connect() as c:
        rows = c.execute(sql, args).fetchall()
    return ok([_serialize_list_row(r) for r in rows])


@router.get("/new")
async def student_new(user: CurrentUser = Depends(get_current_user)):
    if user.role != "HOD":
        raise ApiError("HOD access only", 403, "FORBIDDEN")
    semesters = [dict(s) for s in list_semesters()]
    return ok({"student": None, "semesters": semesters})


@router.get("/{student_id}/edit")
async def student_edit_data(student_id: int, user: CurrentUser = Depends(get_current_user)):
    if user.role != "HOD":
        raise ApiError("HOD access only", 403, "FORBIDDEN")
    with connect() as c:
        row = c.execute("SELECT * FROM students WHERE id=? AND department='CSD'", (student_id,)).fetchone()
    if not row:
        raise ApiError("Student not found", 404, "NOT_FOUND")
    # CORRUPTION TRAP: must decrypt before returning — see §4.4 and webapp/routes/students.py
    student = _serialize_full(row)
    semesters = [dict(s) for s in list_semesters()]
    return ok({"student": student, "semesters": semesters})


@router.get("/{student_id}")
async def student_view(student_id: int, user: CurrentUser = Depends(get_current_user)):
    if user.role == "STUDENT":
        raise ApiError("Access denied", 403, "FORBIDDEN")
    with connect() as c:
        row = c.execute("SELECT * FROM students WHERE id=? AND department='CSD'", (student_id,)).fetchone()
        semester = None
        if row and row["current_semester_id"]:
            sem_row = c.execute(
                "SELECT code, name FROM academic_semesters WHERE id=?",
                (row["current_semester_id"],)
            ).fetchone()
            if sem_row:
                semester = dict(sem_row)
    if not row:
        raise ApiError("Student not found", 404, "NOT_FOUND")
    # HOD detail view — aadhaar returned decrypted (§4.4 exception)
    student = _serialize_full(row)
    return ok({"student": student, "semester": semester})


def _clean_str(val: str | None) -> str:
    return (val or "").strip()


class StudentBody(BaseModel):
    roll_no: str | None = ""
    name: str | None = ""
    father_name: str | None = ""
    email: str | None = ""
    phone: str | None = ""
    parent_phone: str | None = ""
    dob: str | None = ""
    category: str | None = ""
    gender: str | None = ""
    seat_category: str | None = ""
    apaar_id: str | None = ""
    aadhaar_number: str | None = ""
    certificates_submitted: str | None = ""
    certificates_due: str | None = ""
    consultant_name: str | None = ""
    address: str | None = ""
    tenth_school: str | None = ""
    tenth_year: str | None = ""
    tenth_marks: str | None = ""
    twelfth_school: str | None = ""
    twelfth_year: str | None = ""
    twelfth_marks: str | None = ""
    diploma_college: str | None = ""
    diploma_year: str | None = ""
    diploma_marks: str | None = ""
    current_semester_id: int | None = None


def _body_to_data(body: StudentBody) -> dict:
    return {
        "roll_no": _clean_str(body.roll_no),
        "name": _clean_str(body.name),
        "department": "CSD",
        "email": _clean_str(body.email),
        "phone": _clean_str(body.phone),
        "parent_phone": _clean_str(body.parent_phone),
        "dob": _clean_str(body.dob),
        "address": _clean_str(body.address),
        "father_name": _clean_str(body.father_name),
        "category": _clean_str(body.category),
        "gender": _clean_str(body.gender),
        "seat_category": _clean_str(body.seat_category),
        "apaar_id": _clean_str(body.apaar_id),
        "aadhaar_number": _clean_str(body.aadhaar_number),
        "certificates_submitted": _clean_str(body.certificates_submitted),
        "certificates_due": _clean_str(body.certificates_due),
        "consultant_name": _clean_str(body.consultant_name),
        "tenth_school": _clean_str(body.tenth_school),
        "tenth_year": _clean_str(body.tenth_year),
        "tenth_marks": _clean_str(body.tenth_marks),
        "twelfth_school": _clean_str(body.twelfth_school),
        "twelfth_year": _clean_str(body.twelfth_year),
        "twelfth_marks": _clean_str(body.twelfth_marks),
        "diploma_college": _clean_str(body.diploma_college),
        "diploma_year": _clean_str(body.diploma_year),
        "diploma_marks": _clean_str(body.diploma_marks),
    }


STUDENT_DB_KEYS = [
    "roll_no", "name", "department", "email", "phone", "parent_phone", "dob", "address",
    "father_name", "category", "gender", "seat_category", "apaar_id", "aadhaar_number",
    "certificates_submitted", "certificates_due", "consultant_name",
    "tenth_school", "tenth_year", "tenth_marks",
    "twelfth_school", "twelfth_year", "twelfth_marks",
    "diploma_college", "diploma_year", "diploma_marks",
]


@router.post("")
async def student_create(body: StudentBody, user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access only", 403, "FORBIDDEN")
    data = _body_to_data(body)
    try:
        validate_student(data)
        if data["dob"]:
            datetime.strptime(data["dob"], "%Y-%m-%d")
        # Encrypt AFTER validation — §4.4 ordering requirement
        data["aadhaar_number"] = encrypt_field(data["aadhaar_number"])
        data["apaar_id"] = encrypt_field(data["apaar_id"])
        with connect() as c:
            c.execute(
                """INSERT INTO students(roll_no,name,department,email,phone,parent_phone,dob,address,father_name,
                   category,gender,seat_category,apaar_id,aadhaar_number,
                   certificates_submitted,certificates_due,consultant_name,
                   tenth_school,tenth_year,tenth_marks,twelfth_school,twelfth_year,twelfth_marks,
                   diploma_college,diploma_year,diploma_marks,current_semester_id)
                   VALUES(?,?,?,NULLIF(?,''),?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (*[data[k] for k in STUDENT_DB_KEYS], body.current_semester_id),
            )
            audit(c, user.username, "CREATE", "student", data["roll_no"])
            # Seed checklist — §7.4
            for item, st in [("Personal details", "Complete"), ("Documents", "Pending"),
                              ("ID card", "Pending"), ("Fees", "Pending"),
                              ("Attendance records", "Available"), ("Marks records", "Available")]:
                c.execute("INSERT IGNORE INTO checklist(roll_no,item,status) VALUES(?,?,?)",
                          (data["roll_no"], item, st))
            new_id = c.execute("SELECT id FROM students WHERE roll_no=?", (data["roll_no"],)).fetchone()["id"]
        username, password = ensure_student_login(data["roll_no"], user.username)
        return ok({"id": new_id, "created_credentials": {"username": username, "password": password}})
    except ValueError as e:
        raise ApiError(str(e), 400, "VALIDATION_ERROR")
    except IntegrityError as e:
        raise ApiError("A student with that roll number or email already exists", 400, "VALIDATION_ERROR")


@router.patch("/{student_id}")
async def student_update(student_id: int, body: StudentBody, user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access only", 403, "FORBIDDEN")
    with connect() as c:
        existing = c.execute("SELECT id FROM students WHERE id=? AND department='CSD'", (student_id,)).fetchone()
    if not existing:
        raise ApiError("Student not found", 404, "NOT_FOUND")
    data = _body_to_data(body)
    try:
        validate_student(data)
        if data["dob"]:
            datetime.strptime(data["dob"], "%Y-%m-%d")
        # Encrypt AFTER validation — §4.4 ordering requirement
        data["aadhaar_number"] = encrypt_field(data["aadhaar_number"])
        data["apaar_id"] = encrypt_field(data["apaar_id"])
        with connect() as c:
            c.execute(
                """UPDATE students SET roll_no=?,name=?,department=?,email=NULLIF(?,''),phone=?,parent_phone=?,dob=?,
                   address=?,father_name=?,category=?,gender=?,seat_category=?,apaar_id=?,aadhaar_number=?,
                   certificates_submitted=?,certificates_due=?,consultant_name=?,
                   tenth_school=?,tenth_year=?,tenth_marks=?,twelfth_school=?,twelfth_year=?,twelfth_marks=?,
                   diploma_college=?,diploma_year=?,diploma_marks=?,
                   current_semester_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (*[data[k] for k in STUDENT_DB_KEYS], body.current_semester_id, student_id),
            )
            audit(c, user.username, "UPDATE", "student", data["roll_no"])
        return ok({"id": student_id, "created_credentials": None})
    except ValueError as e:
        raise ApiError(str(e), 400, "VALIDATION_ERROR")
    except IntegrityError:
        raise ApiError("A student with that roll number or email already exists", 400, "VALIDATION_ERROR")


@router.post("/{student_id}/toggle-status")
async def toggle_status(student_id: int, user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access only", 403, "FORBIDDEN")
    with connect() as c:
        row = c.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        if not row:
            raise ApiError("Student not found", 404, "NOT_FOUND")
        new_active = 0 if row["active"] else 1
        c.execute("UPDATE students SET active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (new_active, student_id))
        audit(c, user.username, "STATUS", "student", f"{row['roll_no']} -> {new_active}")
    return ok({"active": bool(new_active)})


@router.post("/{student_id}/photo")
async def student_photo(
    student_id: int,
    photo: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access only", 403, "FORBIDDEN")
    with connect() as c:
        row = c.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
    if not row:
        raise ApiError("Student not found", 404, "NOT_FOUND")
    try:
        path = await save_profile_photo(photo, subdir="students", stem=row["roll_no"])
        with connect() as c:
            c.execute("UPDATE students SET photo_path=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (path, student_id))
            audit(c, user.username, "PHOTO", "student", row["roll_no"])
        return ok({"photo_path": path})
    except PhotoUploadError as e:
        raise ApiError(str(e), 400, "UPLOAD_ERROR")


@router.post("/{student_id}/photo/delete")
async def student_photo_delete(
    student_id: int,
    user: CurrentUser = Depends(get_current_user),
):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access only", 403, "FORBIDDEN")
    with connect() as c:
        row = c.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        if not row:
            raise ApiError("Student not found", 404, "NOT_FOUND")
        c.execute("UPDATE students SET photo_path=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?", (student_id,))
        audit(c, user.username, "PHOTO_DELETE", "student", row["roll_no"])
    return ok({"photo_path": None})


@router.delete("/{student_id}")
async def student_delete(student_id: int, user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access only", 403, "FORBIDDEN")
    with connect() as c:
        row = c.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        if not row:
            raise ApiError("Student not found", 404, "NOT_FOUND")
        roll_no = row["roll_no"]
        c.execute("DELETE FROM attendance_marks WHERE roll_no=?", (roll_no,))
        c.execute("DELETE FROM sms_queue WHERE roll_no=?", (roll_no,))
        c.execute("DELETE FROM checklist WHERE roll_no=?", (roll_no,))
        c.execute("DELETE FROM users WHERE student_roll_no=? OR username=?", (roll_no, roll_no))
        c.execute("DELETE FROM students WHERE id=?", (student_id,))
        audit(c, user.username, "DELETE", "student", roll_no)
    return ok({"deleted": True, "id": student_id})


# Halted certificate upload (§4.5) — accepts the request, returns success without writing anything
@router.post("/{student_id}/certificate/{doc_type}")
async def certificate_upload(student_id: int, doc_type: str, user: CurrentUser = Depends(get_current_user)):
    """HALTED per §4.5 — certificate upload disabled. Route kept for backward-compat."""
    return ok({"message": "Certificate upload is currently disabled"})
