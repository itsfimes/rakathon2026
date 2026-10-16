from __future__ import annotations

import time

import pytest

from rakathon_backend.b2.memory import MemoryStorage
from rakathon_backend.b2.service import B2Service
from rakathon_backend.b4.router import MAX_PENDING, B4Router
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import ContractError, TransportError
from rakathon_backend.common.kinds import request_kind


async def _allow_all(*, user_id: str, action: str, correlation_id: str) -> bool:
    _ = (user_id, action, correlation_id)
    return True


def _b2req(action: str, kind: DataKind, payload: dict[str, object]) -> Envelope:
    return Envelope(
        request_id="r-k",
        correlation_id="c-k",
        source="b4",
        target="b2",
        action=action,
        data_kind=kind,
        payload=dict(payload),
        user_id="admin",
    )


async def test_request_kind_mapping() -> None:
    assert request_kind("fhir.write") == DataKind.FHIR
    assert request_kind("tasks.write") == DataKind.PROPRIETARY
    assert request_kind("tasks.read") == DataKind.METADATA
    assert request_kind("fhir.read") == DataKind.METADATA
    assert request_kind("fhir.search") == DataKind.METADATA
    assert request_kind("ai.complete") == DataKind.PROPRIETARY
    assert request_kind("ingest") == DataKind.PROPRIETARY
    assert request_kind("vector.anonymized.search") == DataKind.PROPRIETARY
    assert request_kind("vector.patient.search") == DataKind.PROPRIETARY


async def test_misclassified_fhir_write_rejected() -> None:
    service = B2Service(MemoryStorage(), _allow_all)
    with pytest.raises(ContractError):
        await service.handle(
            _b2req("fhir.write", DataKind.METADATA, {"resourceType": "Patient", "id": "p1"})
        )
    reply = await service.handle(
        _b2req("fhir.write", DataKind.FHIR, {"resourceType": "Patient", "id": "p1"})
    )
    assert reply.data_kind == DataKind.FHIR


async def test_task_responses_are_proprietary() -> None:
    service = B2Service(MemoryStorage(), _allow_all)
    written = await service.handle(
        _b2req(
            "tasks.write",
            DataKind.PROPRIETARY,
            {"id": "t-k", "ownerId": "admin", "dueAt": "2030-01-01T00:00:00+00:00"},
        )
    )
    assert written.data_kind == DataKind.PROPRIETARY
    acked = await service.handle(_b2req("tasks.ack", DataKind.METADATA, {"id": "t-k"}))
    assert acked.data_kind == DataKind.PROPRIETARY


def _front(rid: str) -> Envelope:
    return Envelope(
        request_id=rid,
        correlation_id="c-p",
        source="frontend:coordinator",
        target="b4",
        action="tasks.write",
        data_kind=DataKind.PROPRIETARY,
        payload={"id": "t"},
        user_id="coordinator",
    )


async def test_pending_cap_and_prune() -> None:
    async def never(request: Envelope) -> Envelope:
        raise AssertionError("must not route when full")

    async def ok_reply(request: Envelope) -> Envelope:
        return request.reply(
            source="b2", action=request.action, payload={}, data_kind=DataKind.METADATA
        )

    router = B4Router(_allow_all, None, never, None, {"frontend:coordinator": "coordinator"})
    fresh = time.monotonic()
    for index in range(MAX_PENDING):
        router._pending[("frontend:coordinator", f"r-{index}")] = ("coordinator", fresh)
    with pytest.raises(TransportError):
        await router.handle(_front("r-new"))
    assert router.pending_count() == MAX_PENDING
    for key in list(router._pending):
        router._pending[key] = ("coordinator", 1.0)
    router._b2 = ok_reply
    reply = await router.handle(_front("r-fresh"))
    assert reply.request_id == "r-fresh"
    assert router.pending_count() == 0
