from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from rakathon_backend.b2.ports import Storage
from rakathon_backend.b2.screening import endpoint as screening_endpoint
from rakathon_backend.b2.screening.ports import ScreeningPort
from rakathon_backend.b2.validation import (
    TASK_STATUSES,
    is_ack_member,
    normalize_task_state,
    validate_public_task_create,
)
from rakathon_backend.b6.permissions import canonical_action
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import AuthError, ContractError
from rakathon_backend.common.fhir import ALLOWED_TYPES, check_bundle, check_resource

SERVICE_NAME = "b2"
ALLOWED_CALLERS = frozenset({"b4", "b3"})
FHIR_TYPES = ALLOWED_TYPES

_ = TASK_STATUSES


class AuthCheck(Protocol):
    def __call__(self, *, user_id: str, action: str, correlation_id: str) -> Awaitable[bool]: ...


def _transaction_bundle(payload: dict[str, Any]) -> dict[str, Any] | None:
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


def _collect_plain_resources(payload: dict[str, Any]) -> list[dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    if payload.get("resourceType") == "Bundle":
        if payload.get("type") == "transaction":
            raise ContractError(code="bad_payload", message="use transaction path")
        for entry in payload.get("entry", []):
            if isinstance(entry, dict) and isinstance(entry.get("resource"), dict):
                resources.append(entry["resource"])
        if not resources:
            raise ContractError(code="bad_payload", message="Bundle has no resources")
        return resources
    if "resourceType" in payload:
        return [payload]
    inner = payload.get("bundle")
    if isinstance(inner, dict):
        if inner.get("resourceType") == "Bundle" and inner.get("type") != "transaction":
            for entry in inner.get("entry", []):
                if isinstance(entry, dict) and isinstance(entry.get("resource"), dict):
                    resources.append(entry["resource"])
            if not resources:
                raise ContractError(code="bad_payload", message="Bundle has no resources")
            return resources
        if "resourceType" in inner:
            return [inner]
    raise ContractError(code="bad_payload", message="fhir.write needs Bundle or resource")


def _validate_plain_resource(resource: Any) -> tuple[str, str]:
    return check_resource(resource)


def validate_task_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return normalize_task_state(payload)


class B2Service:
    def __init__(
        self,
        store: Storage,
        auth_check: AuthCheck,
        mode: str = "mock",
        privileged_users: frozenset[str] | None = None,
        screening: ScreeningPort | None = None,
    ) -> None:
        self._store = store
        self._auth = auth_check
        self._mode = mode
        self._privileged = frozenset(privileged_users) if privileged_users else frozenset()
        self._screening = screening

    async def handle(self, request: Envelope) -> Envelope:
        if request.target != SERVICE_NAME:
            raise ContractError(code="target_mismatch", message="request target mismatch")
        if request.source not in ALLOWED_CALLERS:
            raise AuthError(code="auth_failed", message="caller is not permitted")
        user_id = request.user_id
        if not user_id or not user_id.strip():
            raise ContractError(code="bad_payload", message="userId is required")
        action = request.action
        allowed_action = canonical_action(action)
        if action not in (
            "fhir.read",
            "fhir.search",
            "fhir.write",
            "screening.query",
            "tasks.read",
            "tasks.write",
            "tasks.ack",
            "vector.anonymized.search",
            "vector.patient.search",
        ):
            raise ContractError(code="bad_action", message="unsupported action")
        if not await self._auth(
            user_id=user_id, action=allowed_action, correlation_id=request.correlation_id
        ):
            raise AuthError(code="auth_failed", message=f"{action} is not permitted")
        if action in ("fhir.read", "fhir.search"):
            return await self._fhir_read(request)
        if action == "screening.query":
            return await self._screening_query(request)
        if action == "fhir.write":
            return await self._fhir_write(request)
        if action == "tasks.read":
            return await self._tasks_read(request)
        if action == "tasks.write":
            return await self._tasks_write(request)
        if action == "tasks.ack":
            return await self._tasks_ack(request)
        return await self._vector(request)

    async def _fhir_read(self, request: Envelope) -> Envelope:
        payload = request.payload
        rtype = payload.get("resourceType")
        if not isinstance(rtype, str) or rtype not in FHIR_TYPES:
            raise ContractError(code="bad_payload", message="resourceType invalid")
        rid = payload.get("id")
        server_total: int | None = None
        total = 0
        if rid is not None:
            if not isinstance(rid, str) or not rid.strip():
                raise ContractError(code="bad_payload", message="id invalid")
            found = await asyncio.to_thread(self._store.fhir_read, rtype, rid.strip())
            items = [found] if found is not None else []
            total = len(items)
        else:
            params: dict[str, str] = {}
            for key, value in payload.items():
                if key in ("resourceType", "id"):
                    continue
                if not isinstance(value, str):
                    raise ContractError(code="bad_payload", message="search param invalid")
                params[key] = value
            total_fn = getattr(self._store, "fhir_search_with_total", None)
            if callable(total_fn):
                items, server_total = await asyncio.to_thread(total_fn, rtype, params)
            else:
                items = await asyncio.to_thread(self._store.fhir_search, rtype, params)
            if params.get("_summary") == "count" and server_total is not None:
                total = server_total
            else:
                total = len(items)
        bundle: dict[str, Any] = {
            "resourceType": "Bundle",
            "type": "searchset",
            "total": total,
            "entry": [{"resource": item} for item in items],
        }
        reply_payload: dict[str, Any] = {"bundle": bundle, "mode": self._mode}
        if server_total is not None:
            reply_payload["serverTotal"] = server_total
        return request.reply(
            source=SERVICE_NAME,
            action=request.action,
            payload=reply_payload,
            data_kind=DataKind.FHIR,
        )

    async def _screening_query(self, request: Envelope) -> Envelope:
        return await screening_endpoint.handle_query(self._screening, self._mode, request)

    async def _fhir_write(self, request: Envelope) -> Envelope:
        if request.data_kind == DataKind.METADATA:
            raise ContractError(code="misclassified", message="fhir.write needs fhir kind")
        payload = request.payload
        tx = _transaction_bundle(payload)
        if tx is not None:
            check_bundle(dict(tx))
            response = await asyncio.to_thread(self._store.fhir_transaction, dict(tx))
            entries = response.get("entry", [])
            stored_ids: list[str] = []
            if isinstance(entries, list):
                for item in entries:
                    if isinstance(item, dict):
                        resp = item.get("response", {})
                        loc = resp.get("location") if isinstance(resp, dict) else None
                        if isinstance(loc, str) and loc:
                            stored_ids.append(loc)
            return request.reply(
                source=SERVICE_NAME,
                action="fhir.write",
                payload={
                    "bundle": response,
                    "stored": stored_ids,
                    "count": len(stored_ids),
                    "mode": self._mode,
                },
                data_kind=DataKind.FHIR,
            )
        resources = _collect_plain_resources(payload)
        for resource in resources:
            _validate_plain_resource(resource)
        stored_ids = []
        for resource in resources:
            stored = await asyncio.to_thread(self._store.fhir_write, dict(resource))
            stored_ids.append(f"{stored.get('resourceType')}/{stored.get('id')}")
        return request.reply(
            source=SERVICE_NAME,
            action="fhir.write",
            payload={"stored": stored_ids, "count": len(stored_ids), "mode": self._mode},
            data_kind=DataKind.FHIR,
        )

    async def _tasks_read(self, request: Envelope) -> Envelope:
        user_id = str(request.user_id or "")
        task_id = request.payload.get("id")
        if task_id is not None and (not isinstance(task_id, str) or not task_id.strip()):
            raise ContractError(code="bad_payload", message="task id invalid")
        needle = task_id.strip() if isinstance(task_id, str) else None
        items = await asyncio.to_thread(self._store.tasks_read, needle)
        if user_id in self._privileged:
            visible = list(items)
        else:
            visible = [t for t in items if self._visible_to(t, user_id)]
        summaries = [{"id": t["id"], "status": t.get("status")} for t in visible]
        return request.reply(
            source=SERVICE_NAME,
            action="tasks.read",
            payload={"tasks": visible, "summaries": summaries, "count": len(visible)},
            data_kind=DataKind.PROPRIETARY,
        )

    def _visible_to(self, task: dict[str, Any], user_id: str) -> bool:
        if not user_id:
            return False
        if task.get("ownerId") == user_id:
            return True
        required = task.get("requiredAckUserIds", [])
        return isinstance(required, list) and user_id in required

    async def _tasks_write(self, request: Envelope) -> Envelope:
        task = validate_public_task_create(dict(request.payload))
        stored = await asyncio.to_thread(self._store.tasks_create, task)
        return request.reply(
            source=SERVICE_NAME,
            action="tasks.write",
            payload={
                "task": {"id": stored["id"], "status": stored["status"]},
                "count": 1,
                "mode": self._mode,
            },
            data_kind=DataKind.PROPRIETARY,
        )

    async def _tasks_ack(self, request: Envelope) -> Envelope:
        task_id = request.payload.get("id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ContractError(code="bad_payload", message="task id is required")
        user_id = request.user_id or ""
        supplied = request.payload.get("ackUser")
        if isinstance(supplied, str) and supplied.strip() and supplied.strip() != user_id:
            raise AuthError(code="auth_failed", message="ack identity mismatch")
        items = await asyncio.to_thread(self._store.tasks_read, task_id.strip())
        if not items:
            raise ContractError(code="not_found", message="task not found")
        if not is_ack_member(items[0], user_id):
            raise AuthError(code="auth_failed", message="user is not a task member")
        try:
            updated = await asyncio.to_thread(self._store.tasks_ack, task_id.strip(), user_id)
        except KeyError as exc:
            raise ContractError(code="not_found", message="task not found") from exc
        return request.reply(
            source=SERVICE_NAME,
            action="tasks.ack",
            payload={
                "task": {"id": updated["id"], "status": updated["status"]},
                "mode": self._mode,
            },
            data_kind=DataKind.PROPRIETARY,
        )

    async def _vector(self, request: Envelope) -> Envelope:
        action = request.action
        query = request.payload.get("query", "")
        if not isinstance(query, str):
            raise ContractError(code="bad_payload", message="query must be a string")
        limit = request.payload.get("limit", 5)
        if not isinstance(limit, int) or limit <= 0 or limit > 50:
            raise ContractError(code="bad_payload", message="limit invalid")
        if action == "vector.anonymized.search":
            try:
                hits = await asyncio.to_thread(
                    self._store.vector_search, "anonymized", query, limit
                )
            except LookupError as exc:
                raise ContractError(code="not_configured", message="vector not configured") from exc
            return request.reply(
                source=SERVICE_NAME,
                action=action,
                payload={"hits": hits, "count": len(hits), "mode": self._mode},
                data_kind=DataKind.PROPRIETARY,
            )
        try:
            hits = await asyncio.to_thread(self._store.vector_search, "patient", query, limit)
        except LookupError as exc:
            raise ContractError(code="not_configured", message="vector not configured") from exc
        resources = [h["resource"] for h in hits if isinstance(h, dict) and "resource" in h]
        bundle: dict[str, Any] = {
            "resourceType": "Bundle",
            "type": "searchset",
            "total": len(resources),
            "entry": [{"resource": r} for r in resources],
        }
        return request.reply(
            source=SERVICE_NAME,
            action=action,
            payload={"bundle": bundle, "count": len(resources), "mode": self._mode},
            data_kind=DataKind.FHIR,
        )


def make_handler(service: B2Service) -> Callable[[Envelope], Awaitable[Envelope]]:
    async def handler(request: Envelope) -> Envelope:
        return await service.handle(request)

    return handler
