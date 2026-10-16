from __future__ import annotations

from typing import Any

from rakathon_backend.common.fhir import (
    attach_source,
    check_bundle,
    is_manual_review,
    resource_counts,
    validate_bundle,
)

__all__ = [
    "attach_source",
    "check_bundle",
    "is_manual_review",
    "resource_counts",
    "translate_fixture",
    "validate_bundle",
]


def translate_fixture(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    patient = data.get("patient")
    reason = data.get("referralReason")
    if not isinstance(patient, dict):
        return ("manual_review", _outcome("INCOMPLETE", "patient block is missing"))
    pid = patient.get("id")
    name = patient.get("name")
    if not isinstance(pid, str) or not pid.strip():
        return ("manual_review", _outcome("INCOMPLETE", "patient.id is missing"))
    if not isinstance(name, str) or not name.strip():
        return ("manual_review", _outcome("INCOMPLETE", "patient.name is missing"))
    if not isinstance(reason, str) or not reason.strip():
        return ("manual_review", _outcome("INCOMPLETE", "referralReason is missing"))
    clean_id = pid.strip()
    bundle: dict[str, Any] = {
        "resourceType": "Bundle",
        "type": "transaction",
        "meta": {"tag": [{"system": "http://example.org/synthetic", "code": "SYNTHETIC"}]},
        "entry": [
            {
                "fullUrl": f"urn:uuid:patient-{clean_id}",
                "resource": {
                    "resourceType": "Patient",
                    "id": clean_id,
                    "name": [{"text": name.strip()}],
                    "meta": {"tag": [{"code": "SYNTHETIC"}]},
                },
                "request": {"method": "PUT", "url": f"Patient/{clean_id}"},
            },
            {
                "fullUrl": f"urn:uuid:sr-{clean_id}",
                "resource": {
                    "resourceType": "ServiceRequest",
                    "id": f"sr-{clean_id}",
                    "status": "active",
                    "intent": "order",
                    "subject": {"reference": f"Patient/{clean_id}"},
                    "reasonCode": [{"text": reason.strip()}],
                },
                "request": {"method": "PUT", "url": f"ServiceRequest/sr-{clean_id}"},
            },
        ],
    }
    return ("fhir", bundle)


def _outcome(code: str, detail: str) -> dict[str, Any]:
    return {
        "resourceType": "OperationOutcome",
        "issue": [
            {
                "severity": "information",
                "code": "incomplete",
                "details": {"text": f"{code}: {detail}. Manual review required. No data invented."},
            }
        ],
    }
