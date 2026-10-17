from __future__ import annotations

import json
from typing import Any

import httpx

from rakathon_backend.b1.schema import OUTPUT_SCHEMA


def transaction() -> dict[str, Any]:
    items: list[dict[str, Any]] = [
        {"resourceType": "Patient", "id": "synthetic-1", "active": False},
        {
            "resourceType": "Observation",
            "id": "synthetic-observation",
            "status": "final",
            "code": {"text": "Synthetic test"},
            "subject": {"reference": "Patient/synthetic-1"},
            "valueQuantity": {"value": 0, "unit": "test"},
            "effectiveDateTime": "2026-01",
        },
    ]
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "resource": item,
                "request": {"method": "PUT", "url": f"{item['resourceType']}/{item['id']}"},
            }
            for item in items
        ],
    }


def outcome(status: str = "complete") -> dict[str, Any]:
    return {
        "status": status,
        "bundle": None if status == "manual-review" else transaction(),
        "issues": []
        if status == "complete"
        else [
            {"code": "missing-context", "resourceType": None, "detail": "Synthetic omitted context"}
        ],
    }


def provider_fields(value: Any, schema: dict[str, Any] = OUTPUT_SCHEMA) -> Any:
    if "anyOf" in schema:
        if value is None:
            return None
        choices = [choice for choice in schema["anyOf"] if choice.get("type") != "null"]
        if len(choices) > 1:
            choices = [
                choice
                for choice in choices
                if value.get("resourceType")
                in choice.get("properties", {}).get("resourceType", {}).get("enum", [])
            ]
        return provider_fields(value, choices[0])
    if schema.get("type") == "object":
        return {
            **{
                key: provider_fields(value[key], child) if key in value else None
                for key, child in schema["properties"].items()
            },
            **{key: item for key, item in value.items() if key not in schema["properties"]},
        }
    if schema.get("type") == "array":
        return [provider_fields(item, schema["items"]) for item in value]
    return value


def response(content: str, **message: Any) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"finish_reason": "stop", "message": {"content": content, **message}}]},
    )


def provider_response(value: dict[str, Any]) -> httpx.Response:
    return response(json.dumps(provider_fields(value)))
