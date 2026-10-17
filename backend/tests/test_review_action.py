from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from rakathon_backend.b2.memory import MemoryStorage
from rakathon_backend.b2.service import B2Service
from rakathon_backend.b4.router import B4Router, web_envelope
from rakathon_backend.b6.permissions import check, load_matrix
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import AuthError, ContractError
from rakathon_backend.uploads.review_validation import prepare_review_import

PATIENT_ID = "target-1"
PATIENT_REF = "Patient/target-1"
SOURCE = "urn:sha256:" + "a" * 64
APPROVAL = "approval-1"
ALIAS = "model-p9"


def _candidate() -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "resource": {"resourceType": "Patient", "id": ALIAS},
                "request": {"method": "PUT", "url": "Patient/" + ALIAS},
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "o1",
                    "status": "final",
                    "code": {"text": "GLU"},
                    "subject": {"reference": "Patient/" + ALIAS},
                },
                "request": {"method": "PUT", "url": "Observation/o1"},
            },
        ],
    }


def _prepared() -> dict[str, Any]:
    out: dict[str, Any] = prepare_review_import(
        json.dumps(_candidate()),
        patient_id=PATIENT_ID,
        source_urn=SOURCE,
        approval_id=APPROVAL,
        patient_confirmed=True,
    )
    return out


def _payload(prepared: dict[str, Any]) -> dict[str, Any]:
    return {"bundle": copy.deepcopy(prepared["bundle"]), "context": dict(prepared["context"])}


