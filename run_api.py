"""Entry point for the JSON API backend.

LOCAL DEV: python run_api.py
  Runs FastAPI server on http://0.0.0.0:8001
  Vite frontend points to this server.
"""

import os
import sys
import uvicorn

try:
    from dotenv import load_dotenv
    load_dotenv()  # loads .env from the project root (SMTP_*, MYSQL_*, etc.) if present
except ImportError:
    pass  # python-dotenv not installed — fall back to whatever's already in the environment

if __name__ == "__main__":
    secret_key = os.environ.get("SMS_SECRET_KEY") or "dev-secret-key-vcet-csd-sms-2026"
    os.environ["SMS_SECRET_KEY"] = secret_key

    # — Render (and most PaaS hosts) inject $PORT and require the app to bind
    # to it; 8001 stays as the local-dev fallback so `python run_api.py` on
    # your own machine is unaffected.
    port = int(os.environ.get("PORT", 8001))

    print(f"[*] Starting VCET CSD SMS Backend on http://0.0.0.0:{port} ...")
    uvicorn.run("api.app:app", host="0.0.0.0", port=port, reload=False)
