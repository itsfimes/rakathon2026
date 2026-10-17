from __future__ import annotations

import math
import re
from typing import Any

ID = re.compile(r"[A-Za-z0-9.-]{1,64}")
LOCAL_REFERENCE = re.compile(
    r"(?:Patient|Observation|DiagnosticReport|Practitioner|Organization)/[A-Za-z0-9.-]{1,64}"
)
MAX_ITEMS = 50
MAX_STRING = 4096

CODING: dict[str, Any] = {"system": str, "version": str, "code": str, "display": str}
CONCEPT: dict[str, Any] = {"coding": [CODING], "text": str}
REFERENCE: dict[str, Any] = {"reference": "reference", "display": str}
PERIOD: dict[str, Any] = {"start": str, "end": str}
QUANTITY: dict[str, Any] = {"value": "number", "unit": str, "system": str, "code": str}
NAME: dict[str, Any] = {
    "use": str,
    "text": str,
    "family": str,
    "given": [str],
    "prefix": [str],
    "suffix": [str],
}
CONTACT: dict[str, Any] = {"system": str, "value": str, "use": str}
ADDRESS: dict[str, Any] = {
    "use": str,
    "type": str,
    "text": str,
    "line": [str],
    "city": str,
    "district": str,
    "state": str,
    "postalCode": str,
    "country": str,
}
META: dict[str, Any] = {"versionId": str, "lastUpdated": str, "source": str}
BASE: dict[str, Any] = {"resourceType": str, "id": str, "meta": META}
PATIENT: dict[str, Any] = BASE | {
    "name": [NAME],
    "birthDate": str,
    "gender": str,
    "telecom": [CONTACT],
    "address": [ADDRESS],
    "active": bool,
}
VALUE: dict[str, Any] = {
    "valueQuantity": QUANTITY,
    "valueCodeableConcept": CONCEPT,
    "valueString": str,
    "valueBoolean": bool,
    "valueInteger": "number",
    "valueRange": {"low": QUANTITY, "high": QUANTITY},
    "valueRatio": {"numerator": QUANTITY, "denominator": QUANTITY},
}
RANGE: dict[str, Any] = {
    "low": QUANTITY,
    "high": QUANTITY,
    "type": CONCEPT,
    "text": str,
    "age": {"low": QUANTITY, "high": QUANTITY},
}
OBSERVATION: dict[str, Any] = (
    BASE
    | VALUE
    | {
        "status": str,
        "category": [CONCEPT],
        "code": CONCEPT,
        "subject": REFERENCE,
        "effectiveDateTime": str,
        "effectivePeriod": PERIOD,
        "issued": str,
        "interpretation": [CONCEPT],
        "referenceRange": [RANGE],
        "dataAbsentReason": CONCEPT,
        "component": [
            {"code": CONCEPT, "interpretation": [CONCEPT], "referenceRange": [RANGE]} | VALUE
        ],
    }
)
CONDITION: dict[str, Any] = BASE | {
    "clinicalStatus": CONCEPT,
    "verificationStatus": CONCEPT,
    "category": [CONCEPT],
    "severity": CONCEPT,
    "code": CONCEPT,
    "bodySite": [CONCEPT],
    "subject": REFERENCE,
    "onsetDateTime": str,
    "onsetPeriod": PERIOD,
    "abatementDateTime": str,
    "recordedDate": str,
    "recorder": REFERENCE,
    "asserter": REFERENCE,
    "evidence": [{"code": [CONCEPT], "detail": [REFERENCE]}],
}
REPORT: dict[str, Any] = BASE | {
    "status": str,
    "category": [CONCEPT],
    "code": CONCEPT,
    "subject": REFERENCE,
    "effectiveDateTime": str,
    "effectivePeriod": PERIOD,
    "issued": str,
    "result": [REFERENCE],
    "conclusion": str,
    "conclusionCode": [CONCEPT],
    "presentedForm": [{"contentType": str, "title": str, "creation": str}],
}
DOCUMENT: dict[str, Any] = BASE | {
    "status": str,
    "docStatus": str,
    "type": CONCEPT,
    "category": [CONCEPT],
    "subject": REFERENCE,
    "date": str,
    "description": str,
    "author": [REFERENCE],
    "content": [
        {"attachment": {"contentType": str, "title": str, "creation": str}, "format": CODING}
    ],
    "context": {"period": PERIOD},
}
SCHEMAS = {
    "Patient": PATIENT,
    "Condition": CONDITION,
    "Observation": OBSERVATION,
    "DiagnosticReport": REPORT,
    "DocumentReference": DOCUMENT,
}


