"""Real SMTP email sending for the auth OTP flow (registration email
verification + password reset). Stdlib smtplib/email only -- no new
dependency needed for requirements.txt.

Configuration is entirely via environment variables (see .env.example at
the project root) -- nothing is hardcoded here, so this works against
Gmail (with an App Password), any other SMTP provider, or is safely
inert (raises a clear error) if unconfigured. Kept in its own module,
separate from database.py, so database.py stays free of network I/O --
same reasoning as database.py's own docstrings about create_password_reset()
not sending anything itself.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def get_smtp_config():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    host = os.environ.get("SMTP_HOST", "").strip()
    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ.get("SMTP_USERNAME", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    from_email = os.environ.get("SMTP_FROM_EMAIL", "").strip() or username
    from_name = os.environ.get("SMTP_FROM_NAME", "VCET CSD SMS").strip()
    use_ssl = os.environ.get("SMTP_USE_SSL", "0") == "1"
    use_tls = os.environ.get("SMTP_USE_TLS", "1") == "1"
    return {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "from_email": from_email,
        "from_name": from_name,
        "use_ssl": use_ssl,
        "use_tls": use_tls,
    }


class EmailNotConfiguredError(RuntimeError):
    """Raised when SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD aren't set. Kept as
    its own exception (not a bare RuntimeError) so callers in routes_auth.py
    can catch it specifically and return a clear ApiError instead of a
    generic 500."""


def is_configured() -> bool:
    cfg = get_smtp_config()
    return bool(cfg["host"] and cfg["username"] and cfg["password"])


def send_email(to_email: str, subject: str, body_text: str) -> None:
    cfg = get_smtp_config()
    if not bool(cfg["host"] and cfg["username"] and cfg["password"]):
        raise EmailNotConfiguredError(
            "Email sending is not configured on this server. "
            "Set SMTP_HOST, SMTP_USERNAME, and SMTP_PASSWORD (see .env)."
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{cfg['from_name']} <{cfg['from_email']}>"
    msg["To"] = to_email
    msg.set_content(body_text)

    if cfg["use_ssl"]:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=context, timeout=15) as server:
            server.login(cfg["username"], cfg["password"])
            server.send_message(msg)
    else:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as server:
            if cfg["use_tls"]:
                context = ssl.create_default_context()
                server.starttls(context=context)
            server.login(cfg["username"], cfg["password"])
            server.send_message(msg)


def send_otp_email(to_email: str, code: str, purpose: str) -> None:
    """purpose is 'REGISTER' or 'RESET_PASSWORD' -- only used to vary the
    email copy, never affects sending mechanics."""
    if purpose == "REGISTER":
        subject = "Verify your email — VCET CSD SMS"
        intro = "Use this code to verify your email and finish creating your account:"
    else:
        subject = "Password reset code — VCET CSD SMS"
        intro = "Use this code to reset your password:"

    body = (
        f"{intro}\n\n"
        f"    {code}\n\n"
        f"This code expires in 10 minutes. If you didn't request this, "
        f"you can safely ignore this email.\n"
    )
    send_email(to_email, subject, body)
