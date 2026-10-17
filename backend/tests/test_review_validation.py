from __future__ import annotations

import json
from typing import Any

import pytest

from rakathon_backend.common.errors import ContractError
from rakathon_backend.common.fhir import check_bundle
from rakathon_backend.uploads.review_validation import (
    MAX_CANDIDATE_BYTES,
    REVIEW_TAG_CODE,
    REVIEW_TAG_SYSTEM,
    prepare_review_import,
    validate_candidate_text,
)

PATIENT_ID = "target-1"
PATIENT_REF = "Patient/target-1"
SOURCE = "urn:sha256:" + "a" * 64
APPROVAL = "approval-1"
ALIAS = "model-p9"


def _patient(alias: str) -> dict[str, Any]:
    return {"resourceType": "Patient", "id": alias, "name": [{"text": "Zebra"}]}


def _observation(rid: str, subject: str) -> dict[str, Any]:
    return {
        "resourceType": "Observation",
        "id": rid,
        "status": "final",
        "code": {"text": "GLUCOSE"},
        "subject": {"reference": subject},
    }


def _request(resource: dict[str, Any]) -> dict[str, Any]:
    rtype = str(resource["resourceType"])
    return {
        "resource": resource,
        "request": {"method": "PUT", "url": rtype + "/" + str(resource["id"])},
    }


def _text(bundle: dict[str, Any]) -> str:
    return json.dumps(bundle)


def _aliased_bundle() -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [_request(_patient(ALIAS)), _request(_observation("o1", "Patient/" + ALIAS))],
    }


def test_alias_binding_drops_patient_and_rewrites_subject() -> None:
    seen = validate_candidate_text(_text(_aliased_bundle()), PATIENT_ID)
    assert seen["association"] == "associationNeeded"
    assert seen["aliasRef"] == "Patient/" + ALIAS
    assert seen["importableCount"] == 1
    prepared = prepare_review_import(
        _text(_aliased_bundle()),
        patient_id=PATIENT_ID,
        source_urn=SOURCE,
        approval_id=APPROVAL,
        patient_confirmed=True,
    )
    bundle = prepared["bundle"]
    assert prepared["candidateHash"] == seen["candidateHash"]
    assert prepared["patientRef"] == PATIENT_REF
    assert prepared["context"]["candidateHash"] == seen["candidateHash"]
    assert prepared["context"]["approvalId"] == APPROVAL
    assert prepared["counts"] == {"Observation": 1}
    assert len(bundle["entry"]) == 1
    resource = bundle["entry"][0]["resource"]
    assert resource["resourceType"] == "Observation"
    assert resource["subject"] == {"reference": PATIENT_REF}
    assert resource["id"].startswith("imp-")
    assert len(resource["id"]) <= 64
    request = bundle["entry"][0]["request"]
    assert request == {"method": "PUT", "url": "Observation/" + resource["id"], "ifNoneMatch": "*"}
    assert resource["meta"] == {
        "source": SOURCE,
        "tag": [{"system": REVIEW_TAG_SYSTEM, "code": REVIEW_TAG_CODE}],
    }


def test_omitted_patient_with_selected_subject_is_bound() -> None:
    bundle = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [_request(_observation("o1", PATIENT_REF))],
    }
    seen = validate_candidate_text(_text(bundle), PATIENT_ID)
    assert seen["association"] == "bound"
    assert seen["hasPatientAlias"] is False
    prepared = prepare_review_import(
        _text(bundle),
        patient_id=PATIENT_ID,
        source_urn=SOURCE,
        approval_id=APPROVAL,
        patient_confirmed=True,
    )
    assert prepared["bundle"]["entry"][0]["resource"]["subject"] == {"reference": PATIENT_REF}


def test_explicit_confirmation_is_required() -> None:
    with pytest.raises(ContractError):
        prepare_review_import(
            _text(_aliased_bundle()),
            patient_id=PATIENT_ID,
            source_urn=SOURCE,
            approval_id=APPROVAL,
            patient_confirmed=False,
        )


def test_rejects_non_fhir_and_operation_outcome() -> None:
    with pytest.raises(ContractError):
        validate_candidate_text("hello, not json", PATIENT_ID)
    with pytest.raises(ContractError):
        validate_candidate_text(json.dumps({"resourceType": "Patient", "id": "x"}), PATIENT_ID)
    outcome = {"resourceType": "OperationOutcome", "issue": [{"severity": "error", "code": "x"}]}
    with pytest.raises(ContractError):
        validate_candidate_text(json.dumps(outcome), PATIENT_ID)


def test_rejects_delete_method_and_unsupported_fields() -> None:
    resource = _observation("o1", PATIENT_REF)
    bad = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [{"resource": resource, "request": {"method": "DELETE", "url": "Observation/o1"}}],
    }
    with pytest.raises(ContractError):
        validate_candidate_text(json.dumps(bad), PATIENT_ID)
    extra = _observation("o1", PATIENT_REF)
    extra["bogusField"] = "oops"
    wrapped = {"resourceType": "Bundle", "type": "transaction", "entry": [_request(extra)]}
    with pytest.raises(ContractError):
        validate_candidate_text(json.dumps(wrapped), PATIENT_ID)


