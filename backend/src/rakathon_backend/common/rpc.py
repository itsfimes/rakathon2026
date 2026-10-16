from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import AuthError, ContractError, TransportError
from rakathon_backend.common.ipc import UnixJsonClient

SERVICES = ("b1", "b2", "b3", "b4", "b5", "b6")


def socket_for(runtime_dir: Path, service: str) -> Path:
    return runtime_dir / f"{service}.sock"


def new_envelope(
    *,
    source: str,
    target: str,
    action: str,
    data_kind: DataKind,
    payload: dict[str, Any],
    user_id: str | None = None,
    request_id: str | None = None,
    correlation_id: str | None = None,
) -> Envelope:
    return Envelope(
        request_id=request_id or f"req-{uuid.uuid4().hex}",
        correlation_id=correlation_id or f"corr-{uuid.uuid4().hex}",
        source=source,
        target=target,
        action=action,
        data_kind=data_kind,
        payload=dict(payload),
        user_id=user_id,
    )


def make_client(
    runtime_dir: Path,
    *,
    target: str,
    source: str,
    token: str,
    timeout: float = 5.0,
) -> UnixJsonClient:
    return UnixJsonClient(
        socket_for(runtime_dir, target), token=token, source=source, timeout=timeout
    )


def require_target(request: Envelope, service_name: str) -> None:
    if request.target != service_name:
        raise ContractError(code="target_mismatch", message="request target mismatch")


async def check_auth(
    b6_client: UnixJsonClient,
    *,
    user_id: str,
    action: str,
    correlation_id: str,
) -> bool:
    request = new_envelope(
        source=b6_client.source,
        target="b6",
        action="authorize",
        data_kind=DataKind.METADATA,
        payload={"userId": user_id, "action": action},
        user_id=user_id,
        correlation_id=correlation_id,
    )
    try:
        reply = await b6_client.call(request, expect_source="b6")
    except (AuthError, ContractError, TransportError, OSError, TimeoutError):
        return False
    allowed = reply.payload.get("allowed")
    return allowed is True


async def call_checked(
    client: UnixJsonClient, request: Envelope, *, expect_source: str
) -> Envelope:
    reply = await client.call(request, expect_source=expect_source)
    if reply.target != client.source:
        raise ContractError(code="source_mismatch", message="response target mismatch")
    return reply
