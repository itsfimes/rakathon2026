from __future__ import annotations

import re
from typing import Any

from rakathon_backend.common.errors import ContractError

CLINICAL_TYPES = frozenset(
    {
        "Patient",
        "ServiceRequest",
        "Observation",
        "DiagnosticReport",
        "DocumentReference",
        "Condition",
        "Procedure",
        "Provenance",
    }
)
ENVELOPE_TYPES = frozenset({"Task", "Bundle", "OperationOutcome"})
ALLOWED_TYPES = CLINICAL_TYPES | ENVELOPE_TYPES
MAX_TRANSACTION_ENTRIES = 100

_ID_RE = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")
_RT_RE = re.compile(r"^[A-Za-z]+$")
_SAFE_URL_RE = re.compile(r"^(" + "|".join(sorted(ALLOWED_TYPES)) + r")(/[A-Za-z0-9\-.]{1,64})?$")
_EXEC_PREFIXES = ("javascript:", "data:", "vbscript:", "file:")

_STATUS_VALUES: dict[str, frozenset[str]] = {
    "ServiceRequest": frozenset(
        {"draft", "active", "on-hold", "revoked", "completed", "entered-in-error", "unknown"}
    ),
    "Observation": frozenset(
        {
            "registered",
            "preliminary",
            "final",
            "amended",
            "corrected",
            "cancelled",
            "entered-in-error",
            "unknown",
        }
    ),
    "DiagnosticReport": frozenset(
        {
            "registered",
            "partial",
            "preliminary",
            "final",
            "amended",
            "corrected",
            "appended",
            "cancelled",
            "entered-in-error",
            "unknown",
        }
    ),
    "Procedure": frozenset(
        {
            "preparation",
            "in-progress",
            "not-done",
            "on-hold",
            "stopped",
            "completed",
            "entered-in-error",
            "unknown",
        }
    ),
    "DocumentReference": frozenset({"current", "superseded", "entered-in-error"}),
}


def _fail(message: str) -> ContractError:
    return ContractError(code="bad_payload", message=message)


def check_resource_id(resource: Any) -> tuple[str, str]:
    if not isinstance(resource, dict):
        raise _fail("resource must be an object")
    rtype = resource.get("resourceType")
    rid = resource.get("id")
    if not isinstance(rtype, str) or _RT_RE.fullmatch(rtype) is None or rtype not in ALLOWED_TYPES:
        raise _fail("resource needs an allowed type and id")
    if not isinstance(rid, str) or _ID_RE.fullmatch(rid.strip()) is None:
        raise _fail("resource needs an allowed type and id")
    return (rtype, rid.strip())


def _scan_strings(value: Any) -> None:
    if isinstance(value, str):
        lowered = value.strip().lower()
        for prefix in _EXEC_PREFIXES:
            if lowered.startswith(prefix):
                raise _fail("resource carries an executable URL")
        return
    if isinstance(value, dict):
        for item in value.values():
            _scan_strings(item)
        return
    if isinstance(value, list):
        for item in value:
            _scan_strings(item)


def _check_status(rtype: str, resource: dict[str, Any]) -> None:
    allowed = _STATUS_VALUES.get(rtype)
    if allowed is None:
        return
    status = resource.get("status")
    if status is None:
        return
    if not isinstance(status, str) or status not in allowed:
        raise _fail("resource status is not a known value")


def _check_minimal(rtype: str, resource: dict[str, Any]) -> None:
    if rtype == "ServiceRequest":
        for key in ("status", "intent", "subject"):
            if key not in resource:
                raise _fail("ServiceRequest is missing a required field")
        if not isinstance(resource.get("subject"), dict):
            raise _fail("ServiceRequest is missing a required field")
    elif rtype == "Observation":
        for key in ("status", "code"):
            if key not in resource:
                raise _fail("Observation is missing a required field")
    elif rtype == "DiagnosticReport":
        for key in ("status", "code"):
            if key not in resource:
                raise _fail("DiagnosticReport is missing a required field")
    elif rtype == "DocumentReference":
        for key in ("status", "content"):
            if key not in resource:
                raise _fail("DocumentReference is missing a required field")
        if not isinstance(resource.get("content"), list) or not resource["content"]:
            raise _fail("DocumentReference is missing a required field")
    elif rtype == "Condition":
        if "code" not in resource:
            raise _fail("Condition is missing a required field")
    elif rtype == "Procedure":
        for key in ("status", "subject"):
            if key not in resource:
                raise _fail("Procedure is missing a required field")
    elif rtype == "Provenance":
        for key in ("target", "recorded"):
            if key not in resource:
                raise _fail("Provenance is missing a required field")


