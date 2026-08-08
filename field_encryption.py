"""At-rest encryption for sensitive student fields (Aadhaar, APAAR).

SMS_15_HANDOFF.md Item 1. Kept in its own module (not inline in
database.py) so there is exactly ONE place that knows the key, the
cipher, and the "is this already ciphertext" heuristic — every call
site imports encrypt_field/decrypt_field/looks_encrypted from here
instead of re-deriving any of that logic.

WHY a hard-fail on missing key, matching SMS_SECRET_KEY in run_web.py:
if this key were allowed to silently default, every Aadhaar/APAAR
number already encrypted under the real key becomes permanently
unrecoverable garbage the moment someone runs the app without the env
var set (e.g. a fresh clone, a misconfigured deploy). A loud crash at
startup is recoverable; silent data loss of a government ID field is
not. See DEPLOY.md for how to generate/set SMS_FIELD_ENCRYPTION_KEY.
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken

_KEY_ENV_VAR = "SMS_FIELD_ENCRYPTION_KEY"
_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet
    key = os.environ.get(_KEY_ENV_VAR)
    if not key:
        raise RuntimeError(
            f"{_KEY_ENV_VAR} environment variable is not set.\n"
            "Refusing to start without a real field-encryption key — see "
            "DEPLOY.md section 'Generate a field encryption key'."
        )
    # — _get_fernet
    # Fernet() raises its own ValueError on a malformed key (wrong length,
    # not valid base64) — let that propagate as-is, it's already clear.
    _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def looks_encrypted(value: str | None) -> bool:
    """Best-effort check: is this string already a Fernet token?

    WHY this exists as its own function (not inlined into encrypt_field):
    the one-time startup migration (database.py init_db) needs this exact
    same test to decide whether an existing DB value is legacy plaintext
    that still needs encrypting, or already-encrypted ciphertext that
    must NOT be encrypted a second time. Sharing this function is what
    keeps migration and encrypt/decrypt from silently drifting apart.

    A Fernet token is urlsafe-base64 and, for any realistic plaintext
    this app stores (12-digit Aadhaar, APAAR IDs), always far longer
    than the plaintext itself — so "does decrypt succeed" is a reliable
    test with no ambiguous middle ground here.
    """
    if not value:
        return False
    try:
        _get_fernet().decrypt(value.encode())
        return True
    except (InvalidToken, ValueError, TypeError):
        return False


def encrypt_field(plaintext: str | None) -> str | None:
    """Encrypt a plaintext value for storage. None/'' passes through
    unchanged — WHY: many students have no Aadhaar/APAAR on file yet,
    and encrypting '' would turn "not provided" into a non-empty
    ciphertext blob, breaking every "if not value" / falsy check
    downstream (templates' `{{ r.aadhaar_number or "—" }}`,
    mask_aadhaar's `if not digits`, etc.)."""
    if not plaintext:
        return plaintext
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_field(ciphertext: str | None) -> str | None:
    """Decrypt a stored value for display/editing. None/'' passes
    through unchanged, matching encrypt_field's symmetry. Raises
    InvalidToken if given something that isn't a valid Fernet token for
    the current key — callers should not swallow that silently; letting
    it surface is what stops ciphertext-as-plaintext corruption (see
    students.py's _decrypt_student_row and the handoff's edit-form
    corruption trap) from happening a second time undetected."""
    if not ciphertext:
        return ciphertext
    return _get_fernet().decrypt(ciphertext.encode()).decode()
