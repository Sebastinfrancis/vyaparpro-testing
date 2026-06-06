"""
VyaparPro — Security Utilities
JWT creation/verification, password hashing, TOTP 2FA
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pyotp
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.core.exceptions import (
    InvalidCredentialsError,
    TokenExpiredError,
    TokenInvalidError,
)

# ── Password hashing ─────────────────────────────────────────────────────────
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=settings.BCRYPT_ROUNDS,
)


def hash_password(password: str) -> str:
    """Hash a plain-text password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against its bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)


def validate_password_strength(password: str) -> list[str]:
    """Return list of unmet password requirements (empty = OK)."""
    errors: list[str] = []
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        errors.append(f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters.")
    if not any(c.isupper() for c in password):
        errors.append("Password must contain at least one uppercase letter.")
    if not any(c.islower() for c in password):
        errors.append("Password must contain at least one lowercase letter.")
    if not any(c.isdigit() for c in password):
        errors.append("Password must contain at least one digit.")
    special = "!@#$%^&*()_+-=[]{}|;':\",./<>?"
    if not any(c in special for c in password):
        errors.append("Password must contain at least one special character.")
    return errors


# ── JWT Tokens ───────────────────────────────────────────────────────────────

TokenPayload = dict[str, Any]


def _create_token(
    subject: str | UUID,
    token_type: str,
    expire_delta: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload: TokenPayload = {
        "sub": str(subject),
        "type": token_type,
        "iat": now,
        "exp": now + expire_delta,
        "jti": secrets.token_urlsafe(16),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(
    user_id: str | UUID,
    company_id: str | UUID,
    role_id: str | UUID,
    branch_id: str | UUID | None = None,
    scopes: list[str] | None = None,
) -> str:
    return _create_token(
        subject=user_id,
        token_type="access",
        expire_delta=timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
        extra_claims={
            "company_id": str(company_id),
            "role_id": str(role_id),
            "branch_id": str(branch_id) if branch_id else None,
            "scopes": scopes or [],
        },
    )


def create_refresh_token(user_id: str | UUID) -> str:
    return _create_token(
        subject=user_id,
        token_type="refresh",
        expire_delta=timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
    )


def create_reset_token(user_id: str | UUID, email: str) -> str:
    return _create_token(
        subject=user_id,
        token_type="reset",
        expire_delta=timedelta(minutes=settings.JWT_RESET_TOKEN_EXPIRE_MINUTES),
        extra_claims={"email": email},
    )


def decode_token(token: str, expected_type: str | None = None) -> TokenPayload:
    """
    Decode and validate a JWT token.
    Raises TokenExpiredError or TokenInvalidError on failure.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError as exc:
        if "expired" in str(exc).lower():
            raise TokenExpiredError() from exc
        raise TokenInvalidError() from exc

    if expected_type and payload.get("type") != expected_type:
        raise TokenInvalidError(f"Expected token type '{expected_type}'")

    return payload


def hash_token(token: str) -> str:
    """SHA-256 hash of a token for safe server-side storage."""
    return hashlib.sha256(token.encode()).hexdigest()


# ── TOTP 2FA ─────────────────────────────────────────────────────────────────

def generate_totp_secret() -> str:
    """Generate a new base32 TOTP secret."""
    return pyotp.random_base32()


def get_totp_uri(secret: str, email: str) -> str:
    """Return the OTP Auth URI for QR code generation."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name=settings.TOTP_ISSUER)


def verify_totp(secret: str, code: str) -> bool:
    """Verify a 6-digit TOTP code (±30s window)."""
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)
