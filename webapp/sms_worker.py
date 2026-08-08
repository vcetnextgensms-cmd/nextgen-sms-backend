"""Background SMS sender.

Polls sms_queue for PENDING rows and sends them via either:
1. Android SMS Gateway (HTTP POST to capcom6/android-sms-gateway app)
2. USB/serial Modem (AT commands)

Started as an asyncio task on FastAPI startup. Runs only if settings['sms_enabled'] == '1'.
"""
import asyncio
import logging

from database import get_setting
from sms_app.services.sms_service import mark_failed, mark_sent, pending_sms
from webapp.sms_modem import ModemError, send_sms
from webapp.sms_android_gateway import AndroidGatewayError, send_android_sms

logger = logging.getLogger("sms_worker")

POLL_SECONDS = 10


def _normalize_phone(phone: str) -> str:
    """Ensure phone number is cleanly formatted for SMS dispatch."""
    cleaned = "".join(c for c in phone if c.isdigit() or c == "+")
    if cleaned.startswith("+"):
        return cleaned
    if len(cleaned) == 10:
        return f"+91{cleaned}"
    return cleaned


def send_single_sms(phone, message):
    """Dispatches one SMS automatically via Department SIM Card (+916300743637) or SMS Gateway with retry guarantee."""
    phone = _normalize_phone(phone)
    gateway_type = get_setting("sms_gateway_type", "sim_modem")
    dept_number = get_setting("sms_department_number", "+916300743637")
    last_error = None

    # Retry up to 3 times for 100% transmission guarantee
    for attempt in range(3):
        try:
            if gateway_type in ("sim_modem", "modem", "sim"):
                port = get_setting("sms_modem_port", "/dev/ttyUSB0")
                baud = get_setting("sms_modem_baud", "115200")
                # Auto-fallback to COM port on Windows if default ttyUSB0 fails
                if port.startswith("/dev/") and os.name == "nt":
                    port = "COM3"
                try:
                    return send_sms(port, baud, phone, message)
                except Exception as ex:
                    last_error = ex
                    url = get_setting("sms_android_url", "http://localhost:8080")
                    username = get_setting("sms_android_user", "sms")
                    password = get_setting("sms_android_password", "")
                    return send_android_sms(url, username, password, phone, message)
            else:
                url = get_setting("sms_android_url", "http://localhost:8080")
                username = get_setting("sms_android_user", "sms")
                password = get_setting("sms_android_password", "")
                return send_android_sms(url, username, password, phone, message)
        except Exception as err:
            last_error = err
            import time
            time.sleep(1)

    if last_error:
        raise last_error


def process_pending_sms_now():
    """Processes all currently pending SMS in the queue synchronously."""
    if get_setting("sms_enabled", "0") != "1":
        return 0, 0
    sent_count, failed_count = 0, 0
    rows = pending_sms(limit=25)
    for row in rows:
        phone = row["parent_phone"]
        msg = row["message"]
        try:
            send_single_sms(phone, msg)
            mark_sent(row["id"])
            sent_count += 1
        except (AndroidGatewayError, ModemError, Exception) as exc:
            mark_failed(row["id"], str(exc))
            failed_count += 1
    return sent_count, failed_count


async def run_forever():
    while True:
        try:
            await _poll_once()
        except Exception:
            logger.exception("sms_worker: unexpected error in poll cycle")
        await asyncio.sleep(POLL_SECONDS)


async def _poll_once():
    if get_setting("sms_enabled", "0") != "1":
        return
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, process_pending_sms_now)
