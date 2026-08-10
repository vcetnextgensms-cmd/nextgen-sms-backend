"""Response envelope — OPTION_B_REWRITE_PLAN.md §3.1.

Every /api/* route returns one of:
  { "data": ... }
  { "error": { "message": "...", "code": "OPTIONAL_MACHINE_READABLE_CODE" } }

WHY: the frontend's apiFetch() wrapper (frontend/src/api/client.ts) checks
for `error` uniformly instead of every call site guessing whether a 4xx
body is FastAPI's default {detail: ...} or something else. One shape,
everywhere — do not return bare JSON from any route in api/.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.requests import Request
from fastapi.responses import JSONResponse


def ok(data: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content={"data": jsonable_encoder(data)}, status_code=status_code)

# WHY routes must call set_cookie on the JSONResponse ok() returns, never
# on a separately Depends-injected Response parameter: FastAPI only merges
# an injected Response's headers/cookies onto the route's return value when
# that return value is a plain dict/model FastAPI itself wraps into a
# Response. Every route here returns its own JSONResponse (via ok()) - a
# handler returning a Response object directly bypasses that merge step,
# so response.set_cookie() on the injected parameter is silently dropped.
# This bit us for real in Group 1's live test (refresh cookie never
# arrived) - caught before calling the group done, per standing method.
# Pattern going forward: call ok(...) first, capture the JSONResponse, THEN
# call .set_cookie()/.delete_cookie() on THAT object, and return it.


class ApiError(HTTPException):
    """Raise this from any route/dependency in api/ instead of a bare
    HTTPException — the exception handler below (registered in
    api/app.py) converts it to the {error:{message,code}} envelope.
    Bare HTTPException still works (handled too) but won't carry a `code`.
    """

    def __init__(self, message: str, status_code: int = 400, code: str | None = None):
        super().__init__(status_code=status_code, detail=message)
        self.message = message
        self.code = code


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    body: dict[str, Any] = {"message": exc.message}
    if exc.code:
        body["code"] = exc.code
    return JSONResponse(content={"error": body}, status_code=exc.status_code)


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    # WHY: catches HTTPException raised by FastAPI internals (e.g. 404 on
    # an unmatched route, validation-adjacent 4xxs) that never went through
    # ApiError — keeps the envelope consistent even for framework-level
    # errors, per SECURITY_HANDOFF #3's "catch-all exception handler" item.
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return JSONResponse(content={"error": {"message": detail}}, status_code=exc.status_code)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # WHY: last-resort catch-all (SECURITY_HANDOFF #3) — never leak a raw
    # traceback/exception string to the client. Real detail goes to server
    # logs only.
    import logging
    logging.getLogger("sms.api").exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        content={"error": {"message": "Internal server error"}},
        status_code=500,
    )