class ProjectionError(ValueError):
    pass


def _project(value: Any, schema: Any) -> Any:
    if schema is str:
        if not isinstance(value, str) or len(value) > MAX_STRING:
            raise ProjectionError("invalid string")
        return value
    if schema is bool:
        if not isinstance(value, bool):
            raise ProjectionError("invalid boolean")
        return value
    if schema == "number":
        try:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ProjectionError("invalid number")
        except OverflowError as exc:
            raise ProjectionError("invalid number") from exc
        return value
    if schema == "reference":
        if not isinstance(value, str) or LOCAL_REFERENCE.fullmatch(value) is None:
            raise ProjectionError("invalid reference")
        return value
    if isinstance(schema, list):
        if not isinstance(value, list) or len(value) > MAX_ITEMS:
            raise ProjectionError("invalid array")
        return [_project(item, schema[0]) for item in value]
    if not isinstance(value, dict) or not isinstance(schema, dict):
        raise ProjectionError("invalid object")
    return {key: _project(value[key], sub) for key, sub in schema.items() if key in value}


def project(resource: dict[str, Any], resource_type: str) -> dict[str, Any]:
    rid = resource.get("id")
    if (
        resource.get("resourceType") != resource_type
        or not isinstance(rid, str)
        or ID.fullmatch(rid) is None
    ):
        raise ProjectionError("invalid identity")
    result: dict[str, Any] = _project(resource, SCHEMAS[resource_type])
    return result


def belongs_to(resource: dict[str, Any], patient_id: str) -> bool:
    references = [resource[key] for key in ("subject", "patient") if key in resource]
    return bool(references) and all(
        isinstance(ref, dict) and ref.get("reference") == f"Patient/{patient_id}"
        for ref in references
    )


ACTIVE_CONDITION = (
    "http://terminology.hl7.org/CodeSystem/condition-clinical",
    "active",
)


def _concept_coded(concept: Any, expected: tuple[str, str]) -> bool:
    if not isinstance(concept, dict) or not isinstance(concept.get("coding"), list):
        return False
    return any(
        isinstance(coding, dict)
        and coding.get("system") == expected[0]
        and coding.get("code") == expected[1]
        for coding in concept["coding"]
    )


def _onset_key(condition: dict[str, Any]) -> tuple[str, str]:
    raw = condition.get("onsetDateTime")
    if not isinstance(raw, str):
        period = condition.get("onsetPeriod")
        start = period.get("start") if isinstance(period, dict) else None
        raw = start if isinstance(start, str) else condition.get("recordedDate")
    return (raw if isinstance(raw, str) else "", str(condition.get("id", "")))


def _coded_label(concept: Any) -> dict[str, str] | None:
    if not isinstance(concept, dict):
        return None
    text = concept.get("text")
    for coding in concept.get("coding", []):
        if not isinstance(coding, dict):
            continue
        code = coding.get("code")
        if not isinstance(code, str):
            continue
        display = coding.get("display")
        label = text if isinstance(text, str) and text else display
        return {"code": code, "label": label if isinstance(label, str) and label else code}
    return None


def diagnosis_of(conditions: list[dict[str, Any]]) -> dict[str, str] | None:
    active = [
        item for item in conditions if _concept_coded(item.get("clinicalStatus"), ACTIVE_CONDITION)
    ]
    if not active:
        return None
    chosen = max(active, key=_onset_key)
    return _coded_label(chosen.get("code"))


def patient_summary(resource: dict[str, Any]) -> dict[str, Any]:
    patient = project(resource, "Patient")
    names = patient.get("name", [])
    label = None
    if names:
        name = names[0]
        label = (
            name.get("text")
            or " ".join([*name.get("given", []), name.get("family", "")]).strip()
            or None
        )
    return {"patientId": patient["id"], "label": label, "birthDate": patient.get("birthDate")}
