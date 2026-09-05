"""Cryptographic primitives for staff passwords, invitations, and sessions."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from jwt import InvalidTokenError


PASSWORD_MAX_BYTES = 72
SESSION_ALGORITHM = "HS256"


class InvalidStaffSession(ValueError):
    """Raised when a staff session is malformed, expired, or has the wrong purpose."""


@dataclass(frozen=True, slots=True)
class StaffSessionClaims:
    staff_id: str
    tenant_id: str | None
    active_location_id: str | None
    issued_at: datetime
    expires_at: datetime
    token_id: str


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) < 10:
        raise ValueError("Password must be at least 10 characters.")
    if len(raw) > PASSWORD_MAX_BYTES:
        raise ValueError("Password is too long.")
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        raw = password.encode("utf-8")
        if len(raw) > PASSWORD_MAX_BYTES:
            return False
        return bcrypt.checkpw(raw, password_hash.encode("ascii"))
    except (TypeError, ValueError):
        return False


def issue_invitation_token() -> tuple[str, str]:
    """Return the deliverable token and the only representation stored in SQL."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_opaque_token(raw)


def hash_opaque_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _timestamp(value: datetime) -> int:
    return int(value.timestamp())


def issue_staff_session(
    *,
    staff_id: str,
    tenant_id: str | None,
    active_location_id: str | None,
    secret: str,
    ttl: timedelta,
    now: datetime | None = None,
) -> str:
    if len(secret) < 32:
        raise ValueError("Session signing secret must be at least 32 characters.")
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + ttl
    payload: dict[str, Any] = {
        "typ": "staff_session",
        "sub": staff_id,
        "tid": tenant_id,
        "lid": active_location_id,
        "iat": _timestamp(issued_at),
        "exp": _timestamp(expires_at),
        "jti": secrets.token_urlsafe(18),
    }
    return jwt.encode(payload, secret, algorithm=SESSION_ALGORITHM)


def decode_staff_session(
    token: str,
    *,
    secret: str,
    now: datetime | None = None,
) -> StaffSessionClaims:
    if len(secret) < 32:
        raise ValueError("Session signing secret must be at least 32 characters.")
    try:
        options = {"require": ["typ", "sub", "iat", "exp", "jti"]}
        if now is None:
            payload = jwt.decode(token, secret, algorithms=[SESSION_ALGORITHM], options=options)
        else:
            # PyJWT does not accept an alternate clock. Verify the signature and
            # required structure, then apply the injected test clock ourselves.
            payload = jwt.decode(
                token,
                secret,
                algorithms=[SESSION_ALGORITHM],
                options={**options, "verify_exp": False},
            )
    except InvalidTokenError as exc:
        raise InvalidStaffSession("Invalid or expired staff session.") from exc
    if payload.get("typ") != "staff_session":
        raise InvalidStaffSession("Invalid staff session purpose.")
    try:
        issued_at = datetime.fromtimestamp(int(payload["iat"]), UTC)
        expires_at = datetime.fromtimestamp(int(payload["exp"]), UTC)
        current = now or datetime.now(UTC)
        if expires_at <= current:
            raise InvalidStaffSession("Staff session has expired.")
        return StaffSessionClaims(
            staff_id=str(payload["sub"]),
            tenant_id=str(payload["tid"]) if payload.get("tid") else None,
            active_location_id=str(payload["lid"]) if payload.get("lid") else None,
            issued_at=issued_at,
            expires_at=expires_at,
            token_id=str(payload["jti"]),
        )
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        if isinstance(exc, InvalidStaffSession):
            raise
        raise InvalidStaffSession("Malformed staff session.") from exc
