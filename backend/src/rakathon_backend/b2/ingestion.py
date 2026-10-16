from __future__ import annotations

import copy
from typing import Any

from rakathon_backend.b1.outcome import TAG_SYSTEM, check_import
from rakathon_backend.b2.ports import Storage
from rakathon_backend.common.errors import ContractError, TransportError


def reserved_import_metadata(value: Any) -> bool:
    if isinstance(value, dict):
        meta = value.get("meta")
        if isinstance(meta, dict):
            tags = meta.get("tag", [])
            if isinstance(tags, list) and any(
                isinstance(tag, dict) and tag.get("system") == TAG_SYSTEM for tag in tags
            ):
                return True
            source = meta.get("source")
            if (
                value.get("resourceType") != "Bundle"
                and isinstance(source, str)
                and source.startswith("urn:sha256:")
            ):
                return True
        return any(reserved_import_metadata(item) for item in value.values())
    if isinstance(value, list):
        return any(reserved_import_metadata(item) for item in value)
    return False


def import_context_present(bundle: dict[str, Any], payload: dict[str, Any]) -> bool:
    present = "ingestion" in payload
    if reserved_import_metadata(bundle) and not present:
        raise ContractError(code="bad_payload", message="Reserved import metadata requires context")
    return present


def persist_import(
    store: Storage, bundle: dict[str, Any], context: Any, mode: str = "mock"
) -> dict[str, Any]:
    if mode != "mock":
        raise ContractError(code="not_configured", message="Live imports are disabled")
    bundle, context = copy.deepcopy(bundle), copy.deepcopy(context)
    check_import(bundle, context)
    for entry in bundle["entry"]:
        resource = entry["resource"]
        if store.fhir_read(resource["resourceType"], resource["id"]) is not None:
            raise ContractError(
                code="import_conflict", message="Import cannot overwrite existing records"
            )
    response = store.fhir_transaction(bundle)
    entries = response.get("entry")
    if not isinstance(entries, list) or len(entries) != len(bundle["entry"]):
        raise TransportError(code="write_failed", message="Transaction result incomplete")
    for entry in entries:
        status = entry.get("response", {}).get("status") if isinstance(entry, dict) else None
        if not isinstance(status, str) or status[:3] not in ("200", "201", "204"):
            raise TransportError(
                code="write_failed", message="Transaction did not confirm persistence"
            )
    return response
