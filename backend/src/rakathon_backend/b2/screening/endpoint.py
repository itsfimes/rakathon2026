from __future__ import annotations

import asyncio

from rakathon_backend.b2.screening import archive
from rakathon_backend.b2.screening.ports import ScreeningPort
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import ContractError

SERVICE_NAME = "b2"


async def handle_query(store: ScreeningPort | None, mode: str, request: Envelope) -> Envelope:
    if request.data_kind != DataKind.METADATA:
        raise ContractError(code="misclassified", message="screening.query needs metadata")
    if store is None:
        raise ContractError(code="not_configured", message="screening store is not mounted")
    payload = request.payload
    filters, projection, limit, offset = archive.check_query_args(
        payload.get("filters", {}),
        payload.get("projection"),
        payload.get("limit", 100),
        payload.get("offset", 0),
    )
    page = await asyncio.to_thread(store.query, filters, projection, limit, offset)
    return request.reply(
        source=SERVICE_NAME,
        action=request.action,
        payload={
            "rows": page.rows,
            "count": len(page.rows),
            "truncated": page.truncated,
            "mode": mode,
        },
        data_kind=DataKind.PROPRIETARY,
    )
