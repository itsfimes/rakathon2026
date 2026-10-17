from __future__ import annotations

import copy
import hashlib
import re
from typing import Any

from jsonschema import Draft202012Validator

from rakathon_backend.b1.schema import ISSUE, TRANSACTION, canonical_schema
from rakathon_backend.common.errors import ContractError
from rakathon_backend.common.fhir import check_bundle, check_resource, resource_counts

TAG_SYSTEM = "urn:rakathon:ingestion-status"
SOURCE = re.compile(r"urn:sha256:[a-f0-9]{64}")
PATIENT_ID = re.compile(r"[A-Za-z0-9.-]{1,64}")
ISSUES = Draft202012Validator({"type": "array", "items": ISSUE, "maxItems": 50})
SUBSET = Draft202012Validator(canonical_schema(TRANSACTION))


def issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "resourceType": None, "detail": detail}


def validate_outcome(result: dict[str, Any]) -> dict[str, Any]:
    if set(result) != {"status", "bundle", "issues"}:
        raise ContractError(code="ai_bad_output", message="Ingestion outcome fields invalid")
    status, bundle, issues = result["status"], result["bundle"], result["issues"]
    if status not in ("complete", "incomplete", "manual-review") or not ISSUES.is_valid(issues):
        raise ContractError(code="ai_bad_output", message="Ingestion outcome invalid")
    if status == "manual-review":
        if bundle is not None or not issues:
            raise ContractError(code="ai_bad_output", message="Manual review must not carry writes")
    else:
        if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
            raise ContractError(code="ai_bad_output", message="Ingestion transaction missing")
        check_bundle(bundle)
        if (status == "complete" and issues) or (status == "incomplete" and not issues):
            raise ContractError(
                code="ai_bad_output", message="Ingestion status conflicts with issues"
            )
    return copy.deepcopy(result)


def prepare_import(result: dict[str, Any], source: str, patient_id: Any) -> dict[str, Any]:
    outcome = validate_outcome(result)
    if outcome["status"] != "manual-review":
        if not SUBSET.is_valid(outcome["bundle"]):
            raise ContractError(
                code="ai_bad_output", message="Translation outside approved FHIR subset"
            )
        if not isinstance(patient_id, str) or PATIENT_ID.fullmatch(patient_id) is None:
            outcome = {
                "status": "manual-review",
                "bundle": None,
                "issues": [
                    issue(
                        "ambiguous-association",
                        "An explicit trusted patient identifier is required",
                    )
                ],
            }
        else:
            bundle = outcome["bundle"]
            entries = bundle["entry"]
            patients = [
                entry["resource"]
                for entry in entries
                if entry["resource"]["resourceType"] == "Patient"
            ]
            if len(patients) != 1 or patients[0]["id"] != patient_id:
                raise ContractError(
                    code="association_mismatch", message="Trusted patient association mismatch"
                )
            for entry in entries:
                resource = entry["resource"]
                if (
                    resource["resourceType"] not in ("Patient", "Provenance")
                    and resource.get("subject", {}).get("reference") != f"Patient/{patient_id}"
                ):
                    raise ContractError(
                        code="association_mismatch", message="Resource patient association mismatch"
                    )
            mapping = {}
            for entry in entries:
                resource = entry["resource"]
                old = f"{resource['resourceType']}/{resource['id']}"
                rid = (
                    patient_id
                    if resource["resourceType"] == "Patient"
                    else "imp-" + hashlib.sha256((source + old).encode()).hexdigest()[:40]
                )
                mapping[old] = f"{resource['resourceType']}/{rid}"
            _rewrite(bundle, mapping)
            for entry in entries:
                resource = entry["resource"]
                mapped = mapping[f"{resource['resourceType']}/{resource['id']}"]
                resource["id"] = mapped.split("/")[1]
                resource["meta"] = {
                    "source": source,
                    "tag": [{"system": TAG_SYSTEM, "code": outcome["status"]}],
                }
                entry["request"] = {"method": "PUT", "url": mapped, "ifNoneMatch": "*"}
            check_bundle(bundle)
    return {
        **outcome,
        "sourceUrn": source,
        "needsReview": outcome["status"] != "complete",
        "manualReview": outcome["status"] != "complete",
        "writeEligible": outcome["status"] != "manual-review",
        "resourceCounts": resource_counts(outcome["bundle"]),
        "patientId": patient_id if isinstance(patient_id, str) else None,
    }


def _rewrite(value: Any, mapping: dict[str, str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "reference":
                if item not in mapping:
                    raise ContractError(
                        code="bad_payload", message="Import references must be closed"
                    )
                value[key] = mapping[item]
            else:
                _rewrite(item, mapping)
    elif isinstance(value, list):
        for item in value:
            _rewrite(item, mapping)


def check_import(bundle: dict[str, Any], context: Any) -> None:
    if not isinstance(context, dict) or set(context) != {
        "status",
        "issues",
        "sourceUrn",
        "patientId",
    }:
        raise ContractError(code="bad_payload", message="Import context invalid")
    source, patient_id = context["sourceUrn"], context["patientId"]
    if not isinstance(source, str) or SOURCE.fullmatch(source) is None:
        raise ContractError(code="bad_payload", message="Import source invalid")
    validate_outcome({"status": context["status"], "bundle": bundle, "issues": context["issues"]})
    patients = 0
    for entry in bundle["entry"]:
        resource = entry["resource"]
        check_resource(resource)
        if (
            resource.get("meta")
            != {"source": source, "tag": [{"system": TAG_SYSTEM, "code": context["status"]}]}
            or entry.get("request", {}).get("ifNoneMatch") != "*"
        ):
            raise ContractError(code="bad_payload", message="Import ownership metadata invalid")
        if resource["resourceType"] == "Patient":
            patients += 1
            if resource["id"] != patient_id:
                raise ContractError(code="bad_payload", message="Import patient mismatch")
        elif (
            resource["resourceType"] != "Provenance"
            and resource.get("subject", {}).get("reference") != f"Patient/{patient_id}"
        ):
            raise ContractError(code="bad_payload", message="Import subject mismatch")
    if patients != 1:
        raise ContractError(
            code="bad_payload", message="Import requires exactly one associated Patient"
        )
    canonical = copy.deepcopy(bundle)
    if "meta" in canonical:
        if canonical["meta"] != {"source": source}:
            raise ContractError(code="bad_payload", message="Import bundle metadata invalid")
        del canonical["meta"]
    for entry in canonical["entry"]:
        del entry["resource"]["meta"]
        del entry["request"]["ifNoneMatch"]
    if not SUBSET.is_valid(canonical):
        raise ContractError(code="bad_payload", message="Import outside approved FHIR subset")
