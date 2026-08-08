"""Web app config. Design tokens ported from sms_app/config.py unchanged —
see webapp/static/css/app.css where they become CSS variables."""

import os
import secrets

# - SECRET_KEY
# WHY this changed: this used to fall back to the literal string
# "dev-secret-change-in-production" when SMS_SECRET_KEY wasn't set. That
# string is now public (it shipped in this repo's history), and this key
# signs every session cookie (see webapp/auth_session.py) - anyone who knew
# the old fallback could forge a valid HOD/faculty login. run_web.py already
# refuses to start without SMS_SECRET_KEY set (see DEPLOY.md), so this
# fallback only matters for ad-hoc `uvicorn webapp.main:app` runs that skip
# run_web.py - it's a fresh random value per process start (not a fixed
# string), so it can't be used to forge cookies across restarts. Always set
# SMS_SECRET_KEY for any real deployment.
SECRET_KEY = os.environ.get("SMS_SECRET_KEY") or secrets.token_hex(32)
SESSION_COOKIE = "sms_session"

# Ported 1:1 from sms_app/config.py
NAV = "#092b49"
NAV2 = "#123f6c"
BLUE = "#1769e8"
GREEN = "#18a957"
YELLOW = "#d97706"
RED = "#dc3545"
BG = "#f5f7fb"
TEXT = "#101828"
MUTED = "#667085"
