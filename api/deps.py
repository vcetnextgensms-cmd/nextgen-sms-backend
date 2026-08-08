"""FastAPI dependencies for api/ routes — the JSON-API equivalent of
webapp/auth_session.py's get_current_user(). Same must_change_password
choke-point pattern (plan §3.3).

Supports:
1. Authorization: Bearer <access_token> header (JSON API requests via apiFetch)
2. token query parameter (direct browser downloads / tabs)
3. sms_refresh cookie (httpOnly cookie set during login / refresh)
"""

from __future__ import annotations

from fastapi import Cookie, Header, Query

from api.auth_token import REFRESH_COOKIE, read_access_token, read_refresh_token
from api.envelope import ApiError


class CurrentUser:
    """Mirrors webapp/auth_session.py's CurrentUser exactly."""

    def __init__(self, username: str, role: str, student_roll_no: str | None, must_change_password: bool = False):
        self.username = username
        self.role = role
        self.student_roll_no = student_roll_no
        self.must_change_password = must_change_password


def _extract_user_payload(
    authorization: str | None,
    token: str | None,
    sms_refresh: str | None,
) -> dict | None:
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization.removeprefix("Bearer ").strip()
        data = read_access_token(raw_token)
        if data:
            return data

    if token:
        data = read_access_token(token) or read_refresh_token(token)
        if data:
            return data

    if sms_refresh:
        data = read_refresh_token(sms_refresh)
        if data:
            return data

    return None


def get_current_user(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
    sms_refresh: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
) -> CurrentUser:
    data = _extract_user_payload(authorization, token, sms_refresh)

    if not data:
        raise ApiError("Not authenticated", status_code=401, code="NOT_AUTHENTICATED")

    user = CurrentUser(
        username=data["username"],
        role=data["role"],
        student_roll_no=data.get("student_roll_no"),
        must_change_password=bool(data.get("must_change_password")),
    )

    if user.must_change_password:
        raise ApiError(
            "Password change required before continuing",
            status_code=403,
            code="MUST_CHANGE_PASSWORD",
        )

    return user


def get_current_user_allow_pending(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
    sms_refresh: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
) -> CurrentUser:
    data = _extract_user_payload(authorization, token, sms_refresh)

    if not data:
        raise ApiError("Not authenticated", status_code=401, code="NOT_AUTHENTICATED")

    return CurrentUser(
        username=data["username"],
        role=data["role"],
        student_roll_no=data.get("student_roll_no"),
        must_change_password=bool(data.get("must_change_password")),
    )


def get_optional_user(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
    sms_refresh: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
) -> CurrentUser | None:
    data = _extract_user_payload(authorization, token, sms_refresh)
    if not data:
        return None
    return CurrentUser(
        username=data["username"],
        role=data["role"],
        student_roll_no=data.get("student_roll_no"),
        must_change_password=bool(data.get("must_change_password")),
    )

