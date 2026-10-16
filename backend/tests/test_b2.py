from __future__ import annotations

import pytest

from rakathon_backend.b2.memory import MemoryStorage, StoredVector
from rakathon_backend.b2.service import B2Service
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import AuthError, ContractError

_PERMS = {
    "admin": {
        "fhir.read",
        "fhir.write",
        "tasks.read",
        "tasks.write",
        "tasks.ack",
        "vector.anonymized.search",
        "vector.patient.search",
    },
    "coordinator": {"fhir.read", "tasks.read", "tasks.write", "tasks.ack"},
    "clinician": {"fhir.read", "tasks.read", "tasks.ack", "vector.anonymized.search"},
    "viewer": {"fhir.read", "tasks.read"},
    "watchdog": {"tasks.read"},
}


async def _auth(*, user_id: str, action: str, correlation_id: str) -> bool:
    _ = correlation_id
    return action in _PERMS.get(user_id, set())


def _req(
    user: str,
    action: str,
    payload: dict[str, object],
    source: str = "b4",
    kind: DataKind = DataKind.METADATA,
) -> Envelope:
    return Envelope(
        request_id="r-1",
        correlation_id="c-1",
        source=source,
        target="b2",
        action=action,
        data_kind=kind,
        payload=dict(payload),
        user_id=user,
    )


async def test_viewer_denied_write_direct() -> None:
    service = B2Service(MemoryStorage(), _auth)
    with pytest.raises(AuthError):
        await service.handle(_req("viewer", "fhir.write", {"resourceType": "Patient", "id": "p1"}))
    with pytest.raises(AuthError):
        await service.handle(
            _req(
                "viewer",
                "tasks.write",
                {"id": "t1", "ownerId": "viewer", "dueAt": "2030-01-01T00:00:00+00:00"},
            )
        )


async def test_b6_checked_every_route() -> None:
    service = B2Service(MemoryStorage(), _auth)
    for action in ("fhir.read", "tasks.read", "tasks.ack"):
        payload: dict[str, object] = {"resourceType": "Patient"} if action == "fhir.read" else {}
        if action == "tasks.ack":
            payload = {"id": "missing"}
        with pytest.raises((AuthError, ContractError)):
            await service.handle(_req("ghost", action, payload))


async def test_task_lifecycle_ack_identity() -> None:
    service = B2Service(MemoryStorage(), _auth)
    task = {
        "id": "t-life",
        "ownerId": "clinician",
        "dueAt": "2030-01-01T00:00:00+00:00",
        "status": "OPEN",
        "requiredAckUserIds": ["clinician"],
        "acknowledgedBy": [],
        "patientRef": "Patient/p1",
        "version": 1,
    }
    reply = await service.handle(_req("admin", "tasks.write", task))
    assert reply.payload["task"]["id"] == "t-life"
    ack = await service.handle(_req("clinician", "tasks.ack", {"id": "t-life"}))
    assert ack.payload["task"]["status"] == "ACKED"
    again = await service.handle(_req("clinician", "tasks.ack", {"id": "t-life"}))
    assert again.payload["task"]["status"] == "ACKED"
    with pytest.raises(AuthError):
        await service.handle(_req("clinician", "tasks.ack", {"id": "t-life", "ackUser": "other"}))


async def test_fhir_write_read_search() -> None:
    store = MemoryStorage()
    service = B2Service(store, _auth)
    await service.handle(
        _req(
            "admin",
            "fhir.write",
            {"resourceType": "Patient", "id": "p5", "name": [{"text": "X"}]},
            kind=DataKind.FHIR,
        )
    )
    found = await service.handle(
        _req("clinician", "fhir.read", {"resourceType": "Patient", "id": "p5"})
    )
    assert found.payload["bundle"]["total"] == 1
    searched = await service.handle(_req("clinician", "fhir.read", {"resourceType": "Patient"}))
    assert searched.payload["bundle"]["total"] >= 1


async def test_vector_anon_denied_without_seed() -> None:
    service = B2Service(MemoryStorage(), _auth)
    with pytest.raises(ContractError):
        await service.handle(_req("clinician", "vector.anonymized.search", {"query": "x"}))


async def test_vector_anon_allowed_when_seeded() -> None:
    store = MemoryStorage()
    store.seed_synthetic_vector(StoredVector(vector_id="v1", text="synthetic note"))
    service = B2Service(store, _auth)
    reply = await service.handle(_req("clinician", "vector.anonymized.search", {"query": "x"}))
    assert reply.payload["count"] == 1


async def test_rejects_untrusted_service_caller() -> None:
    service = B2Service(MemoryStorage(), _auth)
    with pytest.raises(AuthError):
        await service.handle(_req("admin", "tasks.read", {}, source="b9"))
