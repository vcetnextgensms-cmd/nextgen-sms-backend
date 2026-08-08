"""Group 1 — Auth API. OPTION_B_REWRITE_PLAN.md §2 group 1 / §3.3 / §3.4.

Route mapping (old -> new, per plan §3.2 pattern):
  POST /login                    -> POST /api/auth/login
  POST /logout                   -> POST /api/auth/logout
  GET/POST /force-password-change -> GET /api/auth/me (state) + POST /api/auth/change-password
  (new, needed by token model, no old equivalent) -> POST /api/auth/refresh

Reuses database.py's auth(), change_password(), audit(), connect() —
unchanged, per plan §3.5 ("reuse these modules, don't rewrite their
internals"). The only new code here is the token issuance/verification
and the JSON envelope; the actual credential check and password-change
logic is identical to the Jinja app's.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

import email_service
from database import (
    audit, auth, change_password, connect,
    create_password_reset, find_user_by_email, mark_email_verified,
    register_student, request_otp, reset_password_by_email,
    reset_password_with_token, verify_otp,
)
from webapp.config import SESSION_COOKIE  # noqa: F401  (kept for reference; API uses REFRESH_COOKIE)

from api.auth_token import (
    REFRESH_COOKIE, REFRESH_MAX_AGE,
    make_access_token, make_refresh_token, read_refresh_token,
)
from api.deps import CurrentUser, get_current_user_allow_pending, get_optional_user
from api.envelope import ApiError, ok

from api.rate_limit import is_locked, record_failure, record_success

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Role-based post-login destination — same table as webapp/routes/auth.py,
# duplicated intentionally rather than imported: that dict is private to
# the Jinja route module and encodes URL paths (Jinja routes), whereas this
# one encodes React route names. Same DATA, different SHAPE, so a shared
# import would just be re-splitting them back apart at the call site.
_DEST_BY_ROLE = {"FACULTY": "/account", "HOD": "/account", "STUDENT": "/profile"}


class LoginBody(BaseModel):
    username: str
    password: str


class ChangePasswordBody(BaseModel):
    old_password: str
    new_password: str
    confirm_password: str


class RegisterBody(BaseModel):
    roll_no: str
    username: str
    password: str
    confirm_password: str
    full_name: str | None = None
    email: str


class ForgotPasswordBody(BaseModel):
    username: str


class ResetPasswordBody(BaseModel):
    token: str
    new_password: str
    confirm_password: str


class SendOtpBody(BaseModel):
    email: str
    purpose: str  # "REGISTER" or "RESET_PASSWORD"


class VerifyOtpBody(BaseModel):
    email: str
    purpose: str
    code: str


class ResetPasswordOtpBody(BaseModel):
    email: str
    code: str
    new_password: str
    confirm_password: str


def _cookie_settings() -> tuple[bool, str]:
    env = os.environ.get("SMS_ENV", "development").strip().lower()
    secure_raw = os.environ.get("SMS_COOKIE_SECURE")
    same_site = os.environ.get("SMS_COOKIE_SAMESITE")
    if secure_raw is None:
        secure = env == "production"
    else:
        secure = secure_raw.strip().lower() in {"1", "true", "yes", "on"}
    if same_site is None or not same_site.strip():
        same_site_value = "none" if secure else "lax"
    else:
        same_site_value = same_site.strip().lower()
    if same_site_value == "none":
        secure = True
    return secure, same_site_value


_COOKIE_SECURE, _COOKIE_SAMESITE = _cookie_settings()


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=REFRESH_MAX_AGE,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite=_COOKIE_SAMESITE,
        path="/",
    )


@router.post("/login")
async def login(body: LoginBody, request: Request):
    if not body.username.strip() or not body.password:
        raise ApiError("Enter username and password", code="MISSING_CREDENTIALS")

    # — Rate limit (plan §3.4 / Item 3)
    # WHY keyed by IP+username, not username alone: prevents one attacker
    # from locking out a real user's username by deliberately failing it
    # from a different IP (a shared-key-by-username-only limiter is itself
    # a denial-of-service vector against legitimate users).
    limiter_key = f"{request.client.host if request.client else 'unknown'}:{body.username.strip().lower()}"
    if is_locked(limiter_key):
        raise ApiError("Too many attempts. Try again later.", status_code=429, code="RATE_LIMITED")

    row = auth(body.username, body.password)
    if not row:
        record_failure(limiter_key)
        raise ApiError("Invalid credentials or inactive account", status_code=401, code="INVALID_CREDENTIALS")
    record_success(limiter_key)

    with connect() as c:
        audit(c, row["username"], "LOGIN", "session", row["role"])

    must_change = bool(row["must_change_password"])
    access = make_access_token(row["username"], row["role"], row["student_roll_no"], must_change)
    refresh = make_refresh_token(row["username"], row["role"], row["student_roll_no"], must_change)

    resp = ok({
        "access_token": access,
        "expires_in": 900,
        "user": {
            "username": row["username"],
            "role": row["role"],
            "student_roll_no": row["student_roll_no"],
            "must_change_password": must_change,
        },
        "redirect": "/force-password-change" if must_change else _DEST_BY_ROLE[row["role"]],
    })
    _set_refresh_cookie(resp, refresh)
    return resp


@router.post("/refresh")
async def refresh(request: Request):
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise ApiError("Not authenticated", status_code=401, code="NOT_AUTHENTICATED")
    data = read_refresh_token(token)
    if not data:
        raise ApiError("Session expired, please log in again", status_code=401, code="TOKEN_INVALID")

    # — Re-check must_change_password against the DB, not just the old
    # refresh token's payload (auth_token.py's module docstring explains
    # why: a HOD may reset someone's account server-side between refreshes,
    # and the flag needs to reflect that on the very next access token).
    with connect() as c:
        urow = c.execute("SELECT must_change_password FROM users WHERE username=%s", (data["username"],)).fetchone()
    must_change = bool(urow["must_change_password"]) if urow else bool(data.get("must_change_password"))

    access = make_access_token(data["username"], data["role"], data.get("student_roll_no"), must_change)
    new_refresh = make_refresh_token(data["username"], data["role"], data.get("student_roll_no"), must_change)

    resp = ok({
        "access_token": access,
        "expires_in": 900,
        "user": {
            "username": data["username"],
            "role": data["role"],
            "student_roll_no": data.get("student_roll_no"),
            "must_change_password": must_change,
        },
    })
    _set_refresh_cookie(resp, new_refresh)  # WHY reissue: sliding 7-day window, same behavior as the old session cookie's implicit renewal-on-use pattern.
    return resp


@router.post("/logout")
async def logout(request: Request, user: CurrentUser | None = Depends(get_optional_user)):
    if user:
        try:
            with connect() as c:
                audit(c, user.username, "LOGOUT", "session", "")
        except Exception:
            pass
    resp = ok({"ok": True})
    resp.delete_cookie(REFRESH_COOKIE, path="/")
    resp.delete_cookie(REFRESH_COOKIE, path="/api/auth")
    resp.delete_cookie(REFRESH_COOKIE)
    return resp



@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user_allow_pending)):
    # WHY allow_pending here specifically: the frontend's route guard
    # (plan §3.3) needs to read must_change_password to decide whether to
    # redirect to /force-password-change in the first place — it can't do
    # that if this endpoint itself 403s for a flagged user.
    return ok({
        "username": user.username,
        "role": user.role,
        "student_roll_no": user.student_roll_no,
        "must_change_password": user.must_change_password,
    })


@router.post("/change-password")
async def change_password_route(
    body: ChangePasswordBody,
    user: CurrentUser = Depends(get_current_user_allow_pending),
):
    if body.new_password != body.confirm_password:
        raise ApiError("New passwords do not match", code="PASSWORD_MISMATCH")
    try:
        change_password(user.username, body.old_password, body.new_password)
    except ValueError as exc:
        raise ApiError(str(exc), code="PASSWORD_CHANGE_FAILED") from exc

    with connect() as c:
        audit(c, user.username, "FORCED_PASSWORD_CHANGE" if user.must_change_password else "CHANGE_PASSWORD", "user", user.username)

    # — Reissue both tokens with the flag cleared (mirrors webapp/routes/
    # auth.py's cookie-reissue comment exactly): change_password() already
    # cleared the DB flag, but THIS request's existing access/refresh
    # tokens are the old signed payloads with must_change_password still
    # True — without reissuing, the frontend would still be holding a
    # stale flagged token until the next refresh cycle.
    access = make_access_token(user.username, user.role, user.student_roll_no, must_change_password=False)
    new_refresh = make_refresh_token(user.username, user.role, user.student_roll_no, must_change_password=False)

    resp = ok({
        "access_token": access,
        "expires_in": 900,
        "redirect": _DEST_BY_ROLE[user.role],
    })
    _set_refresh_cookie(resp, new_refresh)
    return resp

@router.post("/register")
async def register(body: RegisterBody, request: Request):
    """Student self-registration route."""
    if not body.email or not body.email.strip():
        raise ApiError("Email address is required for account creation", code="EMAIL_REQUIRED")
    if body.password != body.confirm_password:
        raise ApiError("Passwords do not match", code="PASSWORD_MISMATCH")

    # Same IP-keyed limiter shape as /login (Item 3 / SECURITY_HANDOFF #5)
    # — prevents scripted roll-number enumeration against this endpoint.
    limiter_key = f"register:{request.client.host if request.client else 'unknown'}"
    if is_locked(limiter_key):
        raise ApiError("Too many attempts. Try again later.", status_code=429, code="RATE_LIMITED")

    try:
        register_student(body.roll_no, body.username, body.password, full_name=body.full_name, email=body.email)
    except ValueError as exc:
        record_failure(limiter_key)
        raise ApiError(str(exc), code="REGISTRATION_FAILED") from exc
    record_success(limiter_key)

    return ok({"message": "Account created. You can now log in.", "email": (body.email or "").strip().lower() or None})


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordBody, request: Request):
    """Issues password reset token."""
    limiter_key = f"forgot:{request.client.host if request.client else 'unknown'}:{body.username.strip().lower()}"
    if is_locked(limiter_key):
        raise ApiError("Too many attempts. Try again later.", status_code=429, code="RATE_LIMITED")

    token = create_password_reset(body.username)
    if not token:
        record_failure(limiter_key)
    else:
        record_success(limiter_key)

    # WHY the same response either way: revealing "no such user" here would
    # let an attacker enumerate valid usernames (identical reasoning to
    # rate_limit.py's login-lockout message and /login's generic 401).
    resp_data = {
        "message": "If that account exists, a password reset link has been generated.",
    }
    if token:
        resp_data["reset_link"] = f"/reset-password?token={token}"
        resp_data["token"] = token
    return ok(resp_data)


@router.post("/reset-password")
async def reset_password(body: ResetPasswordBody, request: Request):
    if body.new_password != body.confirm_password:
        raise ApiError("New passwords do not match", code="PASSWORD_MISMATCH")

    limiter_key = f"resetpw:{request.client.host if request.client else 'unknown'}"
    if is_locked(limiter_key):
        raise ApiError("Too many attempts. Try again later.", status_code=429, code="RATE_LIMITED")

    try:
        reset_password_with_token(body.token, body.new_password)
    except ValueError as exc:
        record_failure(limiter_key)
        raise ApiError(str(exc), code="RESET_FAILED") from exc
    record_success(limiter_key)

    return ok({"message": "Password updated. You can now log in."})


# ---------------------------------------------------------------------------
# Email OTP — used by both registration (verify email) and Forgot Password
# (reset via code instead of a link).
# ---------------------------------------------------------------------------

@router.post("/send-otp")
async def send_otp(body: SendOtpBody, request: Request):
    """Sends a 6-digit OTP to email for the given purpose."""
    purpose = body.purpose.strip().upper()
    if purpose not in ("REGISTER", "RESET_PASSWORD"):
        raise ApiError("Invalid purpose", code="INVALID_PURPOSE")
    email = body.email.strip().lower()
    if not email or "@" not in email:
        raise ApiError("Enter a valid email address", code="INVALID_EMAIL")

    # Per-email+IP limiter — same shape as /login's, prevents an attacker
    # from spamming a stranger's inbox with OTP requests.
    limiter_key = f"otp:{request.client.host if request.client else 'unknown'}:{email}"
    if is_locked(limiter_key):
        raise ApiError("Too many attempts. Try again later.", status_code=429, code="RATE_LIMITED")

    if purpose == "RESET_PASSWORD":
        user = find_user_by_email(email)
        if not user:
            record_success(limiter_key)  # not a failure of the requester's — just no account to email
            return ok({"message": "If that email is registered, a verification code has been sent."})

    code = request_otp(email, purpose)

    try:
        email_service.send_otp_email(email, code, purpose)
        print(f"[OTP] Real OTP email sent for {purpose} to {email}")
    except email_service.EmailNotConfiguredError as exc:
        raise ApiError("Email service is not configured in .env. Please set SMTP_HOST, SMTP_USERNAME, and SMTP_PASSWORD.", status_code=503, code="EMAIL_NOT_CONFIGURED") from exc
    except Exception as exc:
        print(f"[OTP Error] Failed to send email via SMTP ({exc}).")
        record_failure(limiter_key)
        raise ApiError("Could not send verification email. Please verify SMTP_USERNAME and SMTP_PASSWORD (16-char Gmail App Password) in .env.", status_code=502, code="EMAIL_SEND_FAILED") from exc

    record_success(limiter_key)
    return ok({"message": "Verification code sent to your email. It expires in 10 minutes."})


@router.post("/verify-otp")
async def verify_otp_route(body: VerifyOtpBody, request: Request):
    """Verifies a submitted OTP code."""
    purpose = body.purpose.strip().upper()
    if purpose not in ("REGISTER", "RESET_PASSWORD"):
        raise ApiError("Invalid purpose", code="INVALID_PURPOSE")
    email = body.email.strip().lower()

    limiter_key = f"otpverify:{request.client.host if request.client else 'unknown'}:{email}"
    if is_locked(limiter_key):
        raise ApiError("Too many attempts. Try again later.", status_code=429, code="RATE_LIMITED")

    try:
        verify_otp(email, purpose, body.code)
    except ValueError as exc:
        record_failure(limiter_key)
        raise ApiError(str(exc), code="OTP_VERIFY_FAILED") from exc
    record_success(limiter_key)

    if purpose == "REGISTER":
        mark_email_verified(email)

    return ok({"message": "Verified.", "verified": True})


@router.post("/reset-password-otp")
async def reset_password_otp(body: ResetPasswordOtpBody, request: Request):
    """Resets user password via OTP code."""
    if body.new_password != body.confirm_password:
        raise ApiError("New passwords do not match", code="PASSWORD_MISMATCH")

    email = body.email.strip().lower()
    limiter_key = f"resetotp:{request.client.host if request.client else 'unknown'}:{email}"
    if is_locked(limiter_key):
        raise ApiError("Too many attempts. Try again later.", status_code=429, code="RATE_LIMITED")

    try:
        verify_otp(email, "RESET_PASSWORD", body.code)
        reset_password_by_email(email, body.new_password)
    except ValueError as exc:
        record_failure(limiter_key)
        raise ApiError(str(exc), code="RESET_FAILED") from exc
    record_success(limiter_key)

    return ok({"message": "Password updated. You can now log in."})
