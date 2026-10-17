from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from rakathon_backend.b2.iris.newreview import check_review_bundle, check_transaction_response
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import ContractError
from rakathon_backend.common.fhir import resource_counts
from rakathon_backend.uploads.review_validation import (
    APPROVAL_ID_RE,
    PATIENT_ID_RE,
    PATIENT_REF_RE,
    SOURCE_RE,
    validate_candidate_text,
)

ACTION = "document.approve"
SERVICE_NAME = "b2"
_HASH_RE = re.compile(r"^[a-f0-9]{64}$")
_CONTEXT_KEYS = frozenset(
    {"sourceUrn", "approvalId", "patientRef", "patientId", "candidateHash", "counts"}
)


def _fail(code: str, message: str) -> ContractError:
    return ContractError(code=code, message=message)


def _check_context(context: Any) -> dict[str, Any]:
    if not isinstance(context, dict):
        raise _fail("bad_payload", "approval context must be an object")
    if set(context.keys()) != set(_CONTEXT_KEYS):
        raise _fail("bad_payload", "approval context fields invalid")
    source_urn = context["sourceUrn"]
    approval_id = context["approvalId"]
    patient_ref = context["patientRef"]
    patient_id = context["patientId"]
    candidate_hash = context["candidateHash"]
    counts = context["counts"]
    if not isinstance(source_urn, str) or SOURCE_RE.fullmatch(source_urn) is None:
        raise _fail("bad_payload", "approval source is invalid")
    if not isinstance(approval_id, str) or APPROVAL_ID_RE.fullmatch(approval_id) is None:
        raise _fail("bad_payload", "approval identifier is invalid")
    if not isinstance(patient_id, str) or PATIENT_ID_RE.fullmatch(patient_id) is None:
        raise _fail("bad_payload", "approval patient is invalid")
    if not isinstance(patient_ref, str) or PATIENT_REF_RE.fullmatch(patient_ref) is None:
        raise _fail("bad_payload", "approval patient reference is invalid")
    if patient_ref != "Patient/" + patient_id:
        raise _fail("association_mismatch", "approval patient reference mismatch")
    if not isinstance(candidate_hash, str) or _HASH_RE.fullmatch(candidate_hash) is None:
        raise _fail("bad_payload", "approval hash is invalid")
    if not isinstance(counts, dict) or not counts:
        raise _fail("bad_payload", "approval counts are invalid")
    for key, value in counts.items():
        if not isinstance(key, str) or not key.strip():
            raise _fail("bad_payload", "approval counts are invalid")
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise _fail("bad_payload", "approval counts are invalid")
    return {
        "sourceUrn": source_urn,
        "approvalId": approval_id,
        "patientRef": patient_ref,
        "patientId": patient_id,
        "candidateHash": candidate_hash,
        "counts": dict(counts),
    }


async def handle_document_approve(store: Any, mode: str, request: Envelope) -> Envelope:
    if request.data_kind != DataKind.FHIR:
        raise _fail("misclassified", "document.approve needs fhir kind")
    payload = request.payload
    if set(payload.keys()) != {"bundle", "context"}:
        raise _fail("bad_payload", "approval payload must carry bundle and context")
    bundle = payload["bundle"]
    raw_context = payload["context"]
    if not isinstance(bundle, dict):
        raise _fail("bad_payload", "approval bundle must be an object")
    ctx = _check_context(raw_context)
    patient_id = str(ctx["patientId"])
    patient_ref = str(ctx["patientRef"])
    approval_id = str(ctx["approvalId"])
    guards = check_review_bundle(bundle, patient_id)
    if str(guards["patient_ref"]) != patient_ref:
        raise _fail("association_mismatch", "approval subject points elsewhere")
    if str(guards["source_urn"]) != str(ctx["sourceUrn"]):
        raise _fail("metadata_invalid", "approval source mismatch")
    actual_counts = resource_counts(bundle)
    if dict(actual_counts) != dict(ctx["counts"]):
        raise _fail("bad_payload", "approval counts mismatch")
    validate_candidate_text(json.dumps(bundle, sort_keys=True, separators=(",", ":")), patient_id)
    raw_targets = guards["targets"]
    targets: list[tuple[str, str]] = [(str(a), str(b)) for a, b in raw_targets]
    port = getattr(store, "fhir_review_transaction", None)
    if not callable(port):
        raise _fail("not_configured", "review storage is not configured")
    receipt_raw: dict[str, Any] = await asyncio.to_thread(port, dict(bundle), patient_id)
    receipt = check_transaction_response(receipt_raw, targets)
    stored: list[str] = [rtype + "/" + rid for rtype, rid in targets]
    already = receipt.get("alreadyApplied") is True
    return request.reply(
        source=SERVICE_NAME,
        action=ACTION,
        payload={
            "bundle": dict(receipt),
            "stored": stored,
            "count": len(stored),
            "mode": mode,
            "approvalId": approval_id,
            "patientRef": patient_ref,
            "alreadyApplied": already,
        },
        data_kind=DataKind.FHIR,
    )
