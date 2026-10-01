"""
Authentication & Admin Bootstrap.

Provides:
- Password hashing (bcrypt)
- JWT access tokens (HS256 with AUTH_SECRET_KEY)
- Admin bootstrap: one-time code creates the first admin, then code is deleted
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from typing import Optional

import bcrypt
import jwt

from app.config import get_settings

# Algorithm for JWT
JWT_ALGORITHM = "HS256"
TOKEN_EXPIRY_SECONDS = 8 * 3600  # 8 hours


@dataclass
class TokenPayload:
    sub: str  # user id (email)
    role: str  # "admin" | "in_charge" | "officer"
    checkpoint_id: Optional[str] = None
    exp: int = 0


def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(
    sub: str,
    role: str,
    checkpoint_id: Optional[str] = None,
    expires_seconds: int = TOKEN_EXPIRY_SECONDS,
) -> str:
    """Create a JWT access token."""
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": sub,
        "role": role,
        "checkpoint_id": checkpoint_id,
        "iat": now,
        "exp": now + expires_seconds,
    }
    return jwt.encode(payload, settings.AUTH_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> TokenPayload:
    """Decode and validate a JWT access token."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.AUTH_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise ValueError("Token expired")
    except jwt.InvalidTokenError as e:
        raise ValueError(f"Invalid token: {e}")
    return TokenPayload(
        sub=payload["sub"],
        role=payload["role"],
        checkpoint_id=payload.get("checkpoint_id"),
        exp=payload["exp"],
    )


# --- Admin Bootstrap ---

# File storing bootstrap state (created on first bootstrap, deleted after use)
_BOOTSTRAP_STATE_FILE = get_settings().UPLOAD_DIR / ".admin_bootstrap"


def _hash_code(code: str) -> str:
    """Hash the bootstrap code for storage (SHA-256)."""
    return hashlib.sha256(code.encode()).hexdigest()


def bootstrap_admin(
    email: str,
    password: str,
    role: str = "admin",
    bootstrap_code: Optional[str] = None,
) -> dict:
    """
    Create the first admin account using a one-time bootstrap code.

    The bootstrap code must be provided via ADMIN_BOOTSTRAP_CODE env var.
    After successful bootstrap, the code is deleted from the environment
    and the state file is written to prevent re-use.
    """
    settings = get_settings()

    # Verify bootstrap code
    expected_code = settings.ADMIN_BOOTSTRAP_CODE or os.getenv("ADMIN_BOOTSTRAP_CODE")
    if not expected_code:
        raise ValueError("Admin bootstrap not available (ADMIN_BOOTSTRAP_CODE not set)")

    provided = bootstrap_code or ""
    if not hmac.compare_digest(_hash_code(provided), _hash_code(expected_code)):
        raise ValueError("Invalid bootstrap code")

    # Check if bootstrap already used
    if _BOOTSTRAP_STATE_FILE.exists():
        raise ValueError("Admin bootstrap already used")

    # Hash password
    password_hash = get_password_hash(password)

    # Create admin record (in production, store in database)
    admin_record = {
        "email": email,
        "password_hash": password_hash,
        "role": role,
        "created_at": time.time(),
    }

    # Mark bootstrap as used
    _BOOTSTRAP_STATE_FILE.write_text("used")

    # Clear the code from environment (prevents re-use in same process)
    os.environ.pop("ADMIN_BOOTSTRAP_CODE", None)
    settings.ADMIN_BOOTSTRAP_CODE = None

    return {"status": "ok", "admin": admin_record}


def require_admin_bootstrap() -> None:
    """Raise if admin bootstrap is still available (should not be in production)."""
    settings = get_settings()
    if settings.ADMIN_BOOTSTRAP_CODE or os.getenv("ADMIN_BOOTSTRAP_CODE"):
        if not _BOOTSTRAP_STATE_FILE.exists():
            raise RuntimeError(
                "Admin bootstrap code is still set but not used. "
                "Either use it to create the first admin, or remove it from environment."
            )


# Import hmac at module level for bootstrap_admin
import hmac