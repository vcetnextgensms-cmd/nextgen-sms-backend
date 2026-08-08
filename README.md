# CSD NextGen SMS - Backend API

Production-ready FastAPI JSON backend service for VCET CSD Student Management System.

## Features
- JWT Authentication (Access Tokens + Secure `httpOnly` Refresh Cookie)
- HOD, Faculty, and Student Management
- Class Attendance tracking & PDF Export
- Sensitive Field Encryption (Aadhaar, APAAR)
- Database fallback & automatic migrations (SQLite / MySQL)

## Deployment Guide (Render / Railway / Heroku)

1. Connect this repository on Render or Railway.
2. Build command: `pip install -r requirements.txt`
3. Start command: `uvicorn api.app:app --host 0.0.0.0 --port $PORT`
4. Set Environment Variables:
   - `SMS_ENV` = `production`
   - `SMS_SECRET_KEY` = `<secure-secret-key>`
   - `ALLOWED_ORIGINS` = `https://<your-frontend-app>.vercel.app`
   - `SMS_COOKIE_SECURE` = `true`
   - `SMS_COOKIE_SAMESITE` = `none`
