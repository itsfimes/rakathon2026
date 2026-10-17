from __future__ import annotations

import io
import json
import re
import zipfile
from typing import Any

from rakathon_backend.common.errors import ContractError
from rakathon_backend.uploads.review_store import ReviewStore
from rakathon_backend.uploads.store_export import MAX_EXPORT_BYTES

UUID_RE = re.compile(r"^[0-9a-fA-F]{32}$")
REVIEW_PATH_RE = re.compile(
    r"^/api/v1/uploads/([0-9a-fA-F]{32})/review((?:/model|/draft|/approve)?)$"
)
META_PATH_RE = re.compile(r"^/api/v1/uploads/([0-9a-fA-F]{32})$")
EXPORT_PATH_RE = re.compile(r"^/api/v1/uploads/([0-9a-fA-F]{32})/export$")
CASE_LIST_SUFFIX = "/uploads"
APPROVE_ROLES = frozenset({"admin", "coordinator", "clinician"})


def no_dupes(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key " + key)
        out[key] = value
    return out


def reject_constant(value: str) -> Any:
    raise ValueError("non-finite constant " + value)


def strict_dict(raw: bytes | None) -> dict[str, Any]:
    if raw is None or not raw:
        raise ValueError("empty body")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("bad encoding") from exc
    try:
        parsed: Any = json.loads(text, object_pairs_hook=no_dupes, parse_constant=reject_constant)
    except json.JSONDecodeError as exc:
        raise ValueError("malformed json") from exc
    except (ValueError, TypeError) as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(parsed, dict):
        raise ContractError(code="invalid_schema", message="body is not strict json")
    return parsed


def err(
    status: int, code: str, message: str, extra: dict[str, Any] | None = None
) -> tuple[int, dict[str, str], Any]:
    body: dict[str, Any] = {"version": 1, "error": {"code": code, "message": message}}
    if extra:
        body["error"].update(dict(extra))
    return (status, {}, body)


def status_for(code: str) -> int:
    if code in ("not_found", "forbidden"):
        return 404
    if code == "conflict":
        return 409
    if code in ("busy", "import_busy"):
        return 429
    if code in ("too_large", "oversize"):
        return 413
    if code in ("unavailable", "store_unavailable", "not_configured"):
        return 503
    if code in ("bad_request", "method_not_allowed"):
        return 400
    return 422


def contract_response(exc: ContractError) -> tuple[int, dict[str, str], Any]:
    code = str(getattr(exc, "code", "invalid_schema") or "invalid_schema")
    message = str(getattr(exc, "message", "request rejected") or "request rejected")
    if code == "forbidden":
        return err(404, "not_found", "not found")
    if code == "conflict":
        return err(409, "conflict", message)
    return err(status_for(code), code, message)


def is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def json_only(headers: dict[str, str]) -> bool:
    lowered = {str(k).lower(): str(v) for k, v in headers.items()}
    ctype = lowered.get("content-type", "").split(";")[0].strip().lower()
    return ctype == "application/json"


def summary_for(reviews: ReviewStore, user_id: str, job_id: str) -> dict[str, Any] | None:
    try:
        info = reviews.summary(job_id, user_id)
    except ContractError:
        return None
    except (OSError, ValueError, RuntimeError):
        return None
    return {
        "state": str(info.get("state", "")),
        "revision": int(info.get("revision", 0)),
        "valid": bool(info.get("valid", False)),
        "updatedAt": str(info.get("updatedAt", "")),
        "reviewedBy": info.get("reviewedBy"),
    }


def merge_zip(base_blob: bytes, arts: dict[str, bytes]) -> bytes | None:
    try:
        src = zipfile.ZipFile(io.BytesIO(base_blob), "r")
        names = set(src.namelist())
        kept = [(info, src.read(info.filename)) for info in src.infolist()]
        src.close()
    except zipfile.BadZipFile:
        return None
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dest:
        for info, data in kept:
            dest.writestr(info.filename, data)
        for name, data in arts.items():
            if name in names:
                continue
            dest.writestr(name, data)
    return buf.getvalue()


def enrich(
    reviews: ReviewStore,
    user_id: str,
    method: str,
    path: str,
    out: tuple[int, dict[str, str], Any],
) -> tuple[int, dict[str, str], Any]:
    status, headers, payload = out
    if status != 200 or method != "GET":
        return out
    if EXPORT_PATH_RE.match(path) is not None:
        if isinstance(payload, (bytes, bytearray)):
            return enrich_export(reviews, user_id, path, status, headers, bytes(payload))
        return out
    if META_PATH_RE.match(path) is not None:
        if isinstance(payload, dict):
            return enrich_meta(reviews, user_id, path, headers, payload)
        return out
    if path.startswith("/api/v1/cases/") and path.endswith(CASE_LIST_SUFFIX):
        if isinstance(payload, dict):
            return enrich_list(reviews, user_id, headers, payload)
        return out
    return out


def enrich_meta(
    reviews: ReviewStore, user_id: str, path: str, headers: dict[str, str], payload: dict[str, Any]
) -> tuple[int, dict[str, str], Any]:
    matched = META_PATH_RE.match(path)
    if matched is None:
        return (200, headers, payload)
    job = payload.get("job")
    if not isinstance(job, dict):
        return (200, headers, payload)
    brief = summary_for(reviews, user_id, str(matched.group(1)).lower())
    if brief is None:
        return (200, headers, payload)
    next_job = dict(job)
    next_job["review"] = brief
    next_payload = dict(payload)
    next_payload["job"] = next_job
    return (200, headers, next_payload)


def enrich_list(
    reviews: ReviewStore, user_id: str, headers: dict[str, str], payload: dict[str, Any]
) -> tuple[int, dict[str, str], Any]:
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        return (200, headers, payload)
    enriched: list[Any] = []
    for item in jobs:
        if not isinstance(item, dict):
            enriched.append(item)
            continue
        raw_id = item.get("id")
        if not isinstance(raw_id, str) or UUID_RE.match(raw_id) is None:
            enriched.append(item)
            continue
        brief = summary_for(reviews, user_id, raw_id.lower())
        if brief is None:
            enriched.append(item)
            continue
        nxt = dict(item)
        nxt["review"] = brief
        enriched.append(nxt)
    next_payload = dict(payload)
    next_payload["jobs"] = enriched
    return (200, headers, next_payload)


def enrich_export(
    reviews: ReviewStore,
    user_id: str,
    path: str,
    status: int,
    headers: dict[str, str],
    blob: bytes,
) -> tuple[int, dict[str, str], Any]:
    matched = EXPORT_PATH_RE.match(path)
    if matched is None:
        return (status, headers, blob)
    try:
        arts = reviews.export_artifacts(str(matched.group(1)).lower(), user_id)
    except ContractError:
        return (status, headers, blob)
    except (OSError, ValueError, RuntimeError):
        return (status, headers, blob)
    try:
        merged = merge_zip(blob, arts)
    except (OSError, ValueError, KeyError):
        return (status, headers, blob)
    if merged is None or len(merged) > MAX_EXPORT_BYTES:
        return (
            503,
            {},
            {"version": 1, "error": {"code": "unavailable", "message": "export too large"}},
        )
    return (status, headers, merged)
