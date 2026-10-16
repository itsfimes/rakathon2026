from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any

from rakathon_backend.common.errors import AuthError, ContractError
from rakathon_backend.common.fhir import ALLOWED_TYPES, check_bundle, check_resource

FHIR_TYPES = ALLOWED_TYPES
TX_METHODS = frozenset({"POST", "PUT"})
_ID_RE = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")
_RT_RE = re.compile(r"^[A-Za-z]+$")
_SAFE_URL_RE = re.compile(r"^(" + "|".join(sorted(FHIR_TYPES)) + r")(/[A-Za-z0-9\-.]{1,64})?$")


@dataclass
class StoredVector:
    vector_id: str
    text: str
    synthetic: bool = True
    resource: dict[str, Any] | None = None


def _check_resource(resource: Any) -> tuple[str, str]:
    return check_resource(resource)


def _check_tx_entry(entry: Any) -> tuple[str, str, dict[str, Any], str, str]:
    if not isinstance(entry, dict):
        raise ContractError(code="bad_payload", message="transaction entry invalid")
    request = entry.get("request")
    resource = entry.get("resource")
    if not isinstance(request, dict) or not isinstance(resource, dict):
        raise ContractError(code="bad_payload", message="transaction entry invalid")
    method = request.get("method")
    url = request.get("url")
    if method not in TX_METHODS:
        raise ContractError(code="bad_payload", message="transaction method unsupported")
    if not isinstance(url, str) or _SAFE_URL_RE.fullmatch(url.strip()) is None:
        raise ContractError(code="bad_payload", message="transaction url unsafe")
    if "://" in url or url.strip().startswith("/") or "?" in url:
        raise ContractError(code="bad_payload", message="transaction url unsafe")
    rtype, rid = _check_resource(resource)
    url_text = url.strip()
    parts = url_text.split("/")
    if method == "PUT":
        valid = len(parts) == 2 and parts[0] == rtype and parts[1] == rid
    else:
        valid = (len(parts) == 2 and parts[0] == rtype and parts[1] == rid) or (
            len(parts) == 1 and parts[0] == rtype
        )
    if not valid:
        raise ContractError(code="bad_payload", message="transaction url mismatch")
    return (rtype, rid, dict(resource), str(method), url_text)


@dataclass
class MemoryStorage:
    fhir: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    vectors: list[StoredVector] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def fhir_write(self, resource: dict[str, Any]) -> dict[str, Any]:
        _check_resource(resource)
        stored = dict(resource)
        key = (str(resource["resourceType"]), str(resource["id"]).strip())
        with self._lock:
            self.fhir[key] = stored
        return dict(stored)

    def fhir_transaction(self, bundle: dict[str, Any]) -> dict[str, Any]:
        check_bundle(bundle)
        if bundle.get("resourceType") != "Bundle":
            raise ContractError(code="bad_payload", message="transaction needs Bundle")
        if bundle.get("type") != "transaction":
            raise ContractError(code="bad_payload", message="Bundle type must be transaction")
        entries = bundle.get("entry")
        if not isinstance(entries, list) or not entries:
            raise ContractError(code="bad_payload", message="transaction needs entries")
        if len(entries) > 100:
            raise ContractError(code="bad_payload", message="transaction too large")
        checked: list[tuple[str, str, dict[str, Any], str, str]] = []
        for item in entries:
            checked.append(_check_tx_entry(item))
        with self._lock:
            for item, (rtype, rid, _resource, _method, _url) in zip(entries, checked, strict=True):
                if item["request"].get("ifNoneMatch") == "*" and (rtype, rid) in self.fhir:
                    raise ContractError(code="import_conflict", message="Resource already exists")
            for rtype, rid, resource, _method, _url in checked:
                self.fhir[(rtype, rid)] = dict(resource)
            out_entries: list[dict[str, Any]] = []
            for rtype, rid, _res, method, _url in checked:
                status = "201 Created" if method == "POST" else "200 OK"
                out_entries.append({"response": {"status": status, "location": f"{rtype}/{rid}"}})
        return {
            "resourceType": "Bundle",
            "type": "transaction-response",
            "entry": out_entries,
        }

    def fhir_read(self, resource_type: str, rid: str) -> dict[str, Any] | None:
        with self._lock:
            found = self.fhir.get((resource_type, rid))
            return dict(found) if found is not None else None

    def fhir_search(self, resource_type: str, params: dict[str, str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        with self._lock:
            items = list(self.fhir.items())
        for (rtype, _rid), resource in items:
            if rtype != resource_type:
                continue
            if all(str(resource.get(k, "")) == v for k, v in params.items()):
                out.append(dict(resource))
        return out

    def fhir_search_with_total(
        self, resource_type: str, params: dict[str, str]
    ) -> tuple[list[dict[str, Any]], int | None]:
        return (self.fhir_search(resource_type, dict(params)), None)

    def tasks_create(self, task: dict[str, Any]) -> dict[str, Any]:
        stored = dict(task)
        with self._lock:
            if str(task["id"]) in self.tasks:
                raise ContractError(code="duplicate_id", message="task already exists")
            self.tasks[str(task["id"])] = stored
        return dict(stored)

    def tasks_write(self, task: dict[str, Any]) -> dict[str, Any]:
        stored = dict(task)
        with self._lock:
            self.tasks[str(task["id"])] = stored
        return dict(stored)

    def tasks_read(self, task_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if task_id is not None:
                found = self.tasks.get(task_id)
                return [dict(found)] if found is not None else []
            return [dict(v) for v in self.tasks.values()]

    def tasks_ack(self, task_id: str, user_id: str) -> dict[str, Any]:
        with self._lock:
            current = self.tasks.get(task_id)
            if current is None:
                raise KeyError(task_id)
            task = dict(current)
            if task.get("ownerId") != user_id and user_id not in list(
                task.get("requiredAckUserIds", [])
            ):
                raise AuthError(code="auth_failed", message="user is not a task member")
            acked = list(task.get("acknowledgedBy", []))
            if user_id in acked:
                return dict(task)
            acked.append(user_id)
            task["acknowledgedBy"] = acked
            required = set(task.get("requiredAckUserIds", []))
            if required and set(acked) >= required:
                task["status"] = "ACKED"
            task["version"] = int(task.get("version", 1)) + 1
            self.tasks[task_id] = dict(task)
            return dict(task)

    def seed_synthetic_vector(self, item: StoredVector) -> None:
        if not item.synthetic:
            raise ValueError("only SYNTHETIC vectors may be seeded in demo")
        with self._lock:
            self.vectors.append(item)

    def vector_search(self, channel: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self.vectors)
        if channel == "anonymized":
            if not items:
                raise LookupError("not_configured")
            scored = [v for v in items if v.synthetic]
            if not scored:
                raise LookupError("not_configured")
            _ = query
            return [
                {"vectorId": v.vector_id, "synthetic": True, "mode": "mock"} for v in scored[:limit]
            ]
        matches: list[dict[str, Any]] = []
        q = query.lower()
        for v in items:
            if v.resource is not None and q in v.text.lower():
                matches.append({"resource": dict(v.resource), "synthetic": v.synthetic})
        return matches[:limit]
