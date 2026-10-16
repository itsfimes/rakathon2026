from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from typing import Any

import httpx
import pytest
from direct_fixtures import outcome, transaction

from rakathon_backend.b1.outcome import check_import, prepare_import
from rakathon_backend.b2.ingestion import persist_import
from rakathon_backend.b2.memory import MemoryStorage
from rakathon_backend.b5.direct import DirectAdapter
from rakathon_backend.b5.direct_http import DirectHttpTransport, DirectProviderConfig
from rakathon_backend.common.contracts import DataKind
from rakathon_backend.common.errors import ContractError, TransportError
from rakathon_backend.common.fhir import check_bundle, check_resource
from rakathon_backend.common.rpc import new_envelope
from rakathon_backend.runtime.application import BackendApp, fresh_tokens


def test_all_eight_r4_models_and_transaction() -> None:
    bundle = transaction()
    resources: list[dict[str, Any]] = [
        {
            "resourceType": "Condition",
            "id": "condition",
            "code": {"text": "Synthetic"},
            "subject": {"reference": "Patient/synthetic-1"},
        },
        {
            "resourceType": "DiagnosticReport",
            "id": "report",
            "status": "final",
            "code": {"text": "Synthetic"},
            "subject": {"reference": "Patient/synthetic-1"},
            "result": [{"reference": "Observation/synthetic-observation"}],
            "issued": "2026-01-01T00:00:00Z",
        },
        {
            "resourceType": "DocumentReference",
            "id": "document",
            "status": "current",
            "subject": {"reference": "Patient/synthetic-1"},
            "content": [{"attachment": {"title": "Synthetic source", "contentType": "text/plain"}}],
        },
        {
            "resourceType": "ServiceRequest",
            "id": "request",
            "status": "active",
            "intent": "order",
            "subject": {"reference": "Patient/synthetic-1"},
        },
        {
            "resourceType": "Procedure",
            "id": "procedure",
            "status": "completed",
            "subject": {"reference": "Patient/synthetic-1"},
        },
        {
            "resourceType": "Provenance",
            "id": "provenance",
            "recorded": "2026-01-01T00:00:00Z",
            "target": [{"reference": "Patient/synthetic-1"}],
            "agent": [{"who": {"reference": "Patient/synthetic-1"}}],
        },
    ]
    bundle["entry"].extend(
        {
            "resource": item,
            "request": {"method": "PUT", "url": f"{item['resourceType']}/{item['id']}"},
        }
        for item in resources
    )
    before = copy.deepcopy(bundle)
    check_bundle(bundle)
    assert bundle == before
    check_resource(
        {
            "resourceType": "Observation",
            "id": "boolean",
            "status": "final",
            "code": {"text": "Synthetic"},
            "valueBoolean": False,
        }
    )


@pytest.mark.parametrize(
    "resource",
    [
        {"resourceType": "Patient", "id": " whitespace "},
        {"resourceType": "Patient", "id": "p", "active": 0},
        {"resourceType": "Patient", "id": "p", "active": "false"},
        {"resourceType": "Patient", "id": "p", "gender": "custom"},
        {
            "resourceType": "Condition",
            "id": "c",
            "code": {"text": "Synthetic"},
            "subject": {},
        },
        {
            "resourceType": "Condition",
            "id": "c",
            "code": {"text": "Synthetic"},
            "subject": {"reference": "Patient/p"},
            "verificationStatus": {"coding": [{"system": "custom-system", "code": "confirmed"}]},
        },
        {
            "resourceType": "ServiceRequest",
            "id": "r",
            "status": "active",
            "intent": "custom",
            "subject": {"reference": "Patient/p"},
        },
        {
            "resourceType": "DocumentReference",
            "id": "d",
            "status": "current",
            "docStatus": "custom",
            "content": [{"attachment": {"title": "Synthetic"}}],
        },
        {
            "resourceType": "Provenance",
            "id": "p",
            "target": [{"reference": "Patient/p"}],
            "recorded": "2026-01-01T00:00:00Z",
        },
    ],
)
def test_raw_types_required_fields_and_controlled_codes(resource: dict[str, Any]) -> None:
    with pytest.raises(ContractError):
        check_resource(resource)


