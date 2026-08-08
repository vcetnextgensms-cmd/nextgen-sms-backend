"""New JSON API app — OPTION_B_REWRITE_PLAN.md §5, "two fully separate
processes/ports from day one" (Boss's call over the shared-process option).
Runs alongside the existing webapp.main:app (Jinja, port 8000 by
convention) on its own port — see run_api.py at the project root.

Every SECURITY_HANDOFF.md item that's "built once, correctly, from the
start" per plan §1's table lands here:
  #1  docs_url=None etc.        -> FastAPI(...) kwargs below
  #3  catch-all exception handler -> registered below, JSON not plain-text
  #4  cookie secure flag        -> api/routes_auth.py's refresh cookie, secure=True
  #5  /files/ rate limit        -> api/routes_files.py (Group 7, built)
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from api.envelope import ApiError, api_error_handler, http_exception_handler, unhandled_exception_handler
from api.firewall import SecurityFirewallMiddleware
from api.routes_auth import router as auth_router
from api.routes_dashboard import router as dashboard_router
from api.routes_attendance import router as attendance_router
from api.routes_students import router as students_router
from api.routes_faculty import router as faculty_router
from api.routes_subjects import router as subjects_router
from api.routes_academic_calendar import router as academic_calendar_router
from api.routes_me import router as me_router
from api.routes_files import router as files_router
from api.routes_reports import router as reports_router

app = FastAPI(
    title="SMS API",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

import os

def _split_env(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]

allowed_origins_list = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
]
allowed_origins_list.extend(_split_env(os.environ.get("ALLOWED_ORIGINS")))
allowed_origins_list.extend(_split_env(os.environ.get("FRONTEND_ORIGIN")))
allowed_origins_list.extend(_split_env(os.environ.get("FRONTEND_ORIGINS")))

origin_regex = os.environ.get(
    "ALLOWED_ORIGIN_REGEX",
    r"http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)(:\d+)?|https://.*\.(vercel\.app|onrender\.com|firebaseapp\.com|web\.app|trycloudflare\.com|ngrok-free\.app|ngrok-free\.dev|ngrok\.io)",
)

app.add_middleware(SecurityFirewallMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins_list,
    allow_origin_regex=origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(auth_router)           # Group 1 — Auth
app.include_router(dashboard_router)      # Group 2 — Dashboard
app.include_router(attendance_router)     # Group 3 — Attendance
app.include_router(students_router)       # Group 4 — Students
app.include_router(faculty_router)        # Group 5 — Faculty
app.include_router(subjects_router)       # Group 5 — Subjects + Semesters
app.include_router(academic_calendar_router)  # Group 5 — Academic Calendar
app.include_router(me_router)             # Group 6 — Self-service
app.include_router(files_router)          # Group 7 — Protected files
app.include_router(reports_router)        # Problem Reports


@app.get("/")
async def root():
    return {"status": "ok", "message": "VCET CSD SMS Backend API is running"}


@app.get("/api/health")
async def health():
    return {"data": {"ok": True}}


@app.on_event("startup")
def startup_db_init():
    try:
        import database
        database.init_db()
        print("[*] Database initialized successfully on startup.")
    except Exception as e:
        print(f"[!] Database init error: {e}")


