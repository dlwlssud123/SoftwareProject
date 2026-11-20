"""Fixed-cost scrypt password hashes; no caller-controlled work factors."""

import hashlib
import hmac
import re
import secrets

# OWASP's memory/CPU trade-off: N=2^16, r=8, p=2 (64 MiB).
_N, _R, _P = 65536, 8, 2
_DUMMY_SALT = secrets.token_bytes(16)
_FORMAT = re.compile(r"scrypt-v1\$([0-9a-f]{32})\$([0-9a-f]{64})\Z")
USERNAME = re.compile(r"[a-z0-9][a-z0-9._-]{2,63}\Z")


def normalize_username(value: str) -> str:
    value = value.strip().lower()
    if not USERNAME.fullmatch(value):
        raise ValueError(
            "Username must be 3-64 ASCII letters, digits, dots, underscores or hyphens"
        )
    return value


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_N,
        r=_R,
        p=_P,
        maxmem=128 * 1024 * 1024,
        dklen=32,
    )


def hash_password(password: str) -> str:
    try:
        encoded_length = len(password.encode("utf-8"))
    except UnicodeError:
        raise ValueError("Invalid password encoding") from None
    if not password.strip() or not 15 <= len(password) <= 128 or encoded_length > 512:
        raise ValueError(
            "Password must be 15-128 characters and at most 512 UTF-8 bytes"
        )
    salt = secrets.token_bytes(16)
    return f"scrypt-v1${salt.hex()}${_derive(password, salt).hex()}"


def verify_password(password: str, encoded: str | None) -> bool:
    match = _FORMAT.fullmatch(encoded or "")
    salt = bytes.fromhex(match[1]) if match else _DUMMY_SALT
    expected = bytes.fromhex(match[2]) if match else b"\x00" * 32
    actual = _derive(password, salt)
    return hmac.compare_digest(actual, expected) and match is not None
