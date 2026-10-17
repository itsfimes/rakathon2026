from __future__ import annotations

import copy
import re
import urllib.parse
from typing import Any

from rakathon_backend.common.errors import ContractError
from rakathon_backend.common.fhir import CLINICAL_TYPES, check_bundle
from rakathon_backend.uploads.review_validation import (
    PATIENT_ID_RE,
    REVIEW_TAG_CODE,
    REVIEW_TAG_SYSTEM,
    SOURCE_RE,
)


def _fail(code: str, message: str) -> ContractError:
    return ContractError(code=code, message=message)


def check_review_bundle(bundle: Any, patient_id: Any) -> dict[str, Any]:
    if not isinstance(patient_id, str) or PATIENT_ID_RE.fullmatch(patient_id) is None:
        raise _fail("bad_patient_id", "selected patient identifier is invalid")
    patient_ref = "Patient/" + patient_id
    if not isinstance(bundle, dict):
        raise _fail("bad_payload", "review bundle must be an object")
    if bundle.get("resourceType") != "Bundle" or bundle.get("type") != "transaction":
        raise _fail("bad_payload", "review bundle must be a transaction")
    entries = bundle.get("entry")
    if not isinstance(entries, list) or not entries:
        raise _fail("bad_payload", "review bundle carries no entries")
    bundle_meta = bundle.get("meta")
    if not isinstance(bundle_meta, dict):
        raise _fail("metadata_invalid", "review bundle ownership metadata is invalid")
    source = bundle_meta.get("source")
    if not isinstance(source, str) or SOURCE_RE.fullmatch(source) is None:
        raise _fail("metadata_invalid", "review bundle ownership metadata is invalid")
    targets: list[tuple[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise _fail("bad_payload", "review bundle entry is invalid")
        resource = entry.get("resource")
        if not isinstance(resource, dict):
            raise _fail("bad_payload", "review bundle entry resource is invalid")
        rtype = resource.get("resourceType")
        rid = resource.get("id")
        if not isinstance(rtype, str) or not isinstance(rid, str):
            raise _fail("bad_payload", "review bundle entry resource is invalid")
        if rtype == "Patient":
            raise _fail("patient_forbidden", "review import must not write a Patient")
        if rtype not in CLINICAL_TYPES:
            raise _fail("bad_payload", "review entry type is unsupported")
        targets.append((rtype, rid))
        request = entry.get("request")
        if not isinstance(request, dict):
            raise _fail("bad_payload", "review bundle entry request is invalid")
        if request.get("method") != "PUT":
            raise _fail("bad_payload", "review entry must use PUT")
        if request.get("url") != rtype + "/" + rid:
            raise _fail("bad_payload", "review entry url does not match the resource")
        if request.get("ifNoneMatch") != "*":
            raise _fail("metadata_invalid", "review entry guard is invalid")
        meta = resource.get("meta")
        if not isinstance(meta, dict):
            raise _fail("metadata_invalid", "review resource ownership metadata is invalid")
        if meta.get("source") != source:
            raise _fail("metadata_invalid", "review resource ownership metadata is invalid")
        tag = meta.get("tag")
        if not isinstance(tag, list) or len(tag) != 1:
            raise _fail("metadata_invalid", "review resource ownership metadata is invalid")
        first = tag[0]
        if not isinstance(first, dict):
            raise _fail("metadata_invalid", "review resource ownership metadata is invalid")
        if first.get("system") != REVIEW_TAG_SYSTEM or first.get("code") != REVIEW_TAG_CODE:
            raise _fail("metadata_invalid", "review resource ownership metadata is invalid")
        if rtype != "Provenance":
            subject = resource.get("subject")
            if subject is not None:
                if not isinstance(subject, dict):
                    raise _fail("association_mismatch", "review subject is invalid")
                if subject.get("reference") != patient_ref:
                    raise _fail("association_mismatch", "review subject points elsewhere")
    check_bundle(bundle, allowed_external_refs=frozenset({patient_ref}))
    return {
        "patient_ref": patient_ref,
        "patient_id": patient_id,
        "targets": targets,
        "source_urn": source,
    }


def _stripped(resource: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = copy.deepcopy(resource)
    meta = out.get("meta")
    if isinstance(meta, dict):
        meta.pop("versionId", None)
        meta.pop("lastUpdated", None)
    return out


def resources_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return _stripped(left) == _stripped(right)


def outcome_has_error(body: Any) -> bool:
    if not isinstance(body, dict):
        return True
    if body.get("resourceType") != "OperationOutcome":
        return True
    issues = body.get("issue")
    if not isinstance(issues, list):
        return True
    for issue in issues:
        if not isinstance(issue, dict):
            return True
        if issue.get("severity") in ("error", "fatal"):
            return True
        if issue.get("code") == "not-supported":
            return True
    return False


_LOCATION_VERSION_RE = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")


def _location_matches(location: str, rtype: str, rid: str) -> bool:
    text = location.strip()
    if not text or len(text) > 512:
        return False
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        return False
    if any(ch.isspace() for ch in text):
        return False
    if "\\" in text or "%" in text:
        return False
    if "://" in text:
        try:
            parsed = urllib.parse.urlparse(text)
        except ValueError:
            return False
        if parsed.scheme not in ("http", "https"):
            return False
        if parsed.username or parsed.password or not parsed.hostname:
            return False
        if parsed.query or parsed.fragment:
            return False
        try:
            _ = parsed.port
        except ValueError:
            return False
        path = parsed.path
    else:
        if ":" in text or "?" in text or "#" in text:
            return False
        path = text
    if not path:
        return False
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    segments = path.split("/")
    if segments and segments[0] == "":
        segments = segments[1:]
    if not segments or any(seg == "" for seg in segments):
        return False
    if any(seg in (".", "..") for seg in segments):
        return False
    if len(segments) >= 2 and segments[-2] == rtype and segments[-1] == rid:
        return True
    return (
        len(segments) >= 4
        and segments[-4] == rtype
        and segments[-3] == rid
        and segments[-2] == "_history"
        and _LOCATION_VERSION_RE.fullmatch(segments[-1]) is not None
    )


def check_transaction_response(body: Any, targets: list[tuple[str, str]]) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise _fail("remote_error", "transaction response is invalid")
    if body.get("resourceType") != "Bundle":
        raise _fail("remote_error", "transaction response is invalid")
    if body.get("type") != "transaction-response":
        raise _fail("remote_error", "transaction response is invalid")
    entries = body.get("entry")
    if not isinstance(entries, list) or not entries or len(entries) != len(targets):
        raise _fail("remote_error", "transaction response is invalid")
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise _fail("remote_error", "transaction response is invalid")
        response = entry.get("response")
        if not isinstance(response, dict):
            raise _fail("remote_error", "transaction response is invalid")
        status = response.get("status")
        if not isinstance(status, str) or status.strip()[:3] not in ("200", "201"):
            raise _fail("remote_error", "transaction response is invalid")
        location = response.get("location")
        if location is not None:
            if not isinstance(location, str) or not location.strip():
                raise _fail("remote_error", "transaction response is invalid")
            want_type, want_id = targets[index]
            if not _location_matches(location, want_type, want_id):
                raise _fail("remote_error", "transaction response is invalid")
        resource = entry.get("resource")
        if (
            isinstance(resource, dict)
            and resource.get("resourceType") == "OperationOutcome"
            and outcome_has_error(resource)
        ):
            raise _fail("remote_error", "transaction entry failed")
    return dict(body)
