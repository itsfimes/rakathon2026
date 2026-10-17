from __future__ import annotations

from typing import Any

import pytest
from docx_samples import MARKER, make_docx

from rakathon_backend.b1.service import B1Service
from rakathon_backend.b1.translation import translate_fixture
from rakathon_backend.common.blob_store import DOCX_MIME, BlobStore
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import AuthError, ContractError
from rakathon_backend.common.fhir import resource_counts, validate_bundle


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


def _bundle_entry(rtype: str, rid: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    resource: dict[str, Any] = {"resourceType": rtype, "id": rid}
    if extra:
        resource.update(extra)
    entry: dict[str, Any] = {
        "fullUrl": f"urn:uuid:{rtype.lower()}-{rid}",
        "resource": resource,
        "request": {"method": "PUT", "url": f"{rtype}/{rid}"},
    }
    return entry


async def test_docx_route_sends_only_derived_ref() -> None:
    blob = BlobStore()
    raw = make_docx([("p", f"visit note {MARKER}"), ("t", [["h", "v"]])])
    original = blob.put(raw, DOCX_MIME)
    seen: dict[str, str] = {}

    async def via_b5(
        *, bytes_ref: str, purpose: str, user_id: str, correlation_id: str
    ) -> dict[str, Any]:
        seen["ref"] = bytes_ref
        _ = (purpose, user_id, correlation_id)
        record = blob.get(bytes_ref)
        assert record.content_type == "text/plain"
        assert MARKER.encode() in record.data
        entry = _bundle_entry(
            "DocumentReference",
            "doc-1",
            {"status": "current", "content": [{"attachment": {"title": "Synthetic source"}}]},
        )
        return {"bundle": {"resourceType": "Bundle", "type": "transaction", "entry": [entry]}}

    service = B1Service(blob, via_b5, _ok_auth)
    reply = await service.handle(_req(original))
    assert seen["ref"] != original
    assert reply.payload["sourceRef"] == original
    assert len(reply.payload["sourceHash"]) == 64
    assert reply.payload["sourceUrn"] == f"urn:sha256:{reply.payload['sourceHash']}"
    assert reply.payload["bundle"]["meta"]["source"] == reply.payload["sourceUrn"]
    assert reply.payload["resourceCounts"] == {"DocumentReference": 1}
    assert reply.payload["manualReview"] is False
    assert len(blob) == 1


async def test_docx_outcome_manual_review_propagates() -> None:
    blob = BlobStore()
    original = blob.put(make_docx([("p", "admin form")]), DOCX_MIME)

    async def via_b5(
        *, bytes_ref: str, purpose: str, user_id: str, correlation_id: str
    ) -> dict[str, Any]:
        _ = (bytes_ref, purpose, user_id, correlation_id)
        return {
            "bundle": {
                "resourceType": "OperationOutcome",
                "issue": [{"severity": "information", "code": "incomplete"}],
            }
        }

    service = B1Service(blob, via_b5, _ok_auth)
    reply = await service.handle(_req(original))
    assert reply.payload["manualReview"] is True
    assert reply.payload["resourceCounts"] == {"OperationOutcome": 1}


async def test_docx_denied_auth_invokes_no_inference() -> None:
    blob = BlobStore()
    original = blob.put(make_docx([("p", "note")]), DOCX_MIME)
    calls: list[str] = []

    async def via_b5(
        *, bytes_ref: str, purpose: str, user_id: str, correlation_id: str
    ) -> dict[str, Any]:
        calls.append(bytes_ref)
        raise AssertionError("must not translate")

    service = B1Service(blob, via_b5, _deny_auth)
    with pytest.raises(AuthError):
        await service.handle(_req(original))
    assert calls == []


async def test_docx_malicious_archive_maps_to_safe_error() -> None:
    blob = BlobStore()
    original = blob.put(b"not a zip at all", DOCX_MIME)
    service = B1Service(blob, None, _ok_auth)
    with pytest.raises(ContractError) as caught:
        await service.handle(_req(original))
    assert caught.value.code == "docx_invalid"
    assert MARKER not in str(caught.value)


def test_document_reference_only_bundle_is_valid() -> None:
    entry = _bundle_entry(
        "DocumentReference",
        "doc-9",
        {"status": "current", "content": [{"attachment": {"title": "Synthetic source"}}]},
    )
    bundle = {"resourceType": "Bundle", "type": "transaction", "entry": [entry]}
    assert validate_bundle(bundle) is True
    assert resource_counts(bundle) == {"DocumentReference": 1}


def test_expanded_clinical_types_are_valid() -> None:
    entries = [
        _bundle_entry("Patient", "p1"),
        _bundle_entry(
            "Observation",
            "o1",
            {
                "status": "final",
                "code": {"text": "Synthetic observation"},
                "subject": {"reference": "Patient/p1"},
            },
        ),
        _bundle_entry(
            "Condition",
            "c1",
            {"code": {"text": "Synthetic condition"}, "subject": {"reference": "Patient/p1"}},
        ),
        _bundle_entry(
            "Procedure",
            "pr1",
            {"status": "completed", "subject": {"reference": "Patient/p1"}},
        ),
    ]
    assert validate_bundle({"resourceType": "Bundle", "type": "transaction", "entry": entries})


def test_patient_name_is_optional_but_fixture_stays_strict() -> None:
    entry = _bundle_entry("Patient", "p2")
    assert validate_bundle({"resourceType": "Bundle", "type": "transaction", "entry": [entry]})
    kind, bundle = translate_fixture({"patient": {"id": "p2", "name": ""}, "referralReason": "x"})
    assert kind == "manual_review"
    assert bundle["resourceType"] == "OperationOutcome"


@pytest.mark.parametrize(
    "mutate",
    ["method_mismatch", "bad_status", "open_ref", "dup_id", "exec_url", "missing_field"],
)
def test_invalid_bundles_are_rejected(mutate: str) -> None:
    entries = [
        _bundle_entry("Patient", "p1"),
        _bundle_entry(
            "ServiceRequest",
            "sr-1",
            {
                "status": "active",
                "intent": "order",
                "subject": {"reference": "Patient/p1"},
            },
        ),
    ]
    if mutate == "method_mismatch":
        entries[1]["request"] = {"method": "PUT", "url": "ServiceRequest/other"}
    elif mutate == "bad_status":
        entries[1]["resource"]["status"] = "cured"
    elif mutate == "open_ref":
        entries[1]["resource"]["subject"] = {"reference": "Patient/ghost"}
    elif mutate == "dup_id":
        entries.append(_bundle_entry("Patient", "p1"))
    elif mutate == "exec_url":
        entries[1]["resource"]["note"] = "javascript:alert(1)"
    elif mutate == "missing_field":
        del entries[1]["resource"]["subject"]
    assert (
        validate_bundle({"resourceType": "Bundle", "type": "transaction", "entry": entries})
        is False
    )


def test_oversized_transaction_is_rejected() -> None:
    entries = [
        _bundle_entry("Observation", f"o{n}", {"status": "final", "code": {}}) for n in range(101)
    ]
    assert (
        validate_bundle({"resourceType": "Bundle", "type": "transaction", "entry": entries})
        is False
    )
