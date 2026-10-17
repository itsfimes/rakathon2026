from __future__ import annotations

from typing import Any

from rakathon_backend.b2.ingestion import reserved_import_metadata
from rakathon_backend.common.errors import ContractError
from rakathon_backend.common.fhir import check_resource


def transaction_bundle(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("resourceType") == "Bundle" and payload.get("type") == "transaction":
        return payload
    inner = payload.get("bundle")
    if (
        isinstance(inner, dict)
        and inner.get("resourceType") == "Bundle"
        and inner.get("type") == "transaction"
    ):
        return inner
    return None


def collect_plain_resources(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("resourceType") == "Bundle":
        raise ContractError(code="bad_payload", message="only transaction Bundles may be written")
    if "resourceType" in payload:
        return [payload]
    inner = payload.get("bundle")
    if isinstance(inner, dict):
        if inner.get("resourceType") == "Bundle":
            raise ContractError(
                code="bad_payload", message="only transaction Bundles may be written"
            )
        if "resourceType" in inner:
            return [inner]
    raise ContractError(code="bad_payload", message="fhir.write needs Bundle or resource")


def validate_plain_resource(resource: Any) -> tuple[str, str]:
    if reserved_import_metadata(resource):
        raise ContractError(code="bad_payload", message="Reserved import requires a transaction")
    return check_resource(resource)
