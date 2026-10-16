from __future__ import annotations

from typing import Any

from rakathon_backend.common.fhir import _STATUS_VALUES
from rakathon_backend.common.r4 import ENUMS


def obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def optional(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def array(schema: dict[str, Any], minimum: int = 0) -> dict[str, Any]:
    return {"type": "array", "items": schema, "minItems": minimum, "maxItems": 50}


TEXT = {"type": "string", "minLength": 1, "maxLength": 4096}
ID = {"type": "string", "pattern": "^[A-Za-z0-9.-]{1,64}$"}
REFERENCE = obj(
    {
        "reference": {"type": "string", "pattern": "^[A-Za-z]+/[A-Za-z0-9.-]{1,64}$"},
        "display": optional(TEXT),
    }
)
CODING = obj({"system": optional(TEXT), "code": TEXT, "display": optional(TEXT)})
CONCEPT = obj({"text": optional(TEXT), "coding": optional(array(CODING, 1))})
QUANTITY = obj(
    {
        "value": {"type": "number"},
        "unit": optional(TEXT),
        "system": optional(TEXT),
        "code": optional(TEXT),
    }
)
PERIOD = obj({"start": optional(TEXT), "end": optional(TEXT)})
ATTACHMENT = obj(
    {"contentType": optional(TEXT), "title": optional(TEXT), "creation": optional(TEXT)}
)
NAME = obj({"text": optional(TEXT), "family": optional(TEXT), "given": optional(array(TEXT, 1))})


def resource(kind: str, fields: dict[str, Any]) -> dict[str, Any]:
    return obj({"resourceType": {"type": "string", "enum": [kind]}, "id": ID, **fields})


VALUE = {
    "valueQuantity": optional(QUANTITY),
    "valueString": optional(TEXT),
    "valueBoolean": optional({"type": "boolean"}),
    "valueInteger": optional({"type": "integer"}),
    "valueCodeableConcept": optional(CONCEPT),
}
SCHEMAS = [
    resource(
        "Patient",
        {
            "name": optional(array(NAME, 1)),
            "birthDate": optional(TEXT),
            "gender": optional({"type": "string", "enum": ["male", "female", "other", "unknown"]}),
            "active": optional({"type": "boolean"}),
        },
    ),
    resource(
        "Condition",
        {
            "subject": REFERENCE,
            "code": CONCEPT,
            "clinicalStatus": optional(CONCEPT),
            "verificationStatus": optional(CONCEPT),
            "onsetDateTime": optional(TEXT),
            "recordedDate": optional(TEXT),
            "note": optional(array(obj({"text": TEXT}), 1)),
        },
    ),
    resource(
        "Observation",
        {
            "subject": REFERENCE,
            "status": TEXT,
            "code": CONCEPT,
            "effectiveDateTime": optional(TEXT),
            "issued": optional(TEXT),
            "interpretation": optional(array(CONCEPT, 1)),
            "referenceRange": optional(
                array(
                    obj(
                        {
                            "low": optional(QUANTITY),
                            "high": optional(QUANTITY),
                            "text": optional(TEXT),
                        }
                    ),
                    1,
                )
            ),
            "component": optional(array(obj({"code": CONCEPT, **VALUE}), 1)),
            **VALUE,
        },
    ),
    resource(
        "DiagnosticReport",
        {
            "subject": REFERENCE,
            "status": TEXT,
            "code": CONCEPT,
            "effectiveDateTime": optional(TEXT),
            "issued": optional(TEXT),
            "result": optional(array(REFERENCE, 1)),
            "conclusion": optional(TEXT),
        },
    ),
    resource(
        "DocumentReference",
        {
            "subject": REFERENCE,
            "status": TEXT,
            "docStatus": optional(TEXT),
            "type": optional(CONCEPT),
            "date": optional(TEXT),
            "description": optional(TEXT),
            "content": array(obj({"attachment": ATTACHMENT}), 1),
        },
    ),
    resource(
        "ServiceRequest",
        {
            "subject": REFERENCE,
            "status": TEXT,
            "intent": TEXT,
            "code": optional(CONCEPT),
            "authoredOn": optional(TEXT),
            "occurrenceDateTime": optional(TEXT),
            "note": optional(array(obj({"text": TEXT}), 1)),
        },
    ),
    resource(
        "Procedure",
        {
            "subject": REFERENCE,
            "status": TEXT,
            "code": optional(CONCEPT),
            "performedDateTime": optional(TEXT),
            "note": optional(array(obj({"text": TEXT}), 1)),
        },
    ),
    resource(
        "Provenance",
        {
            "target": array(REFERENCE, 1),
            "recorded": TEXT,
            "agent": array(obj({"who": REFERENCE}), 1),
        },
    ),
]
for _schema in SCHEMAS:
    _kind = _schema["properties"]["resourceType"]["enum"][0]
    if _kind in _STATUS_VALUES:
        _schema["properties"]["status"] = {"type": "string", "enum": sorted(_STATUS_VALUES[_kind])}
    if _kind == "ServiceRequest":
        _schema["properties"]["intent"] = {"type": "string", "enum": sorted(ENUMS[_kind]["intent"])}
ISSUE = obj(
    {
        "code": {
            "type": "string",
            "enum": [
                "missing-context",
                "missing-required-fact",
                "unsupported-content",
                "ambiguous-association",
                "excluded-fragment",
            ],
        },
        "resourceType": optional(
            {
                "type": "string",
                "enum": [schema["properties"]["resourceType"]["enum"][0] for schema in SCHEMAS],
            }
        ),
        "detail": TEXT,
    }
)
TRANSACTION = obj(
    {
        "resourceType": {"type": "string", "enum": ["Bundle"]},
        "type": {"type": "string", "enum": ["transaction"]},
        "entry": array(
            obj(
                {
                    "resource": {"anyOf": SCHEMAS},
                    "request": obj({"method": {"type": "string", "enum": ["PUT"]}, "url": TEXT}),
                }
            ),
            1,
        ),
    }
)
OUTPUT_SCHEMA = obj(
    {
        "status": {"type": "string", "enum": ["complete", "incomplete", "manual-review"]},
        "bundle": optional(TRANSACTION),
        "issues": array(ISSUE),
    }
)


def canonical_schema(schema: dict[str, Any]) -> dict[str, Any]:
    if "anyOf" in schema:
        choices = [item for item in schema["anyOf"] if item.get("type") != "null"]
        if len(choices) == 1:
            return canonical_schema(choices[0])
        return {"anyOf": [canonical_schema(item) for item in choices]}
    result = dict(schema)
    if schema.get("type") == "object":
        result["properties"] = {
            key: canonical_schema(child) for key, child in schema["properties"].items()
        }
        result["required"] = [
            key
            for key, child in schema["properties"].items()
            if not any(item.get("type") == "null" for item in child.get("anyOf", []))
        ]
    if schema.get("type") == "array":
        result["items"] = canonical_schema(schema["items"])
    return result


def omit_optional_nulls(value: Any, schema: dict[str, Any]) -> Any:
    alternatives = schema.get("anyOf")
    if alternatives:
        if value is None:
            return None
        if isinstance(value, dict) and "resourceType" in value:
            for alternative in alternatives:
                discriminator = (
                    alternative.get("properties", {}).get("resourceType", {}).get("enum", [])
                )
                if value["resourceType"] in discriminator:
                    return omit_optional_nulls(value, alternative)
        return omit_optional_nulls(value, alternatives[0])
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            child = schema["properties"][key]
            nullable = any(choice.get("type") == "null" for choice in child.get("anyOf", []))
            if item is None and nullable:
                continue
            result[key] = omit_optional_nulls(item, child)
        return result
    if isinstance(value, list):
        return [omit_optional_nulls(item, schema["items"]) for item in value]
    return value
