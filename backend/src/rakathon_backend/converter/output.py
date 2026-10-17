from __future__ import annotations

import json
from typing import Any

from rakathon_backend.common.errors import ContractError
from rakathon_backend.common.fhir import CLINICAL_TYPES, check_bundle, resource_counts
from rakathon_backend.converter import output_io as _output_io
from rakathon_backend.converter.extract import Extracted
from rakathon_backend.converter.output_io import OutputError

__all__ = ["OutputError", "write_outputs"]

write_outputs = _output_io.write_outputs

STATUSES = frozenset({"complete", "incomplete", "manual-review"})
EXACT_KEYS = frozenset({"status", "bundle", "issues", "evidence"})
MAX_ISSUES = 32
MAX_EVIDENCE = 128
MAX_CODE_CHARS = 128
MAX_MESSAGE_CHARS = 500
MAX_QUOTE_CHARS = 1000
MAX_FIELD_CHARS = 256
MIN_QUOTE_CHARS = 8


def _fail(code: str) -> OutputError:
    return OutputError(code, "model output failed strict validation")


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite constant {value}")


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key {key}")
        out[key] = value
    return out


def _check_issue(item: Any) -> dict[str, str]:
    if not isinstance(item, dict) or set(item) != {"code", "message"}:
        raise _fail("bad_issues")
    code = item["code"]
    message = item["message"]
    if not isinstance(code, str) or not isinstance(message, str):
        raise _fail("bad_issues")
    if not code or len(code) > MAX_CODE_CHARS or len(message) > MAX_MESSAGE_CHARS:
        raise _fail("bad_issues")
    if not message.strip():
        raise _fail("bad_issues")
    return {"code": code, "message": message}


def _check_evidence_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise _fail("bad_evidence")
    keys = set(item)
    if keys - {"resourceType", "id", "sourcePage", "literalQuote", "field"}:
        raise _fail("bad_evidence")
    if keys < {"resourceType", "id", "sourcePage", "literalQuote"}:
        raise _fail("bad_evidence")
    rtype = item["resourceType"]
    rid = item["id"]
    page = item["sourcePage"]
    quote = item["literalQuote"]
    if not isinstance(rtype, str) or not isinstance(rid, str):
        raise _fail("bad_evidence")
    if not rtype or not rid or isinstance(page, bool) or not isinstance(page, int):
        raise _fail("bad_evidence")
    if not isinstance(quote, str) or not quote or len(quote) > MAX_QUOTE_CHARS:
        raise _fail("bad_evidence")
    if len(quote.strip()) < MIN_QUOTE_CHARS:
        raise _fail("bad_evidence")
    out: dict[str, Any] = {
        "resourceType": rtype,
        "id": rid,
        "sourcePage": page,
        "literalQuote": quote,
    }
    if "field" in item:
        field = item["field"]
        if not isinstance(field, str) or not field.startswith("/") or len(field) > MAX_FIELD_CHARS:
            raise _fail("bad_evidence")
        out["field"] = field
    elif rtype in CLINICAL_TYPES:
        raise _fail("bad_evidence")
    return out


def _resolve_pointer(resource: dict[str, Any], pointer: str) -> bool:
    current: Any = resource
    for raw in pointer.split("/")[1:]:
        part = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if part not in current:
                return False
            current = current[part]
        elif isinstance(current, list):
            if not part.isdigit() or int(part) >= len(current):
                return False
            current = current[int(part)]
        else:
            return False
    return True


