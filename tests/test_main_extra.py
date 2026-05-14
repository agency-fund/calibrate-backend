"""Extra tests for src/main.py — provider-status, OpenRouter, and sentry-debug."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def app():
    import main as main_mod

    return main_mod.app


@pytest.fixture(scope="module")
def client(app):
    with patch("main.recover_pending_jobs"):
        with TestClient(app) as c:
            yield c


# ---------------------------------------------------------------------------
# /provider-status — subprocess mocked
# ---------------------------------------------------------------------------


def _make_fake_process(returncode: int, stdout: bytes, stderr: bytes):
    process = MagicMock()
    process.returncode = returncode
    process.communicate = AsyncMock(return_value=(stdout, stderr))
    process.wait = AsyncMock(return_value=None)
    process.kill = MagicMock()
    return process


def test_provider_status_all_pass(client):
    process = _make_fake_process(
        0, json.dumps({"openai": {"status": "pass"}}).encode(), b""
    )
    with patch(
        "main.asyncio.create_subprocess_exec", AsyncMock(return_value=process)
    ):
        resp = client.get("/provider-status")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_provider_status_some_failed(client):
    process = _make_fake_process(
        0,
        json.dumps(
            {"openai": {"status": "pass"}, "deepgram": {"status": "fail", "error": "x"}}
        ).encode(),
        b"",
    )
    with patch(
        "main.asyncio.create_subprocess_exec", AsyncMock(return_value=process)
    ):
        resp = client.get("/provider-status")
    assert resp.status_code == 503


def test_provider_status_subprocess_non_zero(client):
    process = _make_fake_process(1, b"", b"boom")
    with patch(
        "main.asyncio.create_subprocess_exec", AsyncMock(return_value=process)
    ):
        resp = client.get("/provider-status")
    assert resp.status_code == 500


def test_provider_status_invalid_json(client):
    process = _make_fake_process(0, b"not json", b"")
    with patch(
        "main.asyncio.create_subprocess_exec", AsyncMock(return_value=process)
    ):
        resp = client.get("/provider-status")
    assert resp.status_code == 500


def test_provider_status_calibrate_not_found(client):
    with patch(
        "main.asyncio.create_subprocess_exec",
        AsyncMock(side_effect=FileNotFoundError()),
    ):
        resp = client.get("/provider-status")
    assert resp.status_code == 500


def test_provider_status_timeout(client):
    import asyncio

    process = MagicMock()
    process.returncode = 0
    process.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
    process.wait = AsyncMock(return_value=None)
    process.kill = MagicMock()
    with patch(
        "main.asyncio.create_subprocess_exec", AsyncMock(return_value=process)
    ):
        resp = client.get("/provider-status")
    assert resp.status_code == 504


# ---------------------------------------------------------------------------
# /openrouter/providers — filtered list path
# ---------------------------------------------------------------------------


def test_openrouter_filtered_list(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_ALLOWED_PROVIDERS", "anthropic,openai")

    payload = {
        "data": [
            {"slug": "anthropic", "name": "Anthropic"},
            {"slug": "openai", "name": "OpenAI"},
            {"slug": "google", "name": "Google"},
        ]
    }

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return payload

    fake_client = MagicMock()
    fake_client.get = AsyncMock(return_value=FakeResp())
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)

    with patch("main.httpx.AsyncClient", return_value=fake_client):
        resp = client.get("/openrouter/providers")
    assert resp.status_code == 200
    body = resp.json()
    slugs = {p["slug"] for p in body["providers"]}
    assert slugs == {"anthropic", "openai"}


def test_openrouter_filtered_list_http_error(client, monkeypatch):
    import httpx

    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_ALLOWED_PROVIDERS", "anthropic")

    fake_client = MagicMock()
    fake_client.get = AsyncMock(side_effect=httpx.HTTPError("nope"))
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)

    with patch("main.httpx.AsyncClient", return_value=fake_client):
        resp = client.get("/openrouter/providers")
    assert resp.status_code == 502


# ---------------------------------------------------------------------------
# /sentry-debug
# ---------------------------------------------------------------------------


def test_sentry_debug_raises(client):
    """The endpoint raises ZeroDivisionError; TestClient re-raises it.
    Either outcome (500 from FastAPI handler, or exception bubbling) proves
    the handler ran."""
    try:
        resp = client.get("/sentry-debug")
        assert resp.status_code == 500
    except ZeroDivisionError:
        pass