def check_resource(resource: Any) -> tuple[str, str]:
    rtype, rid = check_resource_id(resource)
    assert isinstance(resource, dict)
    _scan_strings(resource)
    _check_status(rtype, resource)
    _check_minimal(rtype, resource)
    return (rtype, rid)


def _check_request(entry: dict[str, Any], rtype: str, rid: str) -> None:
    request = entry.get("request")
    if request is None:
        return
    if not isinstance(request, dict):
        raise _fail("transaction entry is invalid")
    method = request.get("method")
    url = request.get("url")
    if method not in ("POST", "PUT"):
        raise _fail("transaction method is unsupported")
    if not isinstance(url, str) or _SAFE_URL_RE.fullmatch(url.strip()) is None:
        raise _fail("transaction url is unsafe")
    text = url.strip()
    if "://" in text or text.startswith("/") or "?" in text:
        raise _fail("transaction url is unsafe")
    parts = text.split("/")
    if method == "PUT":
        valid = len(parts) == 2 and parts[0] == rtype and parts[1] == rid
    else:
        valid = (len(parts) == 2 and parts[0] == rtype and parts[1] == rid) or (
            len(parts) == 1 and parts[0] == rtype
        )
    if not valid:
        raise _fail("transaction url does not match the resource")


def _collect_references(value: Any, out: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "reference" and isinstance(item, str) and item.strip():
                out.append(item.strip())
            else:
                _collect_references(item, out)
        return
    if isinstance(value, list):
        for item in value:
            _collect_references(item, out)


def check_bundle(bundle: Any) -> dict[str, Any]:
    if not isinstance(bundle, dict):
        raise _fail("bundle must be an object")
    if bundle.get("resourceType") == "OperationOutcome":
        issues = bundle.get("issue")
        if not isinstance(issues, list) or not issues:
            raise _fail("OperationOutcome carries no issues")
        return dict(bundle)
    if bundle.get("resourceType") != "Bundle":
        raise _fail("bundle must be a Bundle or OperationOutcome")
    entries = bundle.get("entry")
    if not isinstance(entries, list) or not entries:
        raise _fail("bundle carries no entries")
    if len(entries) > MAX_TRANSACTION_ENTRIES:
        raise _fail("bundle carries too many entries")
    seen_ids: set[tuple[str, str]] = set()
    seen_urls: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise _fail("bundle entry is invalid")
        resource = entry.get("resource")
        rtype, rid = check_resource(resource)
        key = (rtype, rid)
        if key in seen_ids:
            raise _fail("bundle carries duplicate resource ids")
        seen_ids.add(key)
        full_url = entry.get("fullUrl")
        if full_url is not None:
            if not isinstance(full_url, str) or not full_url.strip():
                raise _fail("bundle entry fullUrl is invalid")
            text_url = full_url.strip()
            if not text_url.startswith(("urn:uuid:", "urn:sha256:")):
                raise _fail("bundle entry fullUrl is invalid")
            if text_url in seen_urls:
                raise _fail("bundle carries duplicate fullUrls")
            seen_urls.add(text_url)
        _check_request(entry, rtype, rid)
    refs: list[str] = []
    _collect_references(bundle, refs)
    for ref in refs:
        if ref.startswith("urn:"):
            if ref not in seen_urls:
                raise _fail("bundle reference is not closed")
        elif re.fullmatch(r"[A-Za-z]+/[A-Za-z0-9\-.]{1,64}", ref):
            rtype, _, rid = ref.partition("/")
            if (rtype, rid) not in seen_ids:
                raise _fail("bundle reference is not closed")
        elif ref.startswith("#"):
            raise _fail("bundle reference is not closed")
        else:
            raise _fail("bundle reference is not closed")
    return dict(bundle)


def validate_bundle(bundle: Any) -> bool:
    try:
        check_bundle(bundle)
    except ContractError:
        return False
    return True


def is_manual_review(bundle: Any) -> bool:
    return isinstance(bundle, dict) and bundle.get("resourceType") == "OperationOutcome"


def resource_counts(bundle: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not isinstance(bundle, dict):
        return counts
    if bundle.get("resourceType") == "OperationOutcome":
        counts["OperationOutcome"] = 1
        return counts
    entries = bundle.get("entry")
    if not isinstance(entries, list):
        return counts
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        resource = entry.get("resource")
        if not isinstance(resource, dict):
            continue
        rtype = resource.get("resourceType")
        if isinstance(rtype, str):
            counts[rtype] = counts.get(rtype, 0) + 1
    return counts


def attach_source(bundle: dict[str, Any], source_urn: str) -> dict[str, Any]:
    out = dict(bundle)
    meta = out.get("meta")
    meta_obj = dict(meta) if isinstance(meta, dict) else {}
    meta_obj["source"] = source_urn
    out["meta"] = meta_obj
    return out
