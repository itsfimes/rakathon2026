from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

from rakathon_backend.b1.outcome import SUBSET
from rakathon_backend.common.errors import ContractError
from rakathon_backend.common.fhir import check_bundle, resource_counts

__all__ = [
    "APPROVAL_ID_RE",
    "MAX_CANDIDATE_BYTES",
    "REVIEW_TAG_CODE",
    "REVIEW_TAG_SYSTEM",
    "prepare_review_import",
    "validate_candidate_text",
]

MAX_CANDIDATE_BYTES = 262144
REVIEW_TAG_SYSTEM = "urn:rakathon:review"
REVIEW_TAG_CODE = "human-approved"
SOURCE_RE = re.compile(r"^urn:sha256:[a-f0-9]{64}$")
PATIENT_ID_RE = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")
PATIENT_REF_RE = re.compile(r"^Patient/[A-Za-z0-9\-.]{1,64}$")
APPROVAL_ID_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,128}$")
_FENCE = "```"


def _fail(code: str, message: str) -> ContractError:
    return ContractError(code=code, message=message)


def _reject_constant(value: str) -> Any:
    raise ValueError("non-finite constant " + value)


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key " + key)
        out[key] = value
    return out


def _selected_ref(patient_id: Any) -> str:
    if not isinstance(patient_id, str) or PATIENT_ID_RE.fullmatch(patient_id) is None:
        raise _fail("bad_patient_id", "selected patient identifier is invalid")
    return "Patient/" + patient_id


def _parse_candidate_text(text: Any) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise _fail("bad_payload", "candidate text is empty")
    if len(text.encode("utf-8")) > MAX_CANDIDATE_BYTES:
        raise _fail("oversize", "candidate text exceeds the size bound")
    if _FENCE in text:
        raise _fail("fenced_output", "candidate text carries markdown fences")
    try:
        parsed: Any = json.loads(
            text, object_pairs_hook=_no_duplicates, parse_constant=_reject_constant
        )
    except json.JSONDecodeError as exc:
        raise _fail("malformed_json", "candidate text is not strict JSON") from exc
    except ValueError as exc:
        if "duplicate key" in str(exc):
            raise _fail("duplicate_key", "candidate text carries duplicate keys") from exc
        raise _fail("non_finite", "candidate text carries non-finite constants") from exc
    if not isinstance(parsed, dict):
        raise _fail("bad_payload", "candidate payload must be a JSON object")
    if parsed.get("resourceType") == "OperationOutcome":
        raise _fail("outcome_rejected", "OperationOutcome is never importable")
    return parsed


def _strip_for_subset(bundle: dict[str, Any]) -> dict[str, Any]:
    canonical: dict[str, Any] = copy.deepcopy(bundle)
    canonical.pop("meta", None)
    entries = canonical.get("entry")
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            resource = entry.get("resource")
            if isinstance(resource, dict):
                resource.pop("meta", None)
            request = entry.get("request")
            if isinstance(request, dict):
                request.pop("ifNoneMatch", None)
    return canonical


def _require_subset(bundle: dict[str, Any]) -> None:
    if not SUBSET.is_valid(_strip_for_subset(bundle)):
        raise _fail("subset_rejected", "candidate carries fields outside the approved subset")


