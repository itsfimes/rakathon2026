from __future__ import annotations

from typing import Any

import pytest

from rakathon_backend.b2.memory import MemoryStorage
from rakathon_backend.b2.service import B2Service
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import AuthError, ContractError

_PERMS = {
    "admin": {"tasks.read", "tasks.write", "tasks.ack"},
    "coordinator": {"tasks.read", "tasks.write", "tasks.ack"},
    "clinician": {"tasks.read", "tasks.ack"},
    "viewer": {"tasks.read"},
    "watchdog": {"tasks.read"},
}


async def _auth(*, user_id: str, action: str, correlation_id: str) -> bool:
    _ = correlation_id
    return action in _PERMS.get(user_id, set())


def _req(user: str, action: str, payload: dict[str, Any]) -> Envelope:
    return Envelope(
        request_id="r-1",
        correlation_id="c-1",
        source="b4",
        target="b2",
        action=action,
        data_kind=DataKind.PROPRIETARY,
        payload=dict(payload),
        user_id=user,
    )


def _task(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "t-s4",
        "ownerId": "clinician",
        "dueAt": "2030-01-01T00:00:00+00:00",
        "requiredAckUserIds": ["clinician"],
    }
    if payload:
        base.update(payload)
    return base


async def test_forged_acknowledged_by_rejected() -> None:
    service = B2Service(MemoryStorage(), _auth)
    with pytest.raises(ContractError):
        await service.handle(_req("admin", "tasks.write", _task({"acknowledgedBy": ["x"]})))


async def test_forged_final_status_rejected() -> None:
    service = B2Service(MemoryStorage(), _auth)
    for status in ("ACKED", "DONE"):
        with pytest.raises(ContractError):
            await service.handle(_req("admin", "tasks.write", _task({"status": status})))


async def test_forged_version_rejected() -> None:
    service = B2Service(MemoryStorage(), _auth)
    for bad in (2, 0, -1, "1", 1.0, True, False, None):
        with pytest.raises(ContractError):
            await service.handle(_req("admin", "tasks.write", _task({"version": bad})))


async def test_duplicate_write_cannot_erase_ack() -> None:
    store = MemoryStorage()
    service = B2Service(store, _auth)
    await service.handle(_req("admin", "tasks.write", _task()))
    await service.handle(_req("clinician", "tasks.ack", {"id": "t-s4"}))
    with pytest.raises(ContractError):
        await service.handle(_req("admin", "tasks.write", _task()))
    items = store.tasks_read("t-s4")
    assert items[0]["status"] == "ACKED"
    assert items[0]["acknowledgedBy"] == ["clinician"]


async def test_ack_requires_membership_no_bypass() -> None:
    service = B2Service(MemoryStorage(), _auth)
    await service.handle(_req("admin", "tasks.write", _task()))
    with pytest.raises(AuthError):
        await service.handle(_req("coordinator", "tasks.ack", {"id": "t-s4"}))
    with pytest.raises(AuthError):
        await service.handle(_req("admin", "tasks.ack", {"id": "t-s4"}))


async def test_owner_outside_required_may_ack() -> None:
    async def wide_auth(*, user_id: str, action: str, correlation_id: str) -> bool:
        _ = correlation_id
        return user_id in ("admin", "owner", "member", "stranger") and action.startswith("tasks.")

    store = MemoryStorage()
    service = B2Service(store, wide_auth)
    task = _task({"id": "t-own", "ownerId": "owner", "requiredAckUserIds": ["member"]})
    await service.handle(_req("admin", "tasks.write", task))
    await service.handle(_req("owner", "tasks.ack", {"id": "t-own"}))
    with pytest.raises(AuthError):
        await service.handle(_req("stranger", "tasks.ack", {"id": "t-own"}))


async def test_ack_idempotent_no_version_bump() -> None:
    store = MemoryStorage()
    service = B2Service(store, _auth)
    await service.handle(_req("admin", "tasks.write", _task()))
    await service.handle(_req("clinician", "tasks.ack", {"id": "t-s4"}))
    first = store.tasks_read("t-s4")[0]
    await service.handle(_req("clinician", "tasks.ack", {"id": "t-s4"}))
    second = store.tasks_read("t-s4")[0]
    assert first["version"] == 2
    assert second["version"] == 2
    assert second["acknowledgedBy"] == ["clinician"]
