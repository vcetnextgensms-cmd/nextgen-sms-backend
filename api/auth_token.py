"""Token-based auth — OPTION_B_REWRITE_PLAN.md §3.3, Option 3a (confirmed
by Boss over 3b): httpOnly refresh cookie carries the long-lived
credential; the SPA holds a short-lived access token in memory (never
localStorage — this app handles Aadhaar numbers, see §3.3's reasoning).

Two tokens, two lifetimes:
  - access token:  15 min,  returned in the JSON body, held in a JS
                    variable by the frontend, sent as `Authorization: Bearer`.
  - refresh token: 7 days (matches old SESSION_MAX_AGE), httpOnly+secure
                    cookie, never touched by JS, used only to mint a new
                    access token via POST /api/auth/refresh.

Both are itsdangerous signed payloads (same primitive as the old
webapp/auth_session.py, same SECRET_KEY) — not a parallel crypto scheme,
just two serializers with different salts/max_ages instead of one cookie.

— must_change_password (plan §3.3: "stays a first-class part of whatever
the token/session payload is")
WHY it's in BOTH tokens, not just the refresh token: get_current_user()
below only ever decodes the access token (the refresh token is opaque to
every route except /api/auth/refresh), so if the flag lived only in the
refresh token, a flagged user's access token would silently omit it and
every route's gate would fail open. Re-embedding it on every refresh
(see refresh_access_token()) keeps it correct even if the DB flag
changes between refreshes (e.g. a HOD manually resets someone's account).
"""

import hashlib

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from webapp.config import SECRET_KEY

ACCESS_MAX_AGE = 60 * 15          # 15 minutes
REFRESH_MAX_AGE = 60 * 60 * 24 * 7  # 7 days — matches old SESSION_MAX_AGE
REFRESH_COOKIE = "sms_refresh"
RESET_MAX_AGE = 60 * 30            # 30 minutes — short-lived, single-use (see password_resets.used)

_access_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="sms-api-access")
_refresh_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="sms-api-refresh")
# Separate salt so a reset token can never be replayed against the
# access/refresh serializers (or vice versa) even though all three share
# SECRET_KEY — itsdangerous mixes the salt into the signature itself.
_reset_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="sms-api-password-reset")


def _payload(username: str, role: str, student_roll_no: str | None, must_change_password: bool) -> dict:
    return {
        "username": username,
        "role": role,
        "student_roll_no": student_roll_no,
        "must_change_password": must_change_password,
    }


def make_access_token(username: str, role: str, student_roll_no: str | None, must_change_password: bool = False) -> str:
    return _access_serializer.dumps(_payload(username, role, student_roll_no, must_change_password))


def make_refresh_token(username: str, role: str, student_roll_no: str | None, must_change_password: bool = False) -> str:
    return _refresh_serializer.dumps(_payload(username, role, student_roll_no, must_change_password))


def read_access_token(token: str) -> dict | None:
    try:
        return _access_serializer.loads(token, max_age=ACCESS_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def read_refresh_token(token: str) -> dict | None:
    try:
        return _refresh_serializer.loads(token, max_age=REFRESH_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def make_reset_token(username: str) -> str:
    return _reset_serializer.dumps({"username": username})


def read_reset_token(token: str) -> dict | None:
    try:
        return _reset_serializer.loads(token, max_age=RESET_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def hash_reset_token(token: str) -> str:
    # WHY hash before storing (database.py's password_resets.token_hash):
    # the token itself is a bearer credential for 30 minutes — same
    # reasoning as never storing a plaintext password, applied to a
    # short-lived secret instead of a long-lived one.
    return hashlib.sha256(token.encode()).hexdigest()
