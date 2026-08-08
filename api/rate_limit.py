"""In-memory rate limiter — OPTION_B_REWRITE_PLAN.md §3.4 (Item 3 +
SECURITY_HANDOFF #5, built once). Same shape as originally scoped: 5
attempts / 15 min window, keyed by caller-supplied key (IP+username for
login, session for /api/files/...).

WHY in-memory and not Redis/DB: single-process deployment (§5's two
fully-separate-processes-from-day-one topology still means one process
per app, not a multi-worker fleet), matches "don't over-engineer" applied
elsewhere in the plan (§4.1's Redux-avoidance reasoning). If this ever
runs behind multiple worker processes, this needs to move to shared
storage — flagging here, not treating it as free.

— WHY the error message never distinguishes "locked out" from "wrong
credentials" (same reasoning as before, unchanged by the rewrite): telling
an attacker which one happened lets them enumerate valid usernames (a
"locked out" response confirms the username exists and has real attempts
against it; a generic "invalid credentials" response doesn't).
"""

import time

WINDOW_SECONDS = 15 * 60
MAX_ATTEMPTS = 5

# key -> list[timestamp] of recent failed attempts
_attempts: dict[str, list[float]] = {}


def _prune(key: str, now: float) -> list[float]:
    recent = [t for t in _attempts.get(key, []) if now - t < WINDOW_SECONDS]
    _attempts[key] = recent
    return recent


def is_locked(key: str) -> bool:
    now = time.time()
    return len(_prune(key, now)) >= MAX_ATTEMPTS


def record_failure(key: str) -> None:
    now = time.time()
    _prune(key, now)
    _attempts.setdefault(key, []).append(now)


def record_success(key: str) -> None:
    # WHY clear on success: a legitimate login after some earlier typos
    # shouldn't stay in a countdown toward lockout — matches how most
    # login-attempt limiters behave, and there's no security cost to
    # clearing (an attacker who NEEDED lockout to matter already failed).
    _attempts.pop(key, None)
