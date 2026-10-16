from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import httpx
import pytest

from rakathon_backend.b2.iris.config import IrisFhirConfig
from rakathon_backend.b2.iris.fhir import DirectFhirAdapter
from rakathon_backend.b2.iris.fhir_only import FhirOnlyStorage
from rakathon_backend.b2.memory import MemoryStorage
from rakathon_backend.b2.service import B2Service
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import AuthError, ContractError, TransportError
from rakathon_backend.common.kinds import request_kind
from rakathon_backend.common.rpc import new_envelope
from rakathon_backend.runtime.application import BackendApp, fresh_tokens

LOOPBACK = "http://127.0.0.1:8765/fhir/r4"


def _adapter(handler: object) -> DirectFhirAdapter:
    client = httpx.Client(
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]  # :>
        base_url=LOOPBACK,
        trust_env=False,
        follow_redirects=False,
    )
    return DirectFhirAdapter(
        IrisFhirConfig(base_url=LOOPBACK, username="u", password="p"), client=client
    )


def _bundle(total: object, ids: list[str]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "resourceType": "Bundle",
        "type": "searchset",
        "entry": [{"resource": {"resourceType": "Patient", "id": rid}} for rid in ids],
    }
    if total != "absent":
        body["total"] = total
    return body


def test_search_legacy_list_preserved() -> None:
    adapter = _adapter(lambda r: httpx.Response(200, json=_bundle(6, ["a", "b"])))
    assert len(adapter.search("Patient", {})) == 2


def test_search_with_total_keeps_server_total() -> None:
    adapter = _adapter(lambda r: httpx.Response(200, json=_bundle(6, ["a", "b"])))
    items, total = adapter.search_with_total("Patient", {})
    assert len(items) == 2
    assert total == 6


def test_count_only_empty_entries_keeps_total() -> None:
    adapter = _adapter(lambda r: httpx.Response(200, json=_bundle(6, [])))
    items, total = adapter.search_with_total("Patient", {"_summary": "count"})
    assert items == []
    assert total == 6


def test_total_missing_is_none() -> None:
    adapter = _adapter(lambda r: httpx.Response(200, json=_bundle("absent", ["a"])))
    items, total = adapter.search_with_total("Patient", {})
    assert len(items) == 1
    assert total is None


@pytest.mark.parametrize("bad", [True, False, "6", 6.0, -1, None, [6]])
def test_total_invalid_rejected(bad: object) -> None:
    adapter = _adapter(lambda r: httpx.Response(200, json=_bundle(bad, [])))
    with pytest.raises(ContractError):
        adapter.search_with_total("Patient", {"_summary": "count"})


async def _allow_all(*, user_id: str, action: str, correlation_id: str) -> bool:
    _ = (user_id, action, correlation_id)
    return True


def _search_req(payload: dict[str, str]) -> Envelope:
    return Envelope(
        request_id="r-1",
        correlation_id="c-1",
        source="b4",
        target="b2",
        action="fhir.search",
        data_kind=DataKind.METADATA,
        payload=dict(payload),
        user_id="admin",
    )


async def test_b2_normal_search_additive_server_total() -> None:
    adapter = _adapter(lambda r: httpx.Response(200, json=_bundle(6, ["a", "b"])))
    service = B2Service(FhirOnlyStorage(adapter), _allow_all, mode="iris-fhir")
    reply = await service.handle(_search_req({"resourceType": "Patient"}))
    assert reply.payload["bundle"]["total"] == 2
    assert reply.payload["serverTotal"] == 6
    assert reply.payload["mode"] == "iris-fhir"


async def test_b2_count_only_total_is_server_total() -> None:
    adapter = _adapter(lambda r: httpx.Response(200, json=_bundle(6, [])))
    service = B2Service(FhirOnlyStorage(adapter), _allow_all, mode="iris-fhir")
    reply = await service.handle(_search_req({"resourceType": "Patient", "_summary": "count"}))
    assert reply.payload["bundle"]["total"] == 6
    assert reply.payload["bundle"]["entry"] == []
    assert reply.payload["serverTotal"] == 6


async def test_b2_memory_branch_has_no_server_total() -> None:
    store = MemoryStorage()
    store.fhir_write({"resourceType": "Patient", "id": "p1"})
    service = B2Service(store, _allow_all, mode="mock")
    reply = await service.handle(_search_req({"resourceType": "Patient"}))
    assert reply.payload["bundle"]["total"] == 1
    assert "serverTotal" not in reply.payload


async def test_valid_writes_validated_pre_network() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={})

    adapter = _adapter(handler)
    with pytest.raises(ContractError):
        adapter.write({"resourceType": "Patient"})
    with pytest.raises(ContractError):
        adapter.write({"resourceType": "Patient", "id": "p1", "note": "javascript:evil()"})
    assert calls == []


def _runtime_dir() -> Path:
    base = Path("/tmp/opencode")
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="rakfhir", dir=str(base)))


def _probe_fixture(pid: str, name: str) -> dict[str, Any]:
    return {
        "resourceType": "Patient",
        "id": pid,
        "active": False,
        "name": [{"text": name}],
        "identifier": [{"system": "urn:rakathon:verification", "value": pid}],
        "meta": {"tag": [{"code": "SYNTHETIC-LIVE-PROBE"}]},
    }


