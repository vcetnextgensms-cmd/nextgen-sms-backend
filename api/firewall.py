"""API Security Firewall Middleware — Protects against Brute-Force, Rate-Limiting,
DoS Attacks, Clickjacking, MIME Sniffing, and Cross-Site Scripting (XSS).
"""

import time
from collections import defaultdict
from typing import Dict, List
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# In-memory IP Rate Limiter
# Auth endpoints: Max 12 requests per minute per IP
# General API endpoints: Max 120 requests per minute per IP
auth_requests_log: Dict[str, List[float]] = defaultdict(list)
general_requests_log: Dict[str, List[float]] = defaultdict(list)

AUTH_LIMIT_PER_MINUTE = 15
GENERAL_LIMIT_PER_MINUTE = 120


class SecurityFirewallMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "127.0.0.1"
        now = time.time()
        path = request.url.path.lower()

        # ── Rate-Limiting Firewall Check ──
        if path.startswith("/api/auth/login") or path.startswith("/api/auth/send-otp") or path.startswith("/api/auth/register") or path.startswith("/api/auth/reset-password"):
            timestamps = auth_requests_log[client_ip]
            # Keep only timestamps within last 60 seconds
            valid_timestamps = [t for t in timestamps if now - t < 60]
            auth_requests_log[client_ip] = valid_timestamps
            if len(valid_timestamps) >= AUTH_LIMIT_PER_MINUTE:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "message": "Too many authentication requests. Rate limit exceeded. Please try again in 1 minute.",
                            "code": "RATE_LIMIT_EXCEEDED",
                        }
                    },
                )
            auth_requests_log[client_ip].append(now)
        else:
            timestamps = general_requests_log[client_ip]
            valid_timestamps = [t for t in timestamps if now - t < 60]
            general_requests_log[client_ip] = valid_timestamps
            if len(valid_timestamps) >= GENERAL_LIMIT_PER_MINUTE:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "message": "Too many requests. Rate limit exceeded. Please wait a moment.",
                            "code": "RATE_LIMIT_EXCEEDED",
                        }
                    },
                )
            general_requests_log[client_ip].append(now)

        # Process the request
        response: Response = await call_next(request)

        # ── Enterprise Security & Anti-Attack Headers Firewall ──
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        return response
