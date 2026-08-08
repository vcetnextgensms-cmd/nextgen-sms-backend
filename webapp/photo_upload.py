"""Shared profile-photo upload handling (HANDOFF.md "Item B — Photo upload").

One validate/resize/save implementation reused by every photo upload route —
student self-upload, HOD uploading any student's photo, and HOD/FACULTY
uploading their own account photo — per HANDOFF's explicit instruction not
to duplicate this logic across route files.

Defaults (flagged in HANDOFF as a non-blocking judgment call, picked here
per Boss's confirmation): 2MB upload cap, resized/re-encoded to 400x400.

Validates actual image content via Pillow (not the client-supplied filename
or extension) before writing anything to disk, and always re-encodes on
save — this both normalizes the format to JPEG and strips anything in the
original file that isn't image pixel data.
"""

import uuid
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # 2MB cap
TARGET_SIZE = (400, 400)

# — uploads root
# WHY moved out of static/: static/ is served publicly (unauthenticated) via
# FastAPI's StaticFiles mount in main.py. uploads/ holds student photos,
# certificates, and calendar files, which must only be reachable through the
# auth-gated /files/... route in webapp/routes/protected_files.py. Keeping
# uploads/ as a SIBLING of static/ (not nested inside it) means the public
# static mount can never physically reach these files, even by mistake.
UPLOADS_DIR = Path(__file__).parent / "uploads"


class PhotoUploadError(ValueError):
    pass


async def save_profile_photo(file: UploadFile, *, subdir: str, stem: str) -> str:
    """Validate, resize, and save an uploaded photo.

    subdir: "students" or "users" — keeps the two photo sets apart on disk.
    stem: a filesystem-safe identifier for the owner (roll_no or username).

    Returns the relative URL path (e.g. "/static/uploads/students/xyz.jpg")
    to store in the owning row's photo_path column. Raises PhotoUploadError
    on anything invalid — oversized file, non-image content, unreadable
    data — with a message safe to show the user.
    """
    if not file or not file.filename:
        raise PhotoUploadError("No file was selected")

    raw = await file.read()
    if not raw:
        raise PhotoUploadError("No file was selected")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise PhotoUploadError("Photo must be smaller than 2MB")

    try:
        img = Image.open(__import__("io").BytesIO(raw))
        img.verify()  # first pass: confirm it's actually image data
        img = Image.open(__import__("io").BytesIO(raw))  # verify() consumes the parser, reopen
        img.load()
    except (UnidentifiedImageError, OSError):
        raise PhotoUploadError("That file isn't a readable image")

    img = img.convert("RGB")
    img.thumbnail(TARGET_SIZE, Image.LANCZOS)
    # Pad to an exact square so every photo renders consistently regardless
    # of the source aspect ratio, rather than stretching/cropping content.
    canvas = Image.new("RGB", TARGET_SIZE, (245, 247, 251))  # matches --bg token
    offset = ((TARGET_SIZE[0] - img.width) // 2, (TARGET_SIZE[1] - img.height) // 2)
    canvas.paste(img, offset)

    target_dir = UPLOADS_DIR / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = "".join(ch for ch in stem.lower() if ch.isalnum() or ch in ("-", "_")) or "photo"
    filename = f"{safe_stem}-{uuid.uuid4().hex[:8]}.jpg"
    canvas.save(target_dir / filename, format="JPEG", quality=85)

    # Served via the auth-gated /files/ route, NOT /static/ — see protected_files.py
    return f"/files/{subdir}/{filename}"


MAX_CERT_BYTES = 5 * 1024 * 1024  # 5MB cap
CERT_ALLOWED_EXT = (".pdf", ".jpg", ".jpeg", ".png")


async def save_certificate(file: UploadFile, *, stem: str, doc_type: str) -> str:
    """Save a 10th/12th/diploma certificate upload. Unlike photos, certificates
    are stored as-is (PDF or image) rather than re-encoded, since re-encoding
    a scanned certificate can degrade legibility. Only a file-type/size check
    is applied, not content validation. doc_type e.g. 'tenth', 'twelfth', 'diploma'.
    """
    if not file or not file.filename:
        raise PhotoUploadError("No file was selected")
    ext = Path(file.filename).suffix.lower()
    if ext not in CERT_ALLOWED_EXT:
        raise PhotoUploadError("Certificates must be a PDF, JPG, or PNG file")
    raw = await file.read()
    if not raw:
        raise PhotoUploadError("No file was selected")
    if len(raw) > MAX_CERT_BYTES:
        raise PhotoUploadError("Certificate file must be smaller than 5MB")

    target_dir = UPLOADS_DIR / "certificates"
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = "".join(ch for ch in stem.lower() if ch.isalnum() or ch in ("-", "_")) or "student"
    filename = f"{safe_stem}-{doc_type}-{uuid.uuid4().hex[:8]}{ext}"
    (target_dir / filename).write_bytes(raw)

    # Served via /files/certificates/... which restricts a student to their
    # OWN filename (matched by roll-number stem) — see protected_files.py.
    # This is the highest-sensitivity upload category (10th/12th/diploma
    # scans), so it must never be reachable through the public static mount.
    return f"/files/certificates/{filename}"


MAX_CALENDAR_BYTES = 8 * 1024 * 1024  # 8MB cap — timetable/calendar scans can be larger than a single certificate page
CALENDAR_ALLOWED_EXT = (".pdf", ".jpg", ".jpeg", ".png")


async def save_calendar_file(file: UploadFile, *, semester_code: str, kind: str) -> str:
    """Save an Academic Calendar upload (Timetable or Calendar image/PDF)
    for a semester. Same as save_certificate — stored as-is, not
    re-encoded, since these are read-only reference documents where
    legibility matters more than normalization. HOD-only, enforced at the
    route level, not here.
    kind: 'timetable' or 'calendar' (used only for the filename).
    """
    if not file or not file.filename:
        raise PhotoUploadError("No file was selected")
    ext = Path(file.filename).suffix.lower()
    if ext not in CALENDAR_ALLOWED_EXT:
        raise PhotoUploadError("File must be a PDF, JPG, or PNG file")
    raw = await file.read()
    if not raw:
        raise PhotoUploadError("No file was selected")
    if len(raw) > MAX_CALENDAR_BYTES:
        raise PhotoUploadError("File must be smaller than 8MB")

    target_dir = UPLOADS_DIR / "academic_calendar"
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = "".join(ch for ch in semester_code.lower() if ch.isalnum() or ch in ("-", "_")) or "semester"
    filename = f"{safe_stem}-{kind}-{uuid.uuid4().hex[:8]}{ext}"
    (target_dir / filename).write_bytes(raw)

    return f"/files/academic_calendar/{filename}"
