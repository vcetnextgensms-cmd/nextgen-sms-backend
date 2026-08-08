"""Android SMS Gateway transport.

Supports capcom6/android-sms-gateway (SMSGate app) as well as generic SMS gateways.
- Capcom6 SMSGate app format:
  Endpoint: http://<ip>:8080/message
  Auth: Basic Auth (username / password)
  Payload: {"phoneNumbers": [phone], "message": message}
"""
import base64
import json
import urllib.parse
import urllib.request


class AndroidGatewayError(Exception):
    pass


def send_android_sms(gateway_url, username, password, phone, message, timeout=10):
    if not gateway_url or not gateway_url.strip():
        raise AndroidGatewayError("Android Gateway URL is required (e.g. http://10.205.208.59:8080)")

    url = gateway_url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "http://" + url

    # Ensure /message endpoint for capcom6 SMSGate app if path is empty or trailing slash
    parsed = urllib.parse.urlparse(url)
    if parsed.path in ("", "/"):
        url = urllib.parse.urljoin(url, "/message")

    clean_phone = "".join(c for c in str(phone or "") if c.isdigit() or c == '+')
    if not clean_phone:
        raise AndroidGatewayError("Invalid recipient phone number.")

    # Format payload for capcom6/android-sms-gateway (SMSGate app)
    payload_data = {
        "phoneNumbers": [clean_phone],
        "message": str(message)
    }
    encoded_payload = json.dumps(payload_data).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "VCET-CSD-SMS-Gateway/1.0",
    }

    # Basic Authentication for capcom6/android-sms-gateway
    if username or password:
        user_str = str(username or "").strip()
        pass_str = str(password or "").strip()
        credentials = f"{user_str}:{pass_str}".encode("utf-8")
        b64_credentials = base64.b64encode(credentials).decode("utf-8")
        headers["Authorization"] = f"Basic {b64_credentials}"

    req = urllib.request.Request(url, data=encoded_payload, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = resp.getcode()
            if status_code in (200, 201, 202):
                return True
            else:
                raise AndroidGatewayError(f"Gateway returned HTTP status {status_code}")
    except urllib.error.HTTPError as err:
        try:
            err_body = err.read().decode("utf-8", errors="ignore")
        except Exception:
            err_body = ""
        detail = f": {err_body[:200]}" if err_body else ""
        raise AndroidGatewayError(f"HTTP Error {err.code} ({err.reason}){detail}")
    except urllib.error.URLError as err:
        raise AndroidGatewayError(f"Cannot reach phone at {url}: {err.reason}. Verify phone IP address and Wi-Fi connection.")
    except Exception as exc:
        raise AndroidGatewayError(f"Failed to send SMS via Android Gateway: {exc}")
