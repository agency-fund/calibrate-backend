"""Per-user API keys used to invoke the evaluator endpoint.

The raw key is shown to the user exactly once on creation; only a bcrypt hash and short
lookup prefix are persisted.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth_utils import generate_api_key, get_current_user_id
from db import create_api_key_row, delete_api_key, get_api_keys_for_user

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


class APIKeyCreate(BaseModel):
    name: str


class APIKeyCreateResponse(BaseModel):
    uuid: str
    name: str
    key_prefix: str
    api_key: str  # raw; shown once
    message: str


class APIKeyListItem(BaseModel):
    uuid: str
    name: str
    key_prefix: str
    created_at: str
    last_used_at: Optional[str] = None


@router.post("", response_model=APIKeyCreateResponse)
async def create_api_key(
    payload: APIKeyCreate, user_id: str = Depends(get_current_user_id)
):
    raw_key, key_prefix, key_hash = generate_api_key()
    api_key_uuid = create_api_key_row(
        user_id=user_id, name=payload.name, key_hash=key_hash, key_prefix=key_prefix
    )
    return APIKeyCreateResponse(
        uuid=api_key_uuid,
        name=payload.name,
        key_prefix=key_prefix,
        api_key=raw_key,
        message="Save this key now — it will not be shown again.",
    )


@router.get("", response_model=List[APIKeyListItem])
async def list_api_keys(user_id: str = Depends(get_current_user_id)):
    rows = get_api_keys_for_user(user_id)
    return [
        APIKeyListItem(
            uuid=r["uuid"],
            name=r["name"],
            key_prefix=r["key_prefix"],
            created_at=r["created_at"],
            last_used_at=r.get("last_used_at"),
        )
        for r in rows
    ]


@router.delete("/{api_key_uuid}")
async def delete_api_key_endpoint(
    api_key_uuid: str, user_id: str = Depends(get_current_user_id)
):
    if not delete_api_key(api_key_uuid, user_id):
        raise HTTPException(status_code=404, detail="API key not found")
    return {"message": "API key revoked"}
