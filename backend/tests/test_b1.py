from __future__ import annotations

import json
from typing import Any

import pytest

from rakathon_backend.b1.service import B1Service
from rakathon_backend.b1.translation import translate_fixture, validate_bundle
from rakathon_backend.common.blob_store import BlobStore
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import AuthError, ContractError


def _req(ref: str, user: str = "coordinator", source: str = "b4") -> Envelope:
    return Envelope(
        request_id="r-1",
        correlation_id="c-1",
        source=source,
        target="b1",
        action="ingest",
        data_kind=DataKind.PROPRIETARY,
        payload={"bytesRef": ref, "purpose": "translate"},
        user_id=user,
    )


async def _ok_auth(*, user_id: str, action: str, correlation_id: str) -> bool:
    _ = (user_id, action, correlation_id)
    return True


async def _deny_auth(*, user_id: str, action: str, correlation_id: str) -> bool:
    _ = (user_id, action, correlation_id)
    return False


def test_translate_complete_bundle() -> None:
    kind, bundle = translate_fixture(
        {"patient": {"id": "p1", "name": "Jane"}, "referralReason": "check"}
    )
    assert kind == "fhir"
    assert validate_bundle(bundle) is True
    assert bundle["resourceType"] == "Bundle"


def test_translate_incomplete_no_invention() -> None:
    kind, bundle = translate_fixture({"patient": {"id": "", "name": ""}, "referralReason": ""})
    assert kind == "manual_review"
    assert bundle["resourceType"] == "OperationOutcome"
    assert validate_bundle(bundle) is True


async def test_b1_complete_end_to_end() -> None:
    blob = BlobStore()
    ref = blob.put(
        json.dumps({"patient": {"id": "p9", "name": "Ann"}, "referralReason": "r"}).encode(),
        "application/json",
    )

    async def via_b5(
        *, bytes_ref: str, purpose: str, user_id: str, correlation_id: str
    ) -> dict[str, Any]:
        _ = (purpose, user_id, correlation_id)
        record = blob.get(bytes_ref)
        parsed = json.loads(record.data.decode())
        _kind, bundle = translate_fixture(parsed)
        return {"bundle": bundle}

    service = B1Service(blob, via_b5, _ok_auth)
    reply = await service.handle(_req(ref))
    assert reply.payload["mode"] == "mock"
    assert reply.payload["bundle"]["resourceType"] == "Bundle"
    assert reply.data_kind == DataKind.FHIR


async def test_b1_incomplete_returns_outcome() -> None:
    blob = BlobStore()
    ref = blob.put(json.dumps({"patient": {}, "referralReason": ""}).encode(), "application/json")

    async def via_b5(
        *, bytes_ref: str, purpose: str, user_id: str, correlation_id: str
    ) -> dict[str, Any]:
        _ = (purpose, user_id, correlation_id)
        record = blob.get(bytes_ref)
        parsed = json.loads(record.data.decode())
        _kind, bundle = translate_fixture(parsed)
        return {"bundle": bundle}

    service = B1Service(blob, via_b5, _ok_auth)
    reply = await service.handle(_req(ref))
    assert reply.payload["bundle"]["resourceType"] == "OperationOutcome"


async def test_b1_rejects_raw_blob_inline() -> None:
    blob = BlobStore()
    ref = blob.put(b'{"x": 1}', "application/json")
    service = B1Service(blob, None, _ok_auth)
    bad = Envelope(
        request_id="r-1",
        correlation_id="c-1",
        source="b4",
        target="b1",
        action="ingest",
        data_kind=DataKind.PROPRIETARY,
        payload={"bytesRef": ref, "blob": "raw"},
        user_id="coordinator",
    )
    with pytest.raises(ContractError):
        await service.handle(bad)


async def test_b1_rejects_bad_caller_and_denied_auth() -> None:
    blob = BlobStore()
    ref = blob.put(b'{"x": 1}', "application/json")
    service = B1Service(blob, None, _ok_auth)
    with pytest.raises(AuthError):
        await service.handle(_req(ref, source="b9"))
    denied = B1Service(blob, None, _deny_auth)
    with pytest.raises(AuthError):
        await denied.handle(_req(ref))