def test_rejects_dangling_and_external_references() -> None:
    report = {
        "resourceType": "DiagnosticReport",
        "id": "r1",
        "status": "final",
        "code": {"text": "PANEL"},
        "subject": {"reference": PATIENT_REF},
        "result": [{"reference": "Observation/missing"}],
    }
    dangling = {"resourceType": "Bundle", "type": "transaction", "entry": [_request(report)]}
    with pytest.raises(ContractError):
        validate_candidate_text(json.dumps(dangling), PATIENT_ID)
    foreign = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [_request(_observation("o1", "Patient/other-case"))],
    }
    with pytest.raises(ContractError):
        validate_candidate_text(json.dumps(foreign), PATIENT_ID)


def test_rejects_subject_mismatch_and_multiple_patients() -> None:
    bundle = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [_request(_patient(ALIAS)), _request(_observation("o1", "Patient/other-case"))],
    }
    with pytest.raises(ContractError):
        validate_candidate_text(json.dumps(bundle), PATIENT_ID)
    two = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            _request(_patient("a1")),
            _request(_patient("a2")),
            _request(_observation("o1", PATIENT_REF)),
        ],
    }
    with pytest.raises(ContractError):
        validate_candidate_text(json.dumps(two), PATIENT_ID)


def test_patient_only_candidate_rejected_at_approval() -> None:
    lone = {"resourceType": "Bundle", "type": "transaction", "entry": [_request(_patient(ALIAS))]}
    seen = validate_candidate_text(json.dumps(lone), PATIENT_ID)
    assert seen["importableCount"] == 0
    with pytest.raises(ContractError):
        prepare_review_import(
            json.dumps(lone),
            patient_id=PATIENT_ID,
            source_urn=SOURCE,
            approval_id=APPROVAL,
            patient_confirmed=True,
        )


def test_deterministic_ids_stable_across_retries() -> None:
    first = prepare_review_import(
        _text(_aliased_bundle()),
        patient_id=PATIENT_ID,
        source_urn=SOURCE,
        approval_id=APPROVAL,
        patient_confirmed=True,
    )
    second = prepare_review_import(
        _text(_aliased_bundle()),
        patient_id=PATIENT_ID,
        source_urn=SOURCE,
        approval_id=APPROVAL,
        patient_confirmed=True,
    )
    assert first["bundle"] == second["bundle"]
    other = prepare_review_import(
        _text(_aliased_bundle()),
        patient_id=PATIENT_ID,
        source_urn=SOURCE,
        approval_id="approval-2",
        patient_confirmed=True,
    )
    mine = first["bundle"]["entry"][0]["resource"]["id"]
    theirs = other["bundle"]["entry"][0]["resource"]["id"]
    assert mine != theirs


def test_wrapper_metadata_is_overwritten_by_server() -> None:
    patient = _patient(ALIAS)
    patient["meta"] = {"source": "https://example.org/wrapper"}
    obs = _observation("o1", "Patient/" + ALIAS)
    obs["meta"] = {"source": "https://example.org/wrapper"}
    bundle = {
        "resourceType": "Bundle",
        "type": "transaction",
        "meta": {"source": "https://example.org/wrapper"},
        "entry": [_request(patient), _request(obs)],
    }
    prepared = prepare_review_import(
        json.dumps(bundle),
        patient_id=PATIENT_ID,
        source_urn=SOURCE,
        approval_id=APPROVAL,
        patient_confirmed=True,
    )
    outbound = prepared["bundle"]
    assert outbound["meta"] == {"source": SOURCE}
    assert outbound["entry"][0]["resource"]["meta"]["source"] == SOURCE


def test_strict_json_gates() -> None:
    with pytest.raises(ContractError):
        validate_candidate_text("```json\n{}\n```", PATIENT_ID)
    with pytest.raises(ContractError):
        validate_candidate_text('{"a": 1, "a": 2}', PATIENT_ID)
    with pytest.raises(ContractError):
        validate_candidate_text('{"a": NaN}', PATIENT_ID)
    with pytest.raises(ContractError):
        validate_candidate_text("x" * (MAX_CANDIDATE_BYTES + 1), PATIENT_ID)


def test_common_bundle_default_guard_unchanged() -> None:
    bundle: dict[str, Any] = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [_request(_patient("p1"))],
    }
    bundle["entry"].append(_request(_observation("o1", "Patient/p1")))
    check_bundle(bundle)
    loose = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [_request(_observation("o1", PATIENT_REF))],
    }
    with pytest.raises(ContractError):
        check_bundle(loose)
    check_bundle(loose, allowed_external_refs=frozenset({PATIENT_REF}))
    with pytest.raises(ContractError):
        check_bundle(loose, allowed_external_refs=frozenset({"https://example.org/Patient/x"}))
    frag = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [_request(_observation("o1", "#frag"))],
    }
    with pytest.raises(ContractError):
        check_bundle(frag, allowed_external_refs=frozenset({"#frag"}))
