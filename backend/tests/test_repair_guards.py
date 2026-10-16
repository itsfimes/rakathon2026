from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest

from rakathon_backend.b2.iris.config import IrisFhirConfig, IrisSqlConfig
from rakathon_backend.b2.iris.fhir import DirectFhirAdapter
from rakathon_backend.b2.iris.screening_sql import (
    INVITATION_ID_WIDTH,
    LENGTHS,
    ScreeningSqlStore,
)
from rakathon_backend.b2.memory import MemoryStorage
from rakathon_backend.b2.screening import schema
from rakathon_backend.b2.service import B2Service
from rakathon_backend.bridge.client import BridgeClientConfig, EncryptedBridgeStorage
from rakathon_backend.bridge.crypto import BridgeCrypto, generate_key_file, load_key
from rakathon_backend.bridge.protocol import check_arguments
from rakathon_backend.bridge.replay import ReplayCache
from rakathon_backend.bridge.server import BridgeDispatcher
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import ContractError


def _bad_resources() -> list[dict[str, Any]]:
    return [
        {"resourceType": "ServiceRequest", "id": "sr-bad-1", "status": "active"},
        {"resourceType": "DocumentReference", "id": "doc-bad-1", "status": "current"},
        {
            "resourceType": "ServiceRequest",
            "id": "sr-bad-2",
            "status": "cured",
            "intent": "order",
            "subject": {"reference": "Patient/p-guard-1"},
        },
        {
            "resourceType": "ServiceRequest",
            "id": "sr-bad-3",
            "status": "active",
            "intent": "order",
            "subject": {"reference": "Patient/p-guard-1"},
            "note": "javascript:alert(1)",
        },
    ]


def _tx_bundle(resources: list[dict[str, Any]]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for item in resources:
        rtype = str(item["resourceType"])
        rid = str(item["id"])
        entries.append(
            {
                "fullUrl": f"urn:uuid:{rtype.lower()}-{rid}",
                "resource": dict(item),
                "request": {"method": "PUT", "url": f"{rtype}/{rid}"},
            }
        )
    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}


async def _allow(*, user_id: str, action: str, correlation_id: str) -> bool:
    _ = (user_id, action, correlation_id)
    return True


def _req(payload: dict[str, Any]) -> Envelope:
    return Envelope(
        request_id="r-1",
        correlation_id="c-1",
        source="b4",
        target="b2",
        action="fhir.write",
        data_kind=DataKind.FHIR,
        payload=dict(payload),
        user_id="admin",
    )


@pytest.mark.parametrize("bad", _bad_resources())
async def test_b2_direct_write_rejects_malformed(bad: dict[str, Any]) -> None:
    service = B2Service(MemoryStorage(), _allow)
    with pytest.raises(ContractError):
        await service.handle(_req(dict(bad)))


@pytest.mark.parametrize("bad", _bad_resources())
async def test_b2_transaction_rejects_malformed(bad: dict[str, Any]) -> None:
    service = B2Service(MemoryStorage(), _allow)
    patient = {"resourceType": "Patient", "id": "p-guard-1"}
    with pytest.raises(ContractError):
        await service.handle(_req(_tx_bundle([patient, dict(bad)])))


@pytest.mark.parametrize("bad", _bad_resources())
def test_memory_write_rejects_malformed(bad: dict[str, Any]) -> None:
    with pytest.raises(ContractError):
        MemoryStorage().fhir_write(dict(bad))


@pytest.mark.parametrize("bad", _bad_resources())
def test_memory_transaction_rejects_malformed(bad: dict[str, Any]) -> None:
    patient = {"resourceType": "Patient", "id": "p-guard-1"}
    with pytest.raises(ContractError):
        MemoryStorage().fhir_transaction(_tx_bundle([patient, dict(bad)]))


@pytest.mark.parametrize("bad", _bad_resources())
def test_bridge_protocol_rejects_malformed_resource(bad: dict[str, Any]) -> None:
    with pytest.raises(ContractError):
        check_arguments("fhir.write", {"resource": dict(bad)})


@pytest.mark.parametrize("bad", _bad_resources())
def test_bridge_protocol_rejects_malformed_bundle(bad: dict[str, Any]) -> None:
    patient = {"resourceType": "Patient", "id": "p-guard-1"}
    with pytest.raises(ContractError):
        check_arguments("fhir.write", {"bundle": _tx_bundle([patient, dict(bad)])})


