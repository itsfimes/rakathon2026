from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

from rakathon_backend.common.collection import ACTIVE_COLLECTION, MAX_COLLECTION, CollectionState
from rakathon_backend.common.contracts import Envelope
from rakathon_backend.common.errors import ContractError


async def read_collection(call: Callable[..., Any], *args: Any) -> tuple[Any, dict[str, Any]]:
    state = CollectionState()
    token = ACTIVE_COLLECTION.set(state)
    try:
        result = await asyncio.to_thread(call, *args)
        metadata = state.metadata() if state.pages else {}
        return result, metadata
    except asyncio.CancelledError:
        state.cancelled.set()
        raise
    finally:
        ACTIVE_COLLECTION.reset(token)


def bounded_reply(reply: Envelope, count: int, metadata: dict[str, Any]) -> Envelope:
    if count <= MAX_COLLECTION and "receivedCount" not in metadata:
        metadata = {**metadata, "receivedCount": count}
    if (
        count > MAX_COLLECTION
        or len(
            json.dumps({"envelope": reply.to_dict()}, ensure_ascii=True, allow_nan=False).encode()
        )
        >= 1024 * 1024
    ):
        raise ContractError(
            code="resource_limit",
            message="FHIR collection unavailable",
            metadata={**metadata, "reason": "resource_limit"},
        )
    return reply


def collection_payload(items: list[dict[str, Any]], total: int, mode: str) -> dict[str, Any]:
    return {
        "bundle": {
            "resourceType": "Bundle",
            "type": "searchset",
            "total": total,
            "entry": [{"resource": item} for item in items],
        },
        "mode": mode,
    }
