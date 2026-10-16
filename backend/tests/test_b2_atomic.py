from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest

from rakathon_backend.b2.memory import MemoryStorage
from rakathon_backend.b2.service import B2Service
from rakathon_backend.cli import _async_main
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import ContractError


async def _auth(*, user_id: str, action: str, correlation_id: str) -> bool:
    _ = (user_id, action, correlation_id)
    return True


def _req(
    payload: dict[str, Any],
    action: str = "fhir.write",
    kind: DataKind = DataKind.FHIR,
) -> Envelope:
    return Envelope(
        request_id="r-1",
        correlation_id="c-1",
        source="b4",
        target="b2",
        action=action,
        data_kind=kind,
        payload=dict(payload),
        user_id="admin",
    )


def _tx_entry(method: str, url: str, rtype: str, rid: str) -> dict[str, Any]:
    return {
        "request": {"method": method, "url": url},
        "resource": {"resourceType": rtype, "id": rid},
    }


async def test_transaction_success_and_mode() -> None:
    service = B2Service(MemoryStorage(), _auth, mode="bridge")
    bundle = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            _tx_entry("POST", "Patient/p1", "Patient", "p1"),
            _tx_entry("PUT", "Patient/p2", "Patient", "p2"),
        ],
    }
    reply = await service.handle(_req(bundle))
    assert reply.payload["count"] == 2
    assert reply.payload["mode"] == "bridge"
    assert reply.payload["bundle"]["type"] == "transaction-response"


async def test_transaction_failure_writes_nothing() -> None:
    store = MemoryStorage()
    service = B2Service(store, _auth)
    bundle = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            _tx_entry("POST", "Patient/p-good", "Patient", "p-good"),
            _tx_entry("DELETE", "Patient/p-good", "Patient", "p-good"),
        ],
    }
    with pytest.raises(ContractError):
        await service.handle(_req(bundle))
    assert store.fhir_read("Patient", "p-good") is None


async def test_transaction_rejects_empty_and_malformed() -> None:
    service = B2Service(MemoryStorage(), _auth)
    with pytest.raises(ContractError):
        await service.handle(_req({"resourceType": "Bundle", "type": "transaction", "entry": []}))
    malformed = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [{"resource": {"resourceType": "Patient", "id": "p1"}}],
    }
    with pytest.raises(ContractError):
        await service.handle(_req(malformed))


async def test_plain_bundle_is_atomic() -> None:
    store = MemoryStorage()
    service = B2Service(store, _auth)
    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {"resource": {"resourceType": "Patient", "id": "p-ok"}},
            {"resource": {"resourceType": "Patient"}},
        ],
    }
    with pytest.raises(ContractError):
        await service.handle(_req(bundle))
    assert store.fhir_read("Patient", "p-ok") is None


async def test_genuine_mode_not_mock() -> None:
    service = B2Service(MemoryStorage(), _auth, mode="bridge")
    reply = await service.handle(_req({"resourceType": "Patient", "id": "px"}))
    assert reply.payload["mode"] == "bridge"
    task = {
        "id": "tm",
        "ownerId": "nurse",
        "dueAt": "2030-01-01T00:00:00+00:00",
    }
    tasks = await service.handle(_req(task, action="tasks.write"))
    assert tasks.payload["mode"] == "bridge"


class SlowStore(MemoryStorage):
    def fhir_read(self, resource_type: str, rid: str) -> dict[str, Any] | None:
        time.sleep(0.3)
        return super().fhir_read(resource_type, rid)


async def test_storage_does_not_block_event_loop() -> None:
    service = B2Service(SlowStore(), _auth)
    ticks = 0
    done = False

    async def ticker() -> None:
        nonlocal ticks, done
        while not done:
            ticks += 1
            await asyncio.sleep(0.01)

    task = asyncio.create_task(ticker())
    try:
        reply = await service.handle(
            _req({"resourceType": "Patient", "id": "p-slow"}, action="fhir.read")
        )
        assert reply.payload["bundle"]["total"] == 0
    finally:
        done = True
        await task
    assert ticks >= 5


async def test_bridge_keygen_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "bridge.key"
    code = await _async_main(["bridge-keygen", "--path", str(target), "--key-id", "kid-1"])
    assert code == 0
    out = capsys.readouterr().out
    assert "kid-1" in out and str(target) in out
    assert target.read_bytes().strip().decode() not in out


async def test_serve_bridge_refuses_without_egress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("RAKATHON_ALLOW_IRIS_EGRESS", raising=False)
    monkeypatch.delenv("RAKATHON_BRIDGE_URL", raising=False)
    code = await _async_main(["serve", "--storage", "bridge", "--runtime-dir", str(tmp_path)])
    assert code == 2
