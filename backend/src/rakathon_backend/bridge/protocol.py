from __future__ import annotations

import re
from typing import Any

from rakathon_backend.b2.iris.screening_sql import MAX_BATCH
from rakathon_backend.b2.screening import archive as screening_archive
from rakathon_backend.b2.screening import schema as screening_schema
from rakathon_backend.common.errors import ContractError
from rakathon_backend.common.fhir import ALLOWED_TYPES, check_bundle, check_resource

BRIDGE_OPERATIONS = frozenset(
    {
        "fhir.write",
        "fhir.read",
        "fhir.search",
        "screening.import",
        "screening.query",
        "tasks.write",
        "tasks.read",
        "tasks.ack",
        "vector.search",
        "health",
    }
)
FHIR_TYPES = ALLOWED_TYPES
TX_METHODS = frozenset({"POST", "PUT"})
MAX_ARGS_BYTES = 512 * 1024
MAX_OUTER_BYTES = 1024 * 1024 + 1024
_ID_RE = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")
_SAFE_URL_RE = re.compile(r"^(" + "|".join(sorted(FHIR_TYPES)) + r")(/[A-Za-z0-9\-.]{1,64})?$")
_PARAM_KEY_RE = re.compile(r"^[A-Za-z0-9_\-.]{1,64}$")


def check_outer(raw: Any) -> tuple[str, str]:
    if not isinstance(raw, dict):
        raise ContractError(code="bad_envelope", message="outer envelope invalid")
    if set(raw) != {"keyId", "token"}:
        raise ContractError(code="bad_envelope", message="outer envelope invalid")
    key_id = raw.get("keyId")
    token = raw.get("token")
    if not isinstance(key_id, str) or not key_id.strip() or len(key_id) > 64:
        raise ContractError(code="bad_envelope", message="outer envelope invalid")
    if not isinstance(token, str) or not token or len(token) > MAX_OUTER_BYTES:
        raise ContractError(code="bad_envelope", message="outer envelope invalid")
    return (key_id.strip(), token)


def check_operation(operation: Any) -> str:
    if not isinstance(operation, str) or operation not in BRIDGE_OPERATIONS:
        raise ContractError(code="bad_operation", message="operation not allowed")
    return operation


def _resource_ok(resource: Any) -> dict[str, Any]:
    check_resource(resource)
    assert isinstance(resource, dict)
    return dict(resource)


def _bundle_ok(bundle: Any, transaction_only: bool = False) -> dict[str, Any]:
    if not isinstance(bundle, dict):
        raise ContractError(code="bad_payload", message="Bundle invalid")
    if bundle.get("resourceType") != "Bundle":
        raise ContractError(code="bad_payload", message="Bundle invalid")
    check_bundle(bundle)
    btype = bundle.get("type")
    if transaction_only and btype != "transaction":
        raise ContractError(code="bad_payload", message="Bundle must be transaction")
    if btype not in ("transaction", "collection", "searchset", "history"):
        raise ContractError(code="bad_payload", message="Bundle type unsupported")
    return dict(bundle)


def check_arguments(operation: str, arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ContractError(code="bad_payload", message="arguments invalid")
    if operation == "health":
        if arguments:
            raise ContractError(code="bad_payload", message="health takes no arguments")
        return {}
    if operation == "fhir.read":
        rtype = arguments.get("resourceType")
        rid = arguments.get("id")
        if not isinstance(rtype, str) or rtype not in FHIR_TYPES:
            raise ContractError(code="bad_payload", message="resourceType invalid")
        if not isinstance(rid, str) or _ID_RE.fullmatch(rid.strip()) is None:
            raise ContractError(code="bad_payload", message="id invalid")
        return {"resourceType": rtype, "id": rid.strip()}
    if operation == "fhir.search":
        rtype = arguments.get("resourceType")
        params = arguments.get("params", {})
        if not isinstance(rtype, str) or rtype not in FHIR_TYPES:
            raise ContractError(code="bad_payload", message="resourceType invalid")
        if not isinstance(params, dict):
            raise ContractError(code="bad_payload", message="params invalid")
        clean: dict[str, str] = {}
        for key, value in params.items():
            if not isinstance(key, str) or _PARAM_KEY_RE.fullmatch(key) is None:
                raise ContractError(code="bad_payload", message="search param invalid")
            if not isinstance(value, str) or not value or len(value) > 256:
                raise ContractError(code="bad_payload", message="search param invalid")
            clean[key] = value
        return {"resourceType": rtype, "params": clean}
    if operation == "fhir.write":
        if "resource" in arguments and "bundle" in arguments:
            raise ContractError(code="bad_payload", message="write takes one payload")
        if "resource" in arguments:
            return {"resource": _resource_ok(arguments["resource"])}
        if "bundle" in arguments:
            return {"bundle": _bundle_ok(arguments["bundle"])}
        raise ContractError(code="bad_payload", message="write needs resource or bundle")
    if operation == "tasks.write":
        task = arguments.get("task")
        if not isinstance(task, dict):
            raise ContractError(code="bad_payload", message="task invalid")
        return {"task": dict(task)}
    if operation == "tasks.read":
        tid = arguments.get("taskId")
        if tid is not None and (not isinstance(tid, str) or not tid.strip()):
            raise ContractError(code="bad_payload", message="task id invalid")
        return {"taskId": tid.strip() if isinstance(tid, str) else None}
    if operation == "tasks.ack":
        tid = arguments.get("taskId")
        user = arguments.get("userId")
        if not isinstance(tid, str) or not tid.strip():
            raise ContractError(code="bad_payload", message="task id invalid")
        if not isinstance(user, str) or not user.strip():
            raise ContractError(code="bad_payload", message="user id invalid")
        return {"taskId": tid.strip(), "userId": user.strip()}
    if operation == "screening.import":
        rows = arguments.get("rows")
        if not isinstance(rows, list) or not rows or len(rows) > MAX_BATCH:
            raise ContractError(code="bad_payload", message="import batch must hold 1..500 rows")
        clean_rows: list[dict[str, str]] = []
        for item in rows:
            if not isinstance(item, dict):
                raise ContractError(code="bad_payload", message="screening row invalid")
            checked = screening_schema.validate_row(item)
            clean_rows.append(checked)
        return {"rows": clean_rows}
    if operation == "screening.query":
        filters, projection, limit, offset = screening_archive.check_query_args(
            arguments.get("filters", {}),
            arguments.get("projection"),
            arguments.get("limit", 100),
            arguments.get("offset", 0),
        )
        return {
            "filters": filters,
            "projection": projection,
            "limit": limit,
            "offset": offset,
        }
    if operation == "vector.search":
        channel = arguments.get("channel")
        query = arguments.get("query")
        limit = arguments.get("limit", 5)
        if channel not in ("anonymized", "patient"):
            raise ContractError(code="bad_payload", message="channel invalid")
        if not isinstance(query, str) or not query or len(query) > 8192:
            raise ContractError(code="bad_payload", message="query invalid")
        if not isinstance(limit, int) or limit <= 0 or limit > 50:
            raise ContractError(code="bad_payload", message="limit invalid")
        return {"channel": channel, "query": query, "limit": limit}
    raise ContractError(code="bad_operation", message="operation not allowed")
