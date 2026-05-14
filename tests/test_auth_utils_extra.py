"""Additional coverage for src/auth_utils.py."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt

import auth_utils
from auth_utils import (
    JWT_ALGORITHM,
    create_access_token,
    get_current_user_id,
    get_optional_user_id,
    require_superadmin,
)


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_get_current_user_id_valid(monkeypatch):
    monkeypatch.setattr(auth_utils, "JWT_SECRET_KEY", "test-secret-key-for-unit-tests")
    monkeypatch.setattr(auth_utils, "JWT_EXPIRATION_HOURS", 1)
    token = create_access_token("uid-1", "user@example.com")
    out = asyncio.run(get_current_user_id(_creds(token)))
    assert out == "uid-1"


def test_get_current_user_id_invalid_token(monkeypatch):
    monkeypatch.setattr(auth_utils, "JWT_SECRET_KEY", "test-secret-key-for-unit-tests")
    with pytest.raises(HTTPException) as ex:
        asyncio.run(get_current_user_id(_creds("not-a-token")))
    assert ex.value.status_code == 401


def test_get_current_user_id_missing_sub(monkeypatch):
    monkeypatch.setattr(auth_utils, "JWT_SECRET_KEY", "test-secret-key-for-unit-tests")
    payload = {
        "email": "u@example.com",
        "exp": datetime.utcnow() + timedelta(hours=1),
    }
    token = jwt.encode(payload, auth_utils.JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    with pytest.raises(HTTPException) as ex:
        asyncio.run(get_current_user_id(_creds(token)))
    assert ex.value.status_code == 401


def test_require_superadmin_allows(monkeypatch):
    monkeypatch.setattr(auth_utils, "JWT_SECRET_KEY", "test-secret-key-for-unit-tests")
    monkeypatch.setattr(auth_utils, "SUPERADMIN_EMAIL", "admin@example.com")
    token = create_access_token("admin-uid", "admin@example.com")
    out = asyncio.run(require_superadmin(_creds(token)))
    assert out == "admin-uid"


def test_require_superadmin_rejects_non_admin(monkeypatch):
    monkeypatch.setattr(auth_utils, "JWT_SECRET_KEY", "test-secret-key-for-unit-tests")
    monkeypatch.setattr(auth_utils, "SUPERADMIN_EMAIL", "admin@example.com")
    token = create_access_token("uid", "regular@example.com")
    with pytest.raises(HTTPException) as ex:
        asyncio.run(require_superadmin(_creds(token)))
    assert ex.value.status_code == 403


def test_require_superadmin_no_admin_env(monkeypatch):
    monkeypatch.setattr(auth_utils, "JWT_SECRET_KEY", "test-secret-key-for-unit-tests")
    monkeypatch.setattr(auth_utils, "SUPERADMIN_EMAIL", "")
    token = create_access_token("uid", "regular@example.com")
    with pytest.raises(HTTPException) as ex:
        asyncio.run(require_superadmin(_creds(token)))
    assert ex.value.status_code == 403


def test_get_optional_user_id_none():
    assert asyncio.run(get_optional_user_id(None)) is None


def test_get_optional_user_id_valid(monkeypatch):
    monkeypatch.setattr(auth_utils, "JWT_SECRET_KEY", "test-secret-key-for-unit-tests")
    token = create_access_token("uid-2", "u@e.com")
    out = asyncio.run(get_optional_user_id(_creds(token)))
    assert out == "uid-2"


def test_get_optional_user_id_bad_token():
    assert asyncio.run(get_optional_user_id(_creds("garbage"))) is None
