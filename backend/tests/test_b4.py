from __future__ import annotations

import asyncio
from typing import Any

import pytest

from rakathon_backend.b4.router import B4Router
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import AuthError, ContractError

_ALLOW = {
    ("coordinator", "ingest"),
    ("coordinator", "tasks.write"),
    ("coordinator", "reminders.read"),
    ("clinician", "tasks.ack"),
    ("clinician", "reminders.read"),
    ("clinician", "ai.complete"),
    ("viewer", "reminders.read"),
}


async def _auth(*, user_id: str, action: str, correlation_id: str) -> bool:
    _ = correlation_id
    return (user_id, action) in _ALLOW


def _front(user: str, action: str, payload: dict[str, Any], rid: str = "r-1") -> Envelope:
    return Envelope(
        request_id=rid,
        correlation_id="c-1",
        source=f"frontend:{user}",
        target="b4",
        action=action,
        data_kind=DataKind.METADATA,
        payload=payload,
        user_id=user,
    )


def _ok_downstream(action: str) -> Any:
    async def call(request: Envelope) -> Envelope:
        return request.reply(
            source="b2", action=action, payload={"echo": True}, data_kind=DataKind.METADATA
        )

    return call


async def test_forged_userid_denied() -> None:
    router = B4Router(
        _auth, None, _ok_downstream("tasks.read"), None, {"frontend:viewer": "viewer"}
    )
    forged = Envelope(
        request_id="r-1",
        correlation_id="c-1",
        source="frontend:viewer",
        target="b4",
        action="tasks.read",
        data_kind=DataKind.METADATA,
        payload={},
        user_id="admin",
    )
    with pytest.raises(AuthError):
        await router.handle(forged)


async def test_b4_verifies_b6_before_routing() -> None:
    async def deny(*, user_id: str, action: str, correlation_id: str) -> bool:
        _ = (user_id, action, correlation_id)
        return False

    router = B4Router(deny, None, _ok_downstream("tasks.read"), None, {"frontend:viewer": "viewer"})
    with pytest.raises(AuthError):
        await router.handle(_front("viewer", "tasks.read", {}))


async def test_concurrent_ids_cleanup() -> None:
    release = asyncio.Event()
    calls = 0

    async def slow(request: Envelope) -> Envelope:
        nonlocal calls
        calls += 1
        if calls == 1:
            await release.wait()
        return request.reply(
            source="b2", action=request.action, payload={}, data_kind=DataKind.METADATA
        )

    router = B4Router(
        _auth,
        None,
        slow,
        None,
        {"frontend:coordinator": "coordinator", "frontend:clinician": "clinician"},
    )
    t1 = asyncio.create_task(
        router.handle(_front("coordinator", "tasks.write", {"id": "t1"}, rid="same-id"))
    )
    await asyncio.sleep(0.02)
    other = await router.handle(_front("clinician", "tasks.ack", {"id": "t1"}, rid="same-id"))
    assert other.request_id == "same-id"
    with pytest.raises(ContractError):
        await router.handle(_front("coordinator", "tasks.write", {"id": "t1"}, rid="same-id"))
    release.set()
    first = await t1
    assert first.request_id == "same-id"
    assert router.pending_count() == 0


async def test_ai_result_returns_to_caller_no_loop() -> None:
    async def b5(request: Envelope) -> Envelope:
        assert request.source == "b4"
        assert request.target == "b5"
        return request.reply(
            source="b5",
            action="ai.complete",
            payload={"answer": "hi", "mode": "mock"},
            data_kind=DataKind.PROPRIETARY,
        )

    router = B4Router(_auth, None, None, b5, {"frontend:clinician": "clinician"})
    reply = await router.handle(_front("clinician", "ai.complete", {"prompt": "hello"}))
    assert reply.source == "b4"
    assert reply.target == "frontend:clinician"
    assert reply.payload["answer"] == "hi"


async def test_b3_reminders_stored_and_read() -> None:
    router = B4Router(
        _auth,
        None,
        None,
        None,
        {"frontend:coordinator": "coordinator", "frontend:clinician": "clinician"},
    )
    deliver = Envelope(
        request_id="r-d",
        correlation_id="c-d",
        source="b3",
        target="b4",
        action="reminders.deliver",
        data_kind=DataKind.PROPRIETARY,
        payload={
            "reminders": [
                {
                    "id": "t1",
                    "taskId": "t1",
                    "ownerId": "clinician",
                    "requiredAckUserIds": ["clinician"],
                    "reason": "overdue",
                }
            ]
        },
        user_id="watchdog",
    )
    stored = await router.handle(deliver)
    assert stored.payload["stored"] == 1
    reply = await router.handle(_front("clinician", "reminders.read", {}))
    assert reply.payload["count"] == 1