def _patient_entries(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    entries = bundle.get("entry")
    if not isinstance(entries, list):
        return out
    for entry in entries:
        resource = entry.get("resource") if isinstance(entry, dict) else None
        if isinstance(resource, dict) and resource.get("resourceType") == "Patient":
            out.append(resource)
    return out


def _subject_ref(resource: dict[str, Any]) -> str | None:
    subject = resource.get("subject")
    if not isinstance(subject, dict):
        return None
    ref = subject.get("reference")
    return ref if isinstance(ref, str) else None


def _canonical_hash(bundle: dict[str, Any]) -> str:
    raw = json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _validated_candidate(bundle: dict[str, Any], patient_ref: str) -> dict[str, Any]:
    if bundle.get("resourceType") != "Bundle" or bundle.get("type") != "transaction":
        raise _fail("bad_payload", "candidate must be a transaction Bundle")
    entries = bundle.get("entry")
    if not isinstance(entries, list) or not entries:
        raise _fail("empty_bundle", "candidate bundle carries no entries")
    patients = _patient_entries(bundle)
    if len(patients) > 1:
        raise _fail("too_many_patients", "candidate carries more than one Patient")
    alias_ref: str | None = None
    if patients:
        alias_id = patients[0].get("id")
        if not isinstance(alias_id, str) or PATIENT_ID_RE.fullmatch(alias_id) is None:
            raise _fail("bad_payload", "candidate Patient carries an invalid id")
        alias_ref = "Patient/" + alias_id
    for entry in entries:
        resource = entry.get("resource") if isinstance(entry, dict) else None
        if not isinstance(resource, dict):
            raise _fail("bad_payload", "candidate entry resource is invalid")
        rtype = resource.get("resourceType")
        if rtype == "Patient" or rtype == "Provenance":
            continue
        ref = _subject_ref(resource)
        if ref is not None and ref != patient_ref and ref != alias_ref:
            raise _fail("association_mismatch", "candidate subject points at another patient")
    check_bundle(bundle, allowed_external_refs=frozenset({patient_ref}))
    _require_subset(bundle)
    return {
        "alias_ref": alias_ref,
        "candidate_hash": _canonical_hash(bundle),
        "counts": resource_counts(bundle),
    }


def validate_candidate_text(text: str, patient_id: str) -> dict[str, Any]:
    patient_ref = _selected_ref(patient_id)
    bundle = _parse_candidate_text(text)
    checked = _validated_candidate(bundle, patient_ref)
    alias_ref = checked["alias_ref"]
    counts: dict[str, int] = dict(checked["counts"])
    importable = sum(count for rtype, count in counts.items() if rtype != "Patient")
    association = "bound"
    if isinstance(alias_ref, str) and alias_ref != patient_ref:
        association = "associationNeeded"
    entries = bundle.get("entry")
    return {
        "ok": True,
        "candidateHash": checked["candidate_hash"],
        "patientRef": patient_ref,
        "counts": counts,
        "entryCount": len(entries) if isinstance(entries, list) else 0,
        "hasPatientAlias": alias_ref is not None,
        "aliasRef": alias_ref,
        "importableCount": importable,
        "association": association,
    }


def _rewrite(value: Any, mapping: dict[str, str], patient_ref: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "reference" and isinstance(item, str):
                if item == patient_ref:
                    continue
                target = mapping.get(item)
                if target is None:
                    raise _fail("unclosed_reference", "candidate reference is not closed")
                value[key] = target
            else:
                _rewrite(item, mapping, patient_ref)
    elif isinstance(value, list):
        for item in value:
            _rewrite(item, mapping, patient_ref)


def _new_id(approval_id: str, source_urn: str, old_ref: str) -> str:
    seed = approval_id + "\x00" + source_urn + "\x00" + old_ref
    return "imp-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:40]


def prepare_review_import(
    text: str,
    *,
    patient_id: str,
    source_urn: str,
    approval_id: str,
    patient_confirmed: bool,
) -> dict[str, Any]:
    if patient_confirmed is not True:
        raise _fail("confirmation_required", "explicit patient confirmation is required")
    patient_ref = _selected_ref(patient_id)
    if not isinstance(source_urn, str) or SOURCE_RE.fullmatch(source_urn) is None:
        raise _fail("bad_source", "source URN is invalid")
    if not isinstance(approval_id, str) or APPROVAL_ID_RE.fullmatch(approval_id) is None:
        raise _fail("bad_approval_id", "approval identifier is invalid")
    bundle = _parse_candidate_text(text)
    checked = _validated_candidate(bundle, patient_ref)
    mapping: dict[str, str] = {}
    for entry in bundle["entry"]:
        resource = entry["resource"]
        old_ref = str(resource["resourceType"]) + "/" + str(resource["id"])
        if resource.get("resourceType") == "Patient":
            mapping[old_ref] = patient_ref
        else:
            mapped = str(resource["resourceType"]) + "/" + _new_id(approval_id, source_urn, old_ref)
            mapping[old_ref] = mapped
    seen: set[str] = set()
    for target in mapping.values():
        if target != patient_ref:
            if target in seen:
                raise _fail("bad_payload", "deterministic resource identifiers collided")
            seen.add(target)
    outbound_entries: list[dict[str, Any]] = []
    for entry in bundle["entry"]:
        resource = entry["resource"]
        if resource.get("resourceType") == "Patient":
            continue
        old_ref = str(resource["resourceType"]) + "/" + str(resource["id"])
        mapped = mapping[old_ref]
        fresh: dict[str, Any] = copy.deepcopy(resource)
        fresh["id"] = mapped.split("/")[1]
        fresh["meta"] = {
            "source": source_urn,
            "tag": [{"system": REVIEW_TAG_SYSTEM, "code": REVIEW_TAG_CODE}],
        }
        _rewrite(fresh, mapping, patient_ref)
        new_entry: dict[str, Any] = {
            "resource": fresh,
            "request": {"method": "PUT", "url": mapped, "ifNoneMatch": "*"},
        }
        full_url = entry.get("fullUrl")
        if isinstance(full_url, str) and full_url.strip():
            new_entry["fullUrl"] = full_url.strip()
        outbound_entries.append(new_entry)
    if not outbound_entries:
        raise _fail("nothing_to_import", "candidate carries no importable clinical resource")
    outbound: dict[str, Any] = {
        "resourceType": "Bundle",
        "type": "transaction",
        "meta": {"source": source_urn},
        "entry": outbound_entries,
    }
    check_bundle(outbound, allowed_external_refs=frozenset({patient_ref}))
    _require_subset(outbound)
    for entry in outbound_entries:
        if entry["request"].get("ifNoneMatch") != "*":
            raise _fail("metadata_invalid", "outbound ownership metadata is invalid")
        if entry["resource"].get("meta") != {
            "source": source_urn,
            "tag": [{"system": REVIEW_TAG_SYSTEM, "code": REVIEW_TAG_CODE}],
        }:
            raise _fail("metadata_invalid", "outbound ownership metadata is invalid")
    counts: dict[str, int] = resource_counts(outbound)
    context: dict[str, Any] = {
        "sourceUrn": source_urn,
        "approvalId": approval_id,
        "patientRef": patient_ref,
        "patientId": patient_id,
        "candidateHash": checked["candidate_hash"],
        "counts": dict(counts),
    }
    return {
        "bundle": outbound,
        "context": context,
        "counts": counts,
        "candidateHash": checked["candidate_hash"],
        "patientRef": patient_ref,
        "sourceUrn": source_urn,
        "approvalId": approval_id,
    }