@pytest.mark.parametrize(
    "mutation", ["source", "tag", "condition", "subject", "missing-request", "dangling"]
)
def test_independent_import_boundary_revalidates(mutation: str) -> None:
    prepared = prepare_import(outcome("incomplete"), "urn:sha256:" + "a" * 64, "synthetic-1")
    bundle = prepared["bundle"]
    context = {key: prepared[key] for key in ("status", "issues", "sourceUrn", "patientId")}
    if mutation == "source":
        bundle["entry"][0]["resource"]["meta"]["source"] = "urn:sha256:" + "b" * 64
    elif mutation == "tag":
        bundle["entry"][0]["resource"]["meta"]["tag"][0]["code"] = "complete"
    elif mutation == "condition":
        del bundle["entry"][0]["request"]["ifNoneMatch"]
    elif mutation == "subject":
        bundle["entry"][1]["resource"]["subject"]["reference"] = "Patient/other"
    elif mutation == "missing-request":
        del bundle["entry"][0]["request"]
    elif mutation == "dangling":
        bundle["entry"][1]["resource"]["derivedFrom"] = [{"reference": "Observation/missing"}]
    store = MemoryStorage()
    with pytest.raises(ContractError):
        persist_import(store, bundle, context)
    assert not store.fhir


def test_atomic_create_only_conflict_preserves_existing() -> None:
    prepared = prepare_import(outcome("incomplete"), "urn:sha256:" + "a" * 64, "synthetic-1")
    context = {key: prepared[key] for key in ("status", "issues", "sourceUrn", "patientId")}
    check_import(prepared["bundle"], context)
    store = MemoryStorage()
    first = prepared["bundle"]["entry"][0]["resource"]
    store.fhir[("Patient", first["id"])] = first
    before = copy.deepcopy(store.fhir)
    with pytest.raises(ContractError):
        store.fhir_transaction(prepared["bundle"])
    assert store.fhir == before


def test_b1_independent_subset_gate_rejects_bypassed_adapter_fields() -> None:
    value = outcome()
    value["bundle"]["entry"][0]["resource"]["text"] = {
        "status": "generated",
        "div": "<div>synthetic</div>",
    }
    with pytest.raises(ContractError):
        prepare_import(value, "urn:sha256:" + "a" * 64, "synthetic-1")


async def test_direct_kill_cancels_provider_and_closes_client(tmp_path: Path) -> None:
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def send(request: httpx.Request) -> httpx.Response:
        started.set()
        try:
            await asyncio.sleep(30)
        finally:
            cancelled.set()
        return httpx.Response(500)

    transport = DirectHttpTransport(
        DirectProviderConfig(
            base_url="https://synthetic.invalid",
            model="synthetic",
            auth_scheme="bearer",
            api_key="synthetic",
            allow_remote=True,
        ),
        transport=httpx.MockTransport(send),
    )
    app = BackendApp(
        tmp_path / "uds", fresh_tokens(), ai_adapter=DirectAdapter(transport), ai_mode="direct"
    )
    await app.start()
    client = app.frontend_client("admin")
    call = asyncio.create_task(
        client.call(
            new_envelope(
                source="frontend:admin",
                target="b4",
                action="ai.complete",
                data_kind=DataKind.PROPRIETARY,
                payload={"prompt": "Synthetic"},
                user_id="admin",
            ),
            expect_source="b4",
        )
    )
    try:
        await asyncio.wait_for(started.wait(), 2)
        assert app.gateway is not None and app.gateway.mode == "direct"
        await app.gateway.trip()
        with pytest.raises(TransportError):
            await call
        assert cancelled.is_set()
        with pytest.raises(TransportError) as closed:
            await transport.generate("Synthetic")
        assert closed.value.code == "ai_closed"
    finally:
        await app.close()
