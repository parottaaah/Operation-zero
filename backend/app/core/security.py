"""Password hashing, token issuing and secrets-at-rest helpers.

We deliberately use standard primitives only:

* ``hashlib.scrypt`` for password hashing (memory-hard KDF, stdlib, no custom crypto).
* ``PyJWT`` for signed access/refresh tokens.
* ``cryptography.Fernet`` for encrypting integration credentials at rest.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32


class TokenError(Exception):
    """Raised when a JWT is missing, malformed, expired or of the wrong type."""


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    salt_b64 = base64.b64encode(salt).decode()
    digest_b64 = base64.b64encode(digest).decode()
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt_b64}${digest_b64}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def new_api_key() -> tuple[str, str, str]:
    """Return ``(full_key, sha256_hash, last4)`` for a service ingestion key."""
    raw = "ozk_" + secrets.token_urlsafe(32)
    return raw, sha256_hex(raw), raw[-4:]


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
def _encode(subject: str, token_type: str, ttl: timedelta, extra: dict | None = None) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: uuid.UUID) -> str:
    return _encode(
        str(user_id),
        "access",
        timedelta(minutes=settings.access_token_ttl_minutes),
    )


def create_refresh_token(user_id: uuid.UUID) -> str:
    return _encode(str(user_id), "refresh", timedelta(days=settings.refresh_token_ttl_days))


def decode_token(token: str, expected_type: str = "access") -> uuid.UUID:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("invalid token") from exc
    if payload.get("type") != expected_type:
        raise TokenError("wrong token type")
    try:
        return uuid.UUID(str(payload["sub"]))
    except (ValueError, KeyError) as exc:
        raise TokenError("invalid subject") from exc


# ---------------------------------------------------------------------------
# Secrets at rest
# ---------------------------------------------------------------------------
def _fernet() -> Fernet:
    return Fernet(settings.fernet_key)


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("stored secret cannot be decrypted with the configured key") from exc


__all__ = [
    "TokenError",
    "hash_password",
    "verify_password",
    "new_api_key",
    "sha256_hex",
    "constant_time_equals",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "encrypt_secret",
    "decrypt_secret",
]