def _live_handler(state: dict[str, Any]) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path.startswith("/fhir/r4/Patient/"):
            pid = path.rsplit("/", 1)[-1]
            if pid in state:
                return httpx.Response(200, json=state[pid])
            return httpx.Response(404, json={})
        if request.method == "GET" and path == "/fhir/r4/Patient":
            return httpx.Response(
                200, json={"resourceType": "Bundle", "type": "searchset", "entry": []}
            )
        if request.method == "PUT" and path.startswith("/fhir/r4/Patient/"):
            state[path.rsplit("/", 1)[-1]] = json.loads(request.content.decode())
            return httpx.Response(200, json=state[path.rsplit("/", 1)[-1]])
        return httpx.Response(400, json={})

    return handler


async def test_app_fhir_lifecycle_and_fail_closed() -> None:
    state: dict[str, Any] = {}
    client = httpx.Client(
        transport=httpx.MockTransport(_live_handler(state)),
        base_url=LOOPBACK,
        trust_env=False,
        follow_redirects=False,
    )
    adapter = DirectFhirAdapter(
        IrisFhirConfig(base_url=LOOPBACK, username="u", password="p"), client=client
    )
    app = BackendApp(
        _runtime_dir(), fresh_tokens(), store=FhirOnlyStorage(adapter), mode="iris-fhir"
    )
    await app.start()
    try:
        assert app.mode == "iris-fhir"
        assert app.b3service is not None
        assert app.b3service._loop_task is None
        admin = app.frontend_client("admin")
        viewer = app.frontend_client("viewer")
        pid = "rakathon-probe-offline1"
        missing = await admin.call(
            new_envelope(
                source="frontend:admin",
                target="b4",
                action="fhir.read",
                data_kind=request_kind("fhir.read"),
                payload={"resourceType": "Patient", "id": pid},
                user_id="admin",
            ),
            expect_source="b4",
        )
        assert missing.payload["bundle"]["total"] == 0
        created = await admin.call(
            new_envelope(
                source="frontend:admin",
                target="b4",
                action="fhir.write",
                data_kind=request_kind("fhir.write"),
                payload=_probe_fixture(pid, "Synthetic Probe Rev1"),
                user_id="admin",
            ),
            expect_source="b4",
        )
        assert created.payload["stored"] == [f"Patient/{pid}"]
        assert created.payload["mode"] == "iris-fhir"
        read_back = await admin.call(
            new_envelope(
                source="frontend:admin",
                target="b4",
                action="fhir.read",
                data_kind=request_kind("fhir.read"),
                payload={"resourceType": "Patient", "id": pid},
                user_id="admin",
            ),
            expect_source="b4",
        )
        entries = read_back.payload["bundle"]["entry"]
        assert entries[0]["resource"]["name"] == [{"text": "Synthetic Probe Rev1"}]
        updated = await admin.call(
            new_envelope(
                source="frontend:admin",
                target="b4",
                action="fhir.write",
                data_kind=request_kind("fhir.write"),
                payload=_probe_fixture(pid, "Synthetic Probe Rev2"),
                user_id="admin",
            ),
            expect_source="b4",
        )
        assert updated.payload["stored"] == [f"Patient/{pid}"]
        read_again = await admin.call(
            new_envelope(
                source="frontend:admin",
                target="b4",
                action="fhir.read",
                data_kind=request_kind("fhir.read"),
                payload={"resourceType": "Patient", "id": pid},
                user_id="admin",
            ),
            expect_source="b4",
        )
        assert read_again.payload["bundle"]["entry"][0]["resource"]["name"] == [
            {"text": "Synthetic Probe Rev2"}
        ]
        with pytest.raises(AuthError):
            await viewer.call(
                new_envelope(
                    source="frontend:viewer",
                    target="b4",
                    action="fhir.write",
                    data_kind=request_kind("fhir.write"),
                    payload=_probe_fixture("rakathon-probe-denied", "Synthetic Probe"),
                    user_id="viewer",
                ),
                expect_source="b4",
            )
        assert "rakathon-probe-denied" not in state
        with pytest.raises(TransportError) as exc_tasks:
            await admin.call(
                new_envelope(
                    source="frontend:admin",
                    target="b4",
                    action="tasks.write",
                    data_kind=request_kind("tasks.write"),
                    payload={
                        "id": "t1",
                        "ownerId": "admin",
                        "dueAt": "2030-01-01T00:00:00+00:00",
                    },
                    user_id="admin",
                ),
                expect_source="b4",
            )
        assert exc_tasks.value.code == "not_configured"
        with pytest.raises(TransportError) as exc_vector:
            await admin.call(
                new_envelope(
                    source="frontend:admin",
                    target="b4",
                    action="vector.patient.search",
                    data_kind=request_kind("vector.patient.search"),
                    payload={"query": "[0.1]", "limit": 5},
                    user_id="admin",
                ),
                expect_source="b4",
            )
        assert exc_vector.value.code == "not_configured"
    finally:
        await app.close()
