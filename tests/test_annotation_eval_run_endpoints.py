"""Tests for annotation-task evaluator-run endpoints — the start-job +
list + get + delete + visibility flow. Real start is mocked so no calibrate
subprocess spawns."""

from __future__ import annotations

import uuid
from unittest.mock import patch

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


def _signup(client):
    suffix = uuid.uuid4().hex[:8]
    body = client.post(
        "/auth/signup",
        json={
            "first_name": "E",
            "last_name": "R",
            "email": f"er-{suffix}@example.com",
            "password": "passw0rd",
        },
    ).json()
    return {
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
        "user_uuid": body["user"]["uuid"],
    }


def _llm_ev(client, h):
    evs = client.get("/evaluators", headers=h).json()
    return next(e for e in evs if e.get("evaluator_type") == "llm")


def test_evaluator_run_lifecycle(client, monkeypatch):
    auth = _signup(client)
    h = auth["headers"]
    llm_ev = _llm_ev(client, h)
    task_uuid = client.post(
        "/annotation-tasks",
        json={
            "name": f"t-{uuid.uuid4().hex[:6]}",
            "type": "llm",
            "evaluator_ids": [llm_ev["uuid"]],
        },
        headers=h,
    ).json()["uuid"]
    # Add LLM-compatible items
    client.post(
        f"/annotation-tasks/{task_uuid}/items",
        json={
            "items": [
                {
                    "payload": {
                        "name": "i1",
                        "chat_history": [{"role": "user", "content": "hi"}],
                        "agent_response": "hi back",
                    }
                },
                {
                    "payload": {
                        "name": "i2",
                        "chat_history": [{"role": "user", "content": "hi"}],
                        "agent_response": "yes",
                    }
                },
            ]
        },
        headers=h,
    )

    # Start a run (force queue path so no thread spawns)
    with patch(
        "routers.annotation_tasks.can_start_job", return_value=False
    ):
        resp = client.post(
            f"/annotation-tasks/{task_uuid}/evaluator-runs",
            json={"evaluators": [{"evaluator_id": llm_ev["uuid"]}]},
            headers=h,
        )
    assert resp.status_code == 200
    job_uuid = resp.json()["job_uuid"]
    assert resp.json()["status"] == "queued"

    # Inflight path — start_annotation_eval_job mocked
    with patch(
        "routers.annotation_tasks.can_start_job", return_value=True
    ), patch(
        "routers.annotation_tasks.start_annotation_eval_job"
    ) as start:
        resp2 = client.post(
            f"/annotation-tasks/{task_uuid}/evaluator-runs",
            json={"evaluators": [{"evaluator_id": llm_ev["uuid"]}]},
            headers=h,
        )
        start.assert_called_once()
    assert resp2.status_code == 200

    # List
    listing = client.get(
        f"/annotation-tasks/{task_uuid}/evaluator-runs", headers=h
    )
    assert listing.status_code == 200
    assert len(listing.json()) >= 2

    # GET job
    got = client.get(
        f"/annotation-tasks/{task_uuid}/evaluator-runs/{job_uuid}", headers=h
    )
    assert got.status_code == 200

    # Visibility — can't share an in-progress / queued run
    bad = client.patch(
        f"/annotation-tasks/{task_uuid}/evaluator-runs/{job_uuid}/visibility",
        json={"is_public": True},
        headers=h,
    )
    assert bad.status_code == 400

    # Off is allowed
    off = client.patch(
        f"/annotation-tasks/{task_uuid}/evaluator-runs/{job_uuid}/visibility",
        json={"is_public": False},
        headers=h,
    )
    assert off.status_code == 200

    # Delete (queued job is deletable)
    deleted = client.delete(
        f"/annotation-tasks/{task_uuid}/evaluator-runs/{job_uuid}", headers=h
    )
    assert deleted.status_code == 200


def test_evaluator_run_bad_evaluator_resolution(client):
    auth = _signup(client)
    h = auth["headers"]
    llm_ev = _llm_ev(client, h)
    task_uuid = client.post(
        "/annotation-tasks",
        json={
            "name": f"t-{uuid.uuid4().hex[:6]}",
            "type": "llm",
            "evaluator_ids": [llm_ev["uuid"]],
        },
        headers=h,
    ).json()["uuid"]
    client.post(
        f"/annotation-tasks/{task_uuid}/items",
        json={
            "items": [
                {
                    "payload": {
                        "name": "i1",
                        "chat_history": [],
                        "agent_response": "x",
                    }
                }
            ]
        },
        headers=h,
    )

    # Try to use an evaluator not linked to the task (default-stt-transcription is not linked)
    evaluators = client.get("/evaluators", headers=h).json()
    other_ev = next(e for e in evaluators if e.get("evaluator_type") == "stt")
    resp = client.post(
        f"/annotation-tasks/{task_uuid}/evaluator-runs",
        json={"evaluators": [{"evaluator_id": other_ev["uuid"]}]},
        headers=h,
    )
    assert resp.status_code == 400


def test_evaluator_run_with_specific_item_ids(client):
    auth = _signup(client)
    h = auth["headers"]
    llm_ev = _llm_ev(client, h)
    task_uuid = client.post(
        "/annotation-tasks",
        json={
            "name": f"t-{uuid.uuid4().hex[:6]}",
            "type": "llm",
            "evaluator_ids": [llm_ev["uuid"]],
        },
        headers=h,
    ).json()["uuid"]
    items = client.post(
        f"/annotation-tasks/{task_uuid}/items",
        json={
            "items": [
                {
                    "payload": {
                        "name": "i1",
                        "chat_history": [],
                        "agent_response": "x",
                    }
                }
            ]
        },
        headers=h,
    ).json()["item_ids"]

    with patch(
        "routers.annotation_tasks.can_start_job", return_value=False
    ):
        resp = client.post(
            f"/annotation-tasks/{task_uuid}/evaluator-runs",
            json={
                "evaluators": [{"evaluator_id": llm_ev["uuid"]}],
                "item_ids": items,
            },
            headers=h,
        )
    assert resp.status_code == 200
