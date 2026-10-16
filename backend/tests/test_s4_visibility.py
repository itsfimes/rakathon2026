from __future__ import annotations

from typing import Any

import pytest

from rakathon_backend.b2.memory import MemoryStorage
from rakathon_backend.b2.service import B2Service
from rakathon_backend.b4.reminders import ReminderStore
from rakathon_backend.b4.router import B4Router
from rakathon_backend.b6.permissions import load_matrix, privileged_users
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import ContractError


async def _allow_all(*, user_id: str, action: str, correlation_id: str) -> bool:
    _ = (user_id, action, correlation_id)
    return True


def _task(tid: str, owner: str, required: list[str], status: str = "OPEN") -> dict[str, Any]:
    return {
        "id": tid,
        "ownerId": owner,
        "dueAt": "2030-01-01T00:00:00+00:00",
        "status": status,
        "requiredAckUserIds": list(required),
        "acknowledgedBy": [],
        "patientRef": "Patient/p1",
        "version": 1,
    }


def _read_req(user: str, payload: dict[str, Any] | None = None) -> Envelope:
    return Envelope(
        request_id="r-v",
        correlation_id="c-v",
        source="b4",
        target="b2",
        action="tasks.read",
        data_kind=DataKind.METADATA,
        payload=dict(payload or {}),
        user_id=user,
    )


def _reminder(tid: str, owner: str) -> dict[str, Any]:
    return {
        "id": tid,
        "taskId": tid,
        "ownerId": owner,
        "requiredAckUserIds": [owner],
        "reason": "overdue",
    }


def _front(user: str, payload: dict[str, Any]) -> Envelope:
    return Envelope(
        request_id="r-r",
        correlation_id="c-r",
        source=f"frontend:{user}",
        target="b4",
        action="reminders.read",
        data_kind=DataKind.METADATA,
        payload=dict(payload),
        user_id=user,
    )


def _deliver(items: list[Any]) -> Envelope:
    return Envelope(
        request_id="r-d",
        correlation_id="c-d",
        source="b3",
        target="b4",
        action="reminders.deliver",
        data_kind=DataKind.PROPRIETARY,
        payload={"reminders": items},
        user_id="watchdog",
    )


async def test_tasks_read_scoped_to_member() -> None:
    store = MemoryStorage()
    store.tasks_write(_task("t1", "clinician", ["clinician"]))
    store.tasks_write(_task("t2", "viewer", ["viewer"]))
    service = B2Service(store, _allow_all)
    viewer = await service.handle(_read_req("viewer"))
    assert [t["id"] for t in viewer.payload["tasks"]] == ["t2"]
    clinician = await service.handle(_read_req("clinician"))
    assert [t["id"] for t in clinician.payload["tasks"]] == ["t1"]
    scoped = await service.handle(_read_req("viewer", {"id": "t1"}))
    assert scoped.payload["tasks"] == [] and scoped.payload["count"] == 0


async def test_privileged_users_read_all() -> None:
    policy = load_matrix()
    priv = privileged_users(policy)
    assert priv == frozenset({"admin", "coordinator", "watchdog"})
    store = MemoryStorage()
    store.tasks_write(_task("t1", "clinician", ["clinician"]))
    store.tasks_write(_task("t2", "viewer", ["viewer"]))
    service = B2Service(store, _allow_all, privileged_users=priv)
    for user in ("admin", "coordinator", "watchdog"):
        reply = await service.handle(_read_req(user))
        assert reply.payload["count"] == 2
    denied = B2Service(store, _allow_all)
    assert (await denied.handle(_read_req("watchdog"))).payload["count"] == 0


async def test_viewer_cannot_enumerate_reminders() -> None:
    router = B4Router(
        _allow_all,
        None,
        None,
        None,
        {"frontend:viewer": "viewer", "frontend:clinician": "clinician"},
    )
    await router.handle(_deliver([_reminder("t1", "clinician"), _reminder("t2", "viewer")]))
    viewer = await router.handle(_front("viewer", {}))
    assert viewer.data_kind == DataKind.PROPRIETARY
    assert [r["taskId"] for r in viewer.payload["reminders"]] == ["t2"]
    bypass = await router.handle(_front("viewer", {"ownerId": "clinician"}))
    assert [r["taskId"] for r in bypass.payload["reminders"]] == ["t2"]


async def test_privileged_reminder_filter_exact() -> None:
    router = B4Router(
        _allow_all,
        None,
        None,
        None,
        {"frontend:coordinator": "coordinator"},
        privileged_users=frozenset({"coordinator"}),
    )
    await router.handle(_deliver([_reminder("t1", "clinician"), _reminder("t2", "viewer")]))
    everything = await router.handle(_front("coordinator", {}))
    assert everything.payload["count"] == 2
    filtered = await router.handle(_front("coordinator", {"ownerId": "clinician"}))
    assert [r["taskId"] for r in filtered.payload["reminders"]] == ["t1"]
    substr = await router.handle(_front("coordinator", {"ownerId": "clin"}))
    assert substr.payload["count"] == 0


async def test_malformed_delivery_refused_atomically() -> None:
    router = B4Router(_allow_all, None, None, None, {"frontend:viewer": "viewer"})
    with pytest.raises(ContractError):
        await router.handle(_deliver([_reminder("t1", "viewer"), {"taskId": "bad"}]))
    reply = await router.handle(_front("viewer", {}))
    assert reply.payload["count"] == 0


async def test_reminder_store_caps_and_upserts() -> None:
    store = ReminderStore(capacity=3)
    store.store_all([_reminder(f"t{i}", f"owner{i}") for i in range(3)])
    assert len(store) == 3
    store.store_all([_reminder("t3", "owner3")])
    assert len(store) == 3
    visible = store.visible("owner3", frozenset(), None)
    assert [r["taskId"] for r in visible] == ["t3"]
    store.store_all([dict(_reminder("t3", "owner3"), reason="missing_ack")])
    assert len(store) == 3
