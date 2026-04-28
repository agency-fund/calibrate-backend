"""JWT & API-key Authentication Utilities.

This module provides JWT token creation/validation and API-key verification for
securing API endpoints.
"""

import os
import secrets
import logging
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from jose import JWTError, jwt
from fastapi import HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

API_KEY_PREFIX = "calib_"
API_KEY_LOOKUP_PREFIX_LEN = 12  # prefix stored in DB = API_KEY_PREFIX + 6 raw chars

logger = logging.getLogger(__name__)

# JWT Configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-this-secret-key-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "168"))  # 7 days default

# Security scheme for Bearer token authentication
security = HTTPBearer(auto_error=True)


def create_access_token(user_uuid: str, email: str) -> str:
    """
    Create a JWT access token containing the user's UUID.

    Args:
        user_uuid: The unique identifier of the user
        email: The user's email (for logging/debugging)

    Returns:
        Encoded JWT token string
    """
    expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)
    payload = {
        "sub": user_uuid,  # subject = user UUID
        "email": email,
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    logger.debug(f"Created access token for user {user_uuid} (expires: {expire})")
    return token


def decode_token(token: str) -> Optional[dict]:
    """
    Decode and validate a JWT token.

    Args:
        token: The JWT token string

    Returns:
        Decoded payload dict if valid, None if invalid/expired
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError as e:
        logger.debug(f"Token decode failed: {e}")
        return None


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """
    FastAPI dependency to extract and validate user_id from JWT token.

    Usage:
        @router.post("/endpoint")
        async def endpoint(user_id: str = Depends(get_current_user_id)):
            # user_id is now available and validated
            pass

    Args:
        credentials: HTTP Authorization header credentials (injected by FastAPI)

    Returns:
        The user UUID extracted from the token

    Raises:
        HTTPException: 401 if token is missing, invalid, or expired
    """
    token = credentials.credentials
    payload = decode_token(token)

    if not payload:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Token missing user information",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user_id


SUPERADMIN_EMAIL = os.getenv("SUPERADMIN_EMAIL", "")


async def require_superadmin(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """
    FastAPI dependency that requires the caller to be a superadmin.

    Extracts the email from the JWT and checks it against SUPERADMIN_EMAIL.
    Returns the user UUID if authorized.

    Raises:
        HTTPException: 401 if token invalid, 403 if not superadmin
    """
    user_id = await get_current_user_id(credentials)

    payload = decode_token(credentials.credentials)
    email = payload.get("email", "")
    if not SUPERADMIN_EMAIL or email != SUPERADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Superadmin access required")

    return user_id


# Optional dependency that doesn't require authentication
# Useful for endpoints that work with or without auth
async def get_optional_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    ),
) -> Optional[str]:
    """
    FastAPI dependency to optionally extract user_id from JWT token.

    Returns None if no token is provided or token is invalid.
    Useful for endpoints that should work for both authenticated and anonymous users.

    Args:
        credentials: Optional HTTP Authorization header credentials

    Returns:
        The user UUID if token is valid, None otherwise
    """
    if not credentials:
        return None

    payload = decode_token(credentials.credentials)
    if not payload:
        return None

    return payload.get("sub")


# ============ API-key authentication ============


def generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key.

    Returns:
        (raw_key, key_prefix, key_hash) — persist only prefix + hash; raw_key is shown to the
        user exactly once.
    """
    raw_suffix = secrets.token_urlsafe(32)
    raw_key = f"{API_KEY_PREFIX}{raw_suffix}"
    key_prefix = raw_key[:API_KEY_LOOKUP_PREFIX_LEN]
    key_hash = bcrypt.hashpw(raw_key.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    return raw_key, key_prefix, key_hash


def _extract_api_key(request: Request) -> Optional[str]:
    """Pull the API key out of the request. Accepts either X-API-Key header or
    `Authorization: Bearer <key>` where the key starts with API_KEY_PREFIX."""
    header_key = request.headers.get("X-API-Key")
    if header_key:
        return header_key.strip()
    auth = request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        candidate = auth[7:].strip()
        if candidate.startswith(API_KEY_PREFIX):
            return candidate
    return None


async def get_user_from_api_key(request: Request) -> str:
    """FastAPI dependency: verify the API key and return the owning user's UUID.

    Raises 401 if the key is missing, malformed, or unknown.
    """
    from db import get_api_key_candidates_by_prefix, touch_api_key  # lazy import

    raw_key = _extract_api_key(request)
    if not raw_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key (send X-API-Key header or Authorization: Bearer <key>)",
        )
    if not raw_key.startswith(API_KEY_PREFIX) or len(raw_key) < API_KEY_LOOKUP_PREFIX_LEN:
        raise HTTPException(status_code=401, detail="Malformed API key")

    lookup_prefix = raw_key[:API_KEY_LOOKUP_PREFIX_LEN]
    candidates = get_api_key_candidates_by_prefix(lookup_prefix)
    for candidate in candidates:
        try:
            if bcrypt.checkpw(raw_key.encode("utf-8"), candidate["key_hash"].encode("utf-8")):
                touch_api_key(candidate["uuid"])
                return candidate["user_id"]
        except ValueError:
            continue
    raise HTTPException(status_code=401, detail="Invalid API key")
