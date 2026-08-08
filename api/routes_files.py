"""Group 7 — Protected file serving (§7.7).

Auth-gated file serving — ported from webapp/routes/protected_files.py.
DO NOT add uploads to any public static mount. This is the ONLY way
to reach uploaded files. See §7.7 for the historical data-exposure gap
this route fixes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from api.deps import CurrentUser, get_current_user
from api.envelope import ApiError

# Derive from the same UPLOADS_DIR that writes the files — never a separate
# Path chain that might count directories wrong (§7.7 rationale).
from webapp.photo_upload import UPLOADS_DIR as _UPLOADS_DIR

router = APIRouter(tags=["files"])

# WHY .resolve(): traversal guard compares against an already-resolved target;
# if root is unresolved, the membership check silently never matches.
UPLOADS_ROOT = _UPLOADS_DIR.resolve()


def _authorize(user: CurrentUser, subdir: str, filename: str) -> None:
    """Raise 403 if this user shouldn't see this file.

    HOD/FACULTY: always allowed, any subdir.
    WHY uppercase comparison (§7.7): role is stored/compared uppercase everywhere
    in this app matching the CHECK constraint. A lowercase comparison here would
    silently 403 all staff on certificates, because staff accounts have
    student_roll_no = NULL and would fall through to the certificates check.
    """
    if user.role in ("HOD", "FACULTY"):
        return

    if subdir in ("students", "users", "academic_calendar"):
        return

    if subdir == "certificates":
        if not user.student_roll_no:
            raise ApiError("Not authorized to view this file", 403, "FORBIDDEN")
        own_stem = user.student_roll_no.lower()
        if not filename.lower().startswith(own_stem + "-"):
            raise ApiError("Not authorized to view this file", 403, "FORBIDDEN")
        return

    # Unknown/unknown subdir — default deny (§7.7)
    raise ApiError("Not authorized to view this file", 403, "FORBIDDEN")


@router.get("/api/files/{subdir}/{filename}")
async def serve_file(
    subdir: str,
    filename: str,
    user: CurrentUser = Depends(get_current_user),
):
    # Path traversal guard — must use .resolve() on target AND root
    target = (UPLOADS_ROOT / subdir / filename).resolve()
    if UPLOADS_ROOT not in target.parents and target != UPLOADS_ROOT:
        raise ApiError("Not found", 404, "NOT_FOUND")
    if not target.is_file():
        raise ApiError("Not found", 404, "NOT_FOUND")

    _authorize(user, subdir, filename)
    return FileResponse(target)
