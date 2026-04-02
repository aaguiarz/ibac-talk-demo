"""REST endpoints for managing OpenFGA permission tuples."""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from openfga_sdk import ClientConfiguration, OpenFgaClient, ReadRequestTupleKey
from openfga_sdk.client.models import ClientTuple, ClientWriteRequest
from pydantic import BaseModel

from utils import FGA_WRITE_OPTS

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

router = APIRouter(prefix="/api/permissions", tags=["permissions"])


def _get_fga_client() -> OpenFgaClient:
    store_id = os.environ.get("FGA_STORE_ID", "")
    if not store_id:
        raise HTTPException(status_code=503, detail="FGA_STORE_ID not configured")
    return OpenFgaClient(
        ClientConfiguration(
            api_url=os.environ.get("FGA_API_URL", "http://localhost:8080"),
            store_id=store_id,
        )
    )


def _tuple_to_dict(t: Any) -> dict[str, str]:
    return {"user": t.key.user, "relation": t.key.relation, "object": t.key.object}


async def _read_all_tuples(client: OpenFgaClient) -> list[Any]:
    """Read all tuples from the store, handling pagination."""
    all_tuples: list[Any] = []
    continuation_token: str | None = None
    while True:
        options: dict[str, Any] = {}
        if continuation_token:
            options["continuation_token"] = continuation_token
        resp = await client.read(ReadRequestTupleKey(), options)
        all_tuples.extend(resp.tuples or [])
        if not resp.continuation_token:
            break
        continuation_token = resp.continuation_token
    return all_tuples


@router.get("")
async def list_permissions() -> list[dict[str, str]]:
    """List all tuples from OpenFGA."""
    client = _get_fga_client()
    try:
        raw_tuples = await _read_all_tuples(client)
        return [_tuple_to_dict(t) for t in raw_tuples]
    finally:
        await client.close()


class DeleteTupleRequest(BaseModel):
    user: str
    relation: str
    object: str


@router.post("/delete")
async def delete_tuple(req: DeleteTupleRequest) -> dict[str, str]:
    """Delete a single FGA tuple."""
    client = _get_fga_client()
    try:
        await client.write(
            ClientWriteRequest(
                deletes=[ClientTuple(user=req.user, relation=req.relation, object=req.object)]
            ),
            FGA_WRITE_OPTS,
        )
        return {"status": "deleted"}
    finally:
        await client.close()


@router.post("/reset")
async def reset_permissions() -> dict[str, int]:
    """Delete all tuples from the store."""
    client = _get_fga_client()
    try:
        raw_tuples = await _read_all_tuples(client)
        to_delete = [
            ClientTuple(user=t.key.user, relation=t.key.relation, object=t.key.object)
            for t in raw_tuples
        ]

        if to_delete:
            for i in range(0, len(to_delete), 10):
                batch = to_delete[i : i + 10]
                await client.write(ClientWriteRequest(deletes=batch), FGA_WRITE_OPTS)

        return {"deleted": len(to_delete)}
    finally:
        await client.close()


@router.get("/model", response_class=PlainTextResponse)
async def get_model() -> str:
    """Return the OpenFGA authorization model."""
    model_path = os.path.join(PROJECT_ROOT, "authorization", "model.fga")
    try:
        with open(model_path) as f:
            return f.read()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="model.fga not found")
