"""USB/serial GSM modem SMS transport (HANDOFF.md Item A, transport shape
(b): USB/serial GSM modem plugged into the machine running the FastAPI
app — not a gateway-app/HTTP bridge, and not a paid cloud SMS API).

Uses plain AT commands in text mode (AT+CMGF=1), which is supported by
essentially every USB GSM dongle/modem (the common ones: Huawei E3131/
E1550-class sticks, SIM800/900-based USB modems). No vendor SDK needed.

This module is intentionally dependency-light and side-effect-free besides
the actual serial write — sms_worker.py owns the polling loop and queue
status updates, this module only knows how to send one message and report
whether the modem accepted it.
"""
import time

try:
    import serial  # pyserial
except ImportError:  # pragma: no cover - only missing if pip install skipped
    serial = None

AT_TIMEOUT = 5
SEND_TIMEOUT = 15


class ModemError(Exception):
    pass


def send_sms(port, baud, phone, message):
    """Blocking. Sends one SMS via AT commands. Returns True on success,
    raises ModemError with a human-readable reason on failure. Caller
    (sms_worker.py) is responsible for running this off the asyncio event
    loop (it does real blocking serial I/O) and for catching ModemError.
    """
    if serial is None:
        raise ModemError("pyserial is not installed - add 'pyserial' to requirements.txt and pip install it")
    try:
        ser = serial.Serial(port, int(baud), timeout=AT_TIMEOUT)
    except Exception as exc:
        raise ModemError(f"Could not open modem port {port}: {exc}")
    try:
        _cmd(ser, "AT", "OK")
        _cmd(ser, "AT+CMGF=1", "OK")  # text mode, not PDU mode
        ser.reset_input_buffer()
        ser.write(f'AT+CMGS="{phone}"\r'.encode())
        _wait_for(ser, ">", timeout=AT_TIMEOUT)
        ser.write(message.encode() + b"\x1a")  # body then Ctrl+Z to send
        reply = _wait_for(ser, ("OK", "ERROR", "+CMS ERROR"), timeout=SEND_TIMEOUT)
        if "OK" not in reply:
            raise ModemError(f"Modem rejected the message: {reply.strip() or 'no reply'}")
        return True
    finally:
        ser.close()


def _cmd(ser, command, expect, timeout=AT_TIMEOUT):
    ser.reset_input_buffer()
    ser.write((command + "\r").encode())
    reply = _wait_for(ser, expect, timeout=timeout)
    if expect not in reply:
        raise ModemError(f"Modem did not respond '{expect}' to '{command}': {reply.strip() or 'no reply'}")
    return reply


def _wait_for(ser, expect, timeout):
    """Read until one of the expected token(s) shows up or timeout elapses."""
    tokens = (expect,) if isinstance(expect, str) else expect
    deadline = time.time() + timeout
    buf = ""
    while time.time() < deadline:
        chunk = ser.read(64)
        if chunk:
            buf += chunk.decode(errors="ignore")
            if any(t in buf for t in tokens):
                return buf
        else:
            time.sleep(0.1)
    return buf
