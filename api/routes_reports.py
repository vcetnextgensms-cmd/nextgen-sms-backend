"""Problem Reports API — Allows users to report issues and Admin/HOD to view and resolve them.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from database import create_problem_report, get_problem_reports, update_problem_report_status
from api.deps import CurrentUser, get_current_user
from api.envelope import ApiError, ok

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _require_admin(user: CurrentUser):
    if user.role != "HOD":
        raise ApiError("Only Admin / HOD can view and manage problem reports", 403, "FORBIDDEN")


class SubmitReportBody(BaseModel):
    category: str = "General"
    subject: str
    description: str


class UpdateReportStatusBody(BaseModel):
    status: str
    admin_notes: str | None = None


@router.post("/submit", status_code=201)
async def submit_report(body: SubmitReportBody, user: CurrentUser = Depends(get_current_user)):
    try:
        create_problem_report(
            username=user.username,
            role=user.role,
            category=body.category,
            subject=body.subject,
            description=body.description,
        )
        return ok({"message": "Problem report submitted successfully. An administrator will review it."})
    except ValueError as exc:
        raise ApiError(str(exc), code="VALIDATION_ERROR") from exc


@router.get("")
async def list_reports(user: CurrentUser = Depends(get_current_user)):
    _require_admin(user)
    reports = get_problem_reports()
    return ok({"reports": [dict(r) for r in reports]})


@router.patch("/{report_id}/status")
async def update_report_status(report_id: int, body: UpdateReportStatusBody, user: CurrentUser = Depends(get_current_user)):
    _require_admin(user)
    try:
        update_problem_report_status(
            report_id=report_id,
            status=body.status,
            admin_notes=body.admin_notes,
            actor=user.username,
        )
        return ok({"message": "Report status updated successfully."})
    except ValueError as exc:
        raise ApiError(str(exc), code="VALIDATION_ERROR") from exc