class _CountingStore:
    def __init__(self) -> None:
        self.calls = 0

    def fhir_write(self, resource: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        return dict(resource)

    def fhir_transaction(self, bundle: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        return dict(bundle)


def _dispatcher(tmp_path: Path, store: Any) -> tuple[BridgeDispatcher, BridgeCrypto]:
    key_file = tmp_path / "guard.key"
    generate_key_file(key_file)
    crypto = BridgeCrypto(key=load_key(key_file), key_id="guard-key", ttl=60)
    return (BridgeDispatcher(crypto, store, ReplayCache()), crypto)


def test_bridge_dispatcher_rejects_before_store(tmp_path: Path) -> None:
    store = _CountingStore()
    dispatcher, crypto = _dispatcher(tmp_path, store)
    bad = {"resourceType": "ServiceRequest", "id": "sr-bad-1", "status": "active"}
    rid, token = crypto.encrypt_request("fhir.write", {"resource": bad})
    status, payload, _ = dispatcher.handle_outer({"keyId": "guard-key", "token": token})
    assert status == 200
    with pytest.raises(ContractError):
        crypto.decrypt_response(str(payload["token"]), rid, "fhir.write")
    assert store.calls == 0


def test_bridge_client_fails_before_network(tmp_path: Path) -> None:
    key_file = tmp_path / "client.key"
    generate_key_file(key_file)
    config = BridgeClientConfig(
        url="http://127.0.0.1:9/rpc",
        key_file=key_file,
        key_id="guard-key",
        allow_insecure_loopback=True,
    )
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    store = EncryptedBridgeStorage(config, client=client)
    try:
        with pytest.raises(ContractError):
            store.fhir_write({"resourceType": "ServiceRequest", "id": "x", "status": "active"})
        with pytest.raises(ContractError):
            store.fhir_transaction(
                {
                    "resourceType": "Bundle",
                    "type": "transaction",
                    "entry": [
                        {
                            "request": {"method": "POST", "url": "Patient/p1"},
                            "resource": {"resourceType": "Patient", "id": "p1"},
                            "fullUrl": "urn:uuid:patient-p1",
                        },
                        {
                            "request": {"method": "PUT", "url": "ServiceRequest/x"},
                            "resource": {
                                "resourceType": "ServiceRequest",
                                "id": "x",
                                "status": "active",
                            },
                            "fullUrl": "urn:uuid:sr-x",
                        },
                    ],
                }
            )
    finally:
        store.close()
    assert calls == []


def test_direct_iris_adapter_rejects_before_network() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={})

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://127.0.0.1:8765/fhir/r4",
        trust_env=False,
        follow_redirects=False,
    )
    adapter = DirectFhirAdapter(
        IrisFhirConfig(base_url="http://127.0.0.1:8765/fhir/r4", username="u", password="p"),
        client=client,
    )
    with pytest.raises(ContractError):
        adapter.write({"resourceType": "ServiceRequest", "id": "x", "status": "active"})
    with pytest.raises(ContractError):
        adapter.transaction(
            {
                "resourceType": "Bundle",
                "type": "transaction",
                "entry": [
                    {
                        "request": {"method": "PUT", "url": "DocumentReference/x"},
                        "resource": {"resourceType": "DocumentReference", "id": "x"},
                    }
                ],
            }
        )
    assert calls == []


async def test_valid_standalone_reference_is_persisted() -> None:
    store = MemoryStorage()
    service = B2Service(store, _allow)
    await service.handle(_req({"resourceType": "Patient", "id": "p-guard-1"}))
    valid = {
        "resourceType": "ServiceRequest",
        "id": "sr-guard-1",
        "status": "active",
        "intent": "order",
        "subject": {"reference": "Patient/p-guard-1"},
    }
    reply = await service.handle(_req(dict(valid)))
    assert reply.payload["count"] == 1
    assert store.fhir_read("ServiceRequest", "sr-guard-1") is not None


class _FakeCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[Any]]] = []
        self.rows: list[tuple[Any, ...]] = []
        self.rowcount = 1

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> None:
        self.calls.append((sql, list(params or [])))

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self.rows)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows[0] if self.rows else None


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


def _screen_row(inv: str, person: str) -> dict[str, str]:
    base = {name: "" for name in schema.HEADER}
    base.update(
        {
            "INVITATION_ID": inv,
            "PERSON_ID": person,
            "INVITATION_DATE": "14.01.2020",
            "AGE_BAND": "65-69",
            "VZP_TERRITORIAL_AREA": "PRAHA",
            "PRIOR_INVITATION_COUNT": "0",
            "INVITATION_SEQUENCE": "1",
            "FIRST_INVITATION": "A",
            "GP_REGISTERED": "N",
            "GP_REG_DURATION_BAND": "",
            "GYN_REGISTERED_FLAG": "N",
            "GYN_REG_DURATION_BAND": "",
            "NEVER_SCREENED_BEFORE_FLAG": "A",
            "SCREENING_3M_FLAG": "N",
            "SCREENING_6M_FLAG": "N",
            "SCREENING_12M_FLAG": "N",
        }
    )
    return base


def test_screening_longest_invitation_id_width() -> None:
    assert INVITATION_ID_WIDTH == 64
    assert LENGTHS["INVITATION_ID"] == 64
    longest = "INV" + "9" * 32
    assert len(longest) == 35
    checked = schema.validate_row(_screen_row(longest, "1" * 32))
    assert checked["INVITATION_ID"] == longest
    cursor = _FakeCursor()
    config = IrisSqlConfig(host="127.0.0.1", port=1972, namespace="NS", username="u", password="p")
    store = ScreeningSqlStore(config, factory=lambda: _FakeConn(cursor))
    result = store.init_db()
    assert result["status"] == "created"
    assert "INVITATION_ID VARCHAR(64)" in cursor.calls[0][0]
    cursor2 = _FakeCursor()
    store2 = ScreeningSqlStore(config, factory=lambda: _FakeConn(cursor2))
    out = store2.import_batch([_screen_row(longest, "1" * 32)])
    assert out == {"imported": 1, "skipped": 0, "total": 1}
    insert = [c for c in cursor2.calls if c[0].startswith("INSERT")]
    assert len(insert) == 1
    assert insert[0][1][0] == longest
