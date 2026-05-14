"""Tests for `src/dataset_utils.py`."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

import db
from dataset_utils import resolve_dataset_inputs


@pytest.fixture
def user():
    email = f"ds-{uuid.uuid4().hex[:8]}@example.com"
    return db.create_user("D", "U", email)


def test_resolve_dataset_inputs_missing_dataset(user):
    with pytest.raises(HTTPException) as ex:
        resolve_dataset_inputs(
            dataset_id="missing", user_id=user, expected_type="stt"
        )
    assert ex.value.status_code == 404


def test_resolve_dataset_inputs_type_mismatch(user):
    ds_uuid = db.create_dataset(
        name=f"ds-{uuid.uuid4().hex[:6]}", dataset_type="tts", user_id=user
    )
    db.add_dataset_items(ds_uuid, [{"text": "hi"}])
    with pytest.raises(HTTPException) as ex:
        resolve_dataset_inputs(
            dataset_id=ds_uuid, user_id=user, expected_type="stt"
        )
    assert ex.value.status_code == 400


def test_resolve_dataset_inputs_empty(user):
    ds_uuid = db.create_dataset(
        name=f"ds-{uuid.uuid4().hex[:6]}", dataset_type="stt", user_id=user
    )
    with pytest.raises(HTTPException) as ex:
        resolve_dataset_inputs(
            dataset_id=ds_uuid, user_id=user, expected_type="stt"
        )
    assert ex.value.status_code == 400


def test_resolve_dataset_inputs_stt_dataset(user):
    ds_uuid = db.create_dataset(
        name=f"ds-{uuid.uuid4().hex[:6]}", dataset_type="stt", user_id=user
    )
    db.add_dataset_items(
        ds_uuid,
        [{"text": "hi", "audio_path": "s3://b/k1"}, {"text": "bye", "audio_path": "s3://b/k2"}],
    )
    resolved = resolve_dataset_inputs(
        dataset_id=ds_uuid, user_id=user, expected_type="stt"
    )
    assert resolved.texts == ["hi", "bye"]
    assert resolved.audio_paths == ["s3://b/k1", "s3://b/k2"]
    assert resolved.dataset_id == ds_uuid
    assert resolved.item_ids and len(resolved.item_ids) == 2


def test_resolve_dataset_inputs_tts_dataset(user):
    ds_uuid = db.create_dataset(
        name=f"ds-{uuid.uuid4().hex[:6]}", dataset_type="tts", user_id=user
    )
    db.add_dataset_items(ds_uuid, [{"text": "hi"}])
    resolved = resolve_dataset_inputs(
        dataset_id=ds_uuid, user_id=user, expected_type="tts"
    )
    assert resolved.audio_paths is None
    assert resolved.texts == ["hi"]


def test_resolve_dataset_inputs_inline_stt_creates_new(user):
    resolved = resolve_dataset_inputs(
        dataset_id=None,
        user_id=user,
        expected_type="stt",
        texts=["a", "b"],
        audio_paths=["s3://b/1", "s3://b/2"],
        dataset_name="brand-new-stt",
    )
    assert resolved.dataset_id is not None
    assert resolved.item_ids and len(resolved.item_ids) == 2
    assert db.get_dataset(resolved.dataset_id, user)["type"] == "stt"


def test_resolve_dataset_inputs_inline_tts_creates_new(user):
    resolved = resolve_dataset_inputs(
        dataset_id=None,
        user_id=user,
        expected_type="tts",
        texts=["a"],
        dataset_name="brand-new-tts",
    )
    assert resolved.dataset_id is not None


def test_resolve_dataset_inputs_inline_stt_validation():
    # No audio paths
    with pytest.raises(HTTPException):
        resolve_dataset_inputs(
            dataset_id=None,
            user_id="u",
            expected_type="stt",
            texts=["hi"],
            audio_paths=None,
        )
    # Length mismatch
    with pytest.raises(HTTPException):
        resolve_dataset_inputs(
            dataset_id=None,
            user_id="u",
            expected_type="stt",
            texts=["hi"],
            audio_paths=["a", "b"],
        )


def test_resolve_dataset_inputs_inline_tts_requires_texts():
    with pytest.raises(HTTPException):
        resolve_dataset_inputs(
            dataset_id=None,
            user_id="u",
            expected_type="tts",
            texts=None,
        )
