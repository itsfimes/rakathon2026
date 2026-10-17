from __future__ import annotations

import asyncio
import base64
import binascii
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from threading import Event
from typing import Any

from rakathon_backend.common.collection import failure_metadata
from rakathon_backend.common.errors import AuthError, ContractError, TransportError
from rakathon_backend.common.fhir import PATIENT_CONTEXT_TYPES
from rakathon_backend.uploads.store import UploadStore
from rakathon_backend.web.context_budget import ByteBudget, context_too_large
from rakathon_backend.web.contracts import WebError
from rakathon_backend.web.patient_uploads import collect_uploads
from rakathon_backend.web.projection import ID

Read = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
MAX_ATTACHMENT_BYTES = 900_000
COLLECTION_DEADLINE = 20
COLLECTION_CONCURRENCY = 5


def _resources(payload: dict[str, Any]) -> list[dict[str, Any]]:
    bundle = payload.get("bundle")
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        raise WebError(503, "unavailable", "Patient context unavailable")
    if any(link.get("relation") == "next" for link in bundle.get("link", [])):
        # B2's FHIR adapter must finish its protected pagination before replying.
        raise WebError(503, "unavailable", "Patient context pagination incomplete")
    entries = bundle.get("entry", [])
    if not isinstance(entries, list) or any(
        not isinstance(entry, dict) or not isinstance(entry.get("resource"), dict)
        for entry in entries
    ):
        raise WebError(503, "unavailable", "Patient context unavailable")
    return [entry["resource"] for entry in entries]


def _check_resource(resource: dict[str, Any], kind: str, case_id: str) -> None:
    rid = resource.get("id")
    if resource.get("resourceType") != kind or not isinstance(rid, str) or not ID.fullmatch(rid):
        raise WebError(503, "unavailable", "Patient context identity mismatch")
    refs = [resource[key] for key in ("subject", "patient") if key in resource]
    if kind == "Patient":
        valid = rid == case_id
    else:
        valid = bool(refs) and all(
            isinstance(ref, dict) and ref.get("reference") == f"Patient/{case_id}" for ref in refs
        )
    if not valid:
        raise WebError(503, "unavailable", "Patient context association mismatch")


def document_texts(resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for resource in resources:
        kind = resource["resourceType"]
        attachments = (
            [content.get("attachment", {}) for content in resource.get("content", [])]
            if kind == "DocumentReference"
            else resource.get("presentedForm", [])
            if kind == "DiagnosticReport"
            else []
        )
        for index, attachment in enumerate(attachments):
            item: dict[str, Any] = {"source": f"{kind}/{resource['id']}", "attachment": index}
            content_type = str(attachment.get("contentType", "")).split(";", 1)[0].lower()
            data = attachment.get("data")
            if not (content_type.startswith("text/") or content_type == "application/json"):
                item["status"] = "binary, not readable"
            elif not isinstance(data, str):
                item["status"] = "no inline text; external URLs not fetched"
            else:
                if len(data) > 4 * ((MAX_ATTACHMENT_BYTES + 2) // 3):
                    raise context_too_large()
                try:
                    decoded = base64.b64decode(data, validate=True)
                    if len(decoded) > MAX_ATTACHMENT_BYTES:
                        raise context_too_large()
                    item.update(status="decoded", text=decoded.decode("utf-8"))
                except (binascii.Error, UnicodeError):
                    item["status"] = "invalid base64 or UTF-8 text"
            result.append(item)
    return result


async def collect_patient_context(
    read: Read, case_id: str, uploads: UploadStore | None = None, max_bytes: int = 900_000
) -> dict[str, Any]:
    try:
        async with asyncio.timeout(COLLECTION_DEADLINE):
            return await _collect_patient_context(read, case_id, uploads, max_bytes)
    except TimeoutError as exc:
        raise WebError(503, "unavailable", "Patient context collection timed out") from exc


async def _section(
    read: Read, kind: str, case_id: str, budget: ByteBudget, slots: asyncio.Semaphore
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        async with slots:
            payload = await read(
                {"resourceType": kind, "patient": f"Patient/{case_id}", "_count": "50"}
            )
        items = _resources(payload)
        seen: set[str] = set()
        for item in items:
            _check_resource(item, kind, case_id)
            if item["id"] in seen:
                raise WebError(503, "unavailable", "Duplicate patient context resource")
            seen.add(item["id"])
        budget.charge(items)
        return items, {"status": "complete", "count": len(items), **payload.get("collection", {})}
    except (AuthError, ContractError, TransportError, OSError) as exc:
        reason = failure_metadata(exc)["reason"]
        if isinstance(exc, AuthError) or reason == "auth_failed":
            raise WebError(403, "forbidden", "Patient context read forbidden") from exc
        if reason == "resource_limit":
            raise context_too_large() from exc
        return [], {"status": "unavailable", "reason": reason}


async def _collect_patient_context(
    read: Read, case_id: str, uploads: UploadStore | None, max_bytes: int
) -> dict[str, Any]:
    # This is the same human-identity Patient read used by GET case, before fanout or uploads.
    try:
        patients = _resources(await read({"resourceType": "Patient", "id": case_id}))
    except (AuthError, ContractError) as exc:
        reason = failure_metadata(exc)["reason"]
        if isinstance(exc, AuthError) or reason == "auth_failed":
            raise WebError(403, "forbidden", "Patient context read forbidden") from exc
        if reason == "resource_limit":
            raise context_too_large() from exc
        raise
    if not patients:
        raise WebError(404, "not_found", "Case not found")
    if len(patients) != 1:
        raise WebError(503, "unavailable", "Patient context identity mismatch")
    _check_resource(patients[0], "Patient", case_id)
    # Reserve prompt instructions, JSON framing, and question before retaining context.
    budget = ByteBudget(max_bytes - 4096)
    budget.charge(patients)
    resources = list(patients)
    manifest: dict[str, Any] = {
        "collectedAt": datetime.now(UTC).isoformat(),
        "method": "patient-compartment searches (adapter does not expose $everything)",
        "types": {"Patient": {"status": "complete", "count": 1}},
        "uploads": "enabled" if uploads is not None else "not configured",
    }
    slots = asyncio.Semaphore(COLLECTION_CONCURRENCY)
    tasks = [
        asyncio.create_task(_section(read, kind, case_id, budget, slots))
        for kind in PATIENT_CONTEXT_TYPES
    ]
    try:
        sections = await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    for kind, (items, info) in zip(PATIENT_CONTEXT_TYPES, sections, strict=True):
        resources.extend(items)
        manifest["types"][kind] = info
    documents = document_texts(resources)
    manifest["documents"] = [
        {key: value for key, value in item.items() if key != "text"} for item in documents
    ]
    budget.charge(documents)
    budget.charge(manifest)
    cancelled = Event()
    try:
        upload_items = await asyncio.to_thread(
            collect_uploads, uploads, case_id, budget.remaining, cancelled
        )
    finally:
        # Cancelling to_thread cannot stop a blocked syscall; stop the next read/parse instead.
        cancelled.set()
    return {
        "manifest": manifest,
        "resources": resources,
        "documentTexts": documents,
        "uploads": upload_items,
    }