def parse_model_output_strict(text: str) -> dict[str, Any]:
    if "```" in text:
        raise OutputError("fenced_output", "model output carries markdown fences")
    try:
        parsed: Any = json.loads(
            text, object_pairs_hook=_no_duplicates, parse_constant=_reject_constant
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise OutputError("malformed_json", "model output is not strict JSON") from exc
    if not isinstance(parsed, dict) or set(parsed) != EXACT_KEYS:
        raise _fail("bad_envelope")
    status = parsed["status"]
    bundle, issues, evidence = parsed["bundle"], parsed["issues"], parsed["evidence"]
    if status not in STATUSES:
        raise _fail("bad_status")
    if bundle is not None and not isinstance(bundle, dict):
        raise _fail("bad_bundle")
    if not isinstance(issues, list) or len(issues) > MAX_ISSUES:
        raise _fail("bad_issues")
    if not isinstance(evidence, list) or len(evidence) > MAX_EVIDENCE:
        raise _fail("bad_evidence")
    checked_issues = [_check_issue(item) for item in issues]
    checked_evidence = [_check_evidence_item(item) for item in evidence]
    if status == "manual-review" and bundle is not None:
        raise OutputError("bundle_on_review", "manual-review output must carry a null bundle")
    if status in ("complete", "incomplete") and bundle is None:
        raise OutputError("null_bundle", "complete output must carry a bundle")
    if status == "complete" and checked_issues:
        raise OutputError("complete_has_issues", "complete output must carry no issues")
    validated: dict[str, Any] | None = None
    if bundle is not None:
        if bundle.get("resourceType") == "OperationOutcome":
            raise OutputError("outcome_rejected", "OperationOutcome is never a valid bundle")
        try:
            validated = check_bundle(bundle)
        except ContractError as exc:
            raise OutputError("fhir_rejected", f"structural checks failed: {exc.code}") from exc
    return {
        "status": status,
        "bundle": validated,
        "issues": checked_issues,
        "evidence": checked_evidence,
    }


def check_evidence(
    parsed: dict[str, Any], extracted: Extracted, *, conflict: bool
) -> dict[str, Any]:
    bundle = parsed["bundle"]
    evidence: list[dict[str, Any]] = list(parsed["evidence"])
    issues: list[dict[str, str]] = [dict(item) for item in parsed["issues"]]
    status: str = str(parsed["status"])
    if conflict and status != "manual-review":
        status = "manual-review"
        issues.append({"code": "conflicting_identity", "message": "pages carry conflicting ids"})
        return {"status": status, "bundle": None, "issues": issues, "evidence": evidence}
    if bundle is None:
        return {"status": status, "bundle": None, "issues": issues, "evidence": evidence}
    entries = bundle.get("entry")
    assert isinstance(entries, list)
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in entries:
        resource = entry.get("resource")
        assert isinstance(resource, dict)
        by_key[(str(resource.get("resourceType")), str(resource.get("id")))] = resource
    for item in evidence:
        page = int(item["sourcePage"])
        if page < 1 or page > len(extracted.pages):
            raise OutputError("bad_source_page", "evidence cites an unknown source page")
        quote = str(item["literalQuote"])
        if quote not in extracted.pages[page - 1] or quote not in extracted.text:
            raise OutputError("quote_not_found", "evidence quote is absent from the extract")
        key = (str(item["resourceType"]), str(item["id"]))
        resource = by_key.get(key)
        if resource is None:
            raise OutputError("evidence_no_resource", "evidence cites an unknown resource")
        if "field" in item and not _resolve_pointer(resource, str(item["field"])):
            raise OutputError("bad_field_pointer", "evidence field pointer is absent")
    for key in by_key:
        if key[0] in CLINICAL_TYPES and not any(
            (item["resourceType"], item["id"]) == key for item in evidence
        ):
            raise OutputError("missing_evidence", f"clinical resource {key[0]} lacks evidence")
    return {"status": status, "bundle": bundle, "issues": issues, "evidence": evidence}


def assemble_result(
    checked: dict[str, Any],
    extracted: Extracted,
    *,
    model_present: bool,
    provider_id: str,
    model: str,
    runtime_s: float,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]:
    bundle = checked["bundle"]
    bundle_out: dict[str, Any] | None = None
    if bundle is not None:
        bundle_out = dict(bundle)
        meta = dict(bundle_out.get("meta") or {})
        meta["source"] = f"urn:sha256:{extracted.source_sha256}"
        bundle_out["meta"] = meta
    result = {
        "status": checked["status"],
        "bundle": bundle_out,
        "issues": checked["issues"],
        "evidence": checked["evidence"],
        "needsReview": True,
        "writeEligible": False,
        "persistence": "not-written",
        "source": {
            "sha256": extracted.source_sha256,
            "extractSha256": extracted.extract_sha256,
            "pages": len(extracted.pages),
            "suffix": extracted.suffix,
        },
        "model": {"providerId": provider_id, "model": model, "present": model_present},
    }
    provenance = {
        "sourceSha256": extracted.source_sha256,
        "extractSha256": extracted.extract_sha256,
        "pages": len(extracted.pages),
        "suffix": extracted.suffix,
        "filename": extracted.filename,
        "providerId": provider_id,
        "model": model,
        "modelPresent": model_present,
        "runtimeS": round(runtime_s, 3),
        "counts": resource_counts(bundle) if bundle is not None else {},
    }
    return (result, bundle_out, provenance)


def manual_result(
    code: str,
    message: str,
    extracted: Extracted | None,
    *,
    provider_id: str,
    model: str,
    runtime_s: float,
    filename: str | None = None,
    source_sha: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]:
    checked: dict[str, Any] = {
        "status": "manual-review",
        "bundle": None,
        "issues": [{"code": code, "message": message}],
        "evidence": [],
    }
    if extracted is None:
        source = None if source_sha is None else {"sha256": source_sha, "filename": filename}
        result: dict[str, Any] = {
            "status": "manual-review",
            "bundle": None,
            "issues": checked["issues"],
            "evidence": [],
            "needsReview": True,
            "writeEligible": False,
            "persistence": "not-written",
            "source": source,
            "model": {"providerId": provider_id, "model": model, "present": False},
        }
        provenance: dict[str, Any] = {
            "sourceSha256": source_sha,
            "extractSha256": None,
            "pages": 0,
            "suffix": None,
            "filename": filename,
            "providerId": provider_id,
            "model": model,
            "modelPresent": False,
            "runtimeS": round(runtime_s, 3),
            "counts": {},
        }
        return (result, None, provenance)
    return assemble_result(
        checked,
        extracted,
        model_present=False,
        provider_id=provider_id,
        model=model,
        runtime_s=runtime_s,
    )