class _FakeReviewStore:
    def __init__(self, receipt: dict[str, Any] | None = None) -> None:
        self.calls = 0
        self.last_bundle: dict[str, Any] | None = None
        self.last_patient: str | None = None
        self._receipt = receipt

    def fhir_review_transaction(self, bundle: dict[str, Any], patient_id: str) -> dict[str, Any]:
        self.calls += 1
        self.last_bundle = copy.deepcopy(bundle)
        self.last_patient = patient_id
        if self._receipt is not None:
            return copy.deepcopy(self._receipt)
        targets: list[dict[str, Any]] = []
        for entry in bundle.get("entry", []):
            if isinstance(entry, dict) and isinstance(entry.get("resource"), dict):
                res = entry["resource"]
                targets.append(
                    {
                        "response": {
                            "status": "201 Created",
                            "location": str(res.get("resourceType")) + "/" + str(res.get("id")),
                        }
                    }
                )
        return {"resourceType": "Bundle", "type": "transaction-response", "entry": targets}

    def fhir_read(self, resource_type: str, rid: str) -> dict[str, Any] | None:
        _ = (resource_type, rid)
        return None

    def fhir_search(self, resource_type: str, params: dict[str, str]) -> list[dict[str, Any]]:
        _ = (resource_type, params)
        return []

    def tasks_create(self, task: dict[str, Any]) -> dict[str, Any]:
        _ = task
        raise ContractError(code="not_configured", message="tasks are not configured")

    def tasks_write(self, task: dict[str, Any]) -> dict[str, Any]:
        _ = task
        raise ContractError(code="not_configured", message="tasks are not configured")

    def tasks_read(self, task_id: str | None = None) -> list[dict[str, Any]]:
        _ = task_id
        return []

    def tasks_ack(self, task_id: str, user_id: str) -> dict[str, Any]:
        _ = (task_id, user_id)
        raise ContractError(code="not_configured", message="tasks are not configured")

    def vector_search(self, channel: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        _ = (channel, query, limit)
        raise ContractError(code="not_configured", message="vector not configured")


def _policy_auth() -> Any:
    policy = load_matrix()

    async def auth(*, user_id: str, action: str, correlation_id: str) -> bool:
        _ = correlation_id
        return bool(check(policy, user_id, action).allowed)

    return auth


def _chain(store: Any) -> tuple[B4Router, B2Service, Any]:
    auth = _policy_auth()
    service = B2Service(store, auth, mode="mock")

    async def call_b2(request: Envelope) -> Envelope:
        return await service.handle(request)

    router = B4Router(auth, None, call_b2, None, {}, web_sources=frozenset({"web:auth"}))
    return (router, service, store)


def _direct(service: B2Service, user: str, payload: dict[str, Any]) -> Envelope:
    return Envelope(
        request_id="r-1",
        correlation_id="c-1",
        source="b4",
        target="b2",
        action="document.approve",
        data_kind=DataKind.FHIR,
        payload=payload,
        user_id=user,
    )


async def test_chain_clinician_approves_once() -> None:
    store = _FakeReviewStore()
    router, _, _ = _chain(store)
    prepared = _prepared()
    reply = await router.handle(
        web_envelope("clinician", "document.approve", _payload(prepared), DataKind.FHIR)
    )
    assert reply.action == "document.approve"
    assert reply.data_kind == DataKind.FHIR
    assert reply.payload["approvalId"] == APPROVAL
    assert reply.payload["patientRef"] == PATIENT_REF
    assert reply.payload["alreadyApplied"] is False
    assert reply.payload["count"] == 1
    assert (
        reply.payload["stored"]
        == [reply.payload["bundle"]["entry"][0]["response"]["location"].split("/_history")[0]]
        or len(reply.payload["stored"]) == 1
    )
    assert store.calls == 1
    assert store.last_patient == PATIENT_ID


async def test_chain_admin_and_coordinator_approve() -> None:
    for user in ("admin", "coordinator"):
        store = _FakeReviewStore()
        router, _, _ = _chain(store)
        reply = await router.handle(
            web_envelope(user, "document.approve", _payload(_prepared()), DataKind.FHIR)
        )
        assert reply.payload["count"] == 1
        assert store.calls == 1


async def test_chain_viewer_and_assistant_denied() -> None:
    for user in ("viewer", "web-assistant"):
        store = _FakeReviewStore()
        router, _, _ = _chain(store)
        with pytest.raises(AuthError):
            await router.handle(
                web_envelope(user, "document.approve", _payload(_prepared()), DataKind.FHIR)
            )
        assert store.calls == 0


async def test_clinician_plain_fhir_write_still_denied() -> None:
    store = _FakeReviewStore()
    router, _, _ = _chain(store)
    with pytest.raises(AuthError):
        await router.handle(
            web_envelope(
                "clinician",
                "fhir.write",
                {"resourceType": "Observation", "id": "o1"},
                DataKind.FHIR,
            )
        )


async def test_invalid_schema_zero_port_calls() -> None:
    store = _FakeReviewStore()
    _, service, _ = _chain(store)
    with pytest.raises(ContractError):
        await service.handle(_direct(service, "clinician", {"bundle": {}}))
    with pytest.raises(ContractError):
        await service.handle(
            Envelope(
                request_id="r-1",
                correlation_id="c-1",
                source="b4",
                target="b2",
                action="document.approve",
                data_kind=DataKind.METADATA,
                payload=_payload(_prepared()),
                user_id="clinician",
            )
        )
    assert store.calls == 0


async def test_wrong_patient_subject_denied() -> None:
    store = _FakeReviewStore()
    _, service, _ = _chain(store)
    prepared = _prepared()
    payload = _payload(prepared)
    payload["bundle"]["entry"][0]["resource"]["subject"] = {"reference": "Patient/other-case"}
    with pytest.raises(ContractError):
        await service.handle(_direct(service, "clinician", payload))
    assert store.calls == 0


async def test_patient_entry_and_provenance_guard_denied() -> None:
    store = _FakeReviewStore()
    _, service, _ = _chain(store)
    prepared = _prepared()
    payload = _payload(prepared)
    payload["bundle"]["entry"].append(
        {
            "resource": {"resourceType": "Patient", "id": PATIENT_ID},
            "request": {"method": "PUT", "url": PATIENT_REF},
        }
    )
    with pytest.raises(ContractError):
        await service.handle(_direct(service, "clinician", payload))
    payload2 = _payload(prepared)
    payload2["bundle"]["entry"][0]["resource"]["meta"]["tag"] = [
        {"system": "urn:other", "code": "x"}
    ]
    with pytest.raises(ContractError):
        await service.handle(_direct(service, "clinician", payload2))
    assert store.calls == 0


async def test_context_mismatch_and_counts_denied() -> None:
    store = _FakeReviewStore()
    _, service, _ = _chain(store)
    prepared = _prepared()
    bad_source = _payload(prepared)
    bad_source["context"]["sourceUrn"] = "urn:sha256:" + "b" * 64
    with pytest.raises(ContractError):
        await service.handle(_direct(service, "clinician", bad_source))
    bad_hash = _payload(prepared)
    bad_hash["context"]["candidateHash"] = "not-a-hash"
    with pytest.raises(ContractError):
        await service.handle(_direct(service, "clinician", bad_hash))
    bad_counts = _payload(prepared)
    bad_counts["context"]["counts"] = {"Observation": 99}
    with pytest.raises(ContractError):
        await service.handle(_direct(service, "clinician", bad_counts))
    assert store.calls == 0


async def test_valid_port_receipt_counts() -> None:
    store = _FakeReviewStore()
    _, service, _ = _chain(store)
    reply = await service.handle(_direct(service, "clinician", _payload(_prepared())))
    assert reply.payload["count"] == 1
    assert reply.payload["stored"] == ["Observation/" + reply.payload["stored"][0].split("/")[1]]
    assert reply.payload["bundle"]["type"] == "transaction-response"
    assert store.calls == 1


async def test_already_applied_propagates() -> None:
    receipt = {
        "resourceType": "Bundle",
        "type": "transaction-response",
        "entry": [{"response": {"status": "200 OK"}}],
        "alreadyApplied": True,
    }
    prepared = _prepared()
    targets = [
        (str(e["resource"]["resourceType"]), str(e["resource"]["id"]))
        for e in prepared["bundle"]["entry"]
    ]
    receipt["entry"] = [
        {"resource": copy.deepcopy(e["resource"]), "response": {"status": "200 OK"}}
        for e in prepared["bundle"]["entry"]
    ]
    _ = targets
    store = _FakeReviewStore(receipt=receipt)
    _, service, _ = _chain(store)
    reply = await service.handle(_direct(service, "clinician", _payload(prepared)))
    assert reply.payload["alreadyApplied"] is True
    assert store.calls == 1


async def test_missing_port_not_configured() -> None:
    service = B2Service(MemoryStorage(), _policy_auth(), mode="mock")
    with pytest.raises(ContractError) as excinfo:
        await service.handle(_direct(service, "clinician", _payload(_prepared())))
    assert excinfo.value.code == "not_configured"
