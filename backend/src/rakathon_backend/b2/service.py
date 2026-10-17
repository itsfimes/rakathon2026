from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from rakathon_backend.b2.collection import bounded_reply, collection_payload, read_collection
from rakathon_backend.b2.ingestion import import_context_present, persist_import
from rakathon_backend.b2.ports import Storage
from rakathon_backend.b2.screening import endpoint as screening_endpoint
from rakathon_backend.b2.screening.ports import ScreeningPort
from rakathon_backend.b2.validation import (
    TASK_STATUSES,
    is_ack_member,
    normalize_task_state,
    validate_public_task_create,
)
from rakathon_backend.b2.write_guards import (
    collect_plain_resources,
    transaction_bundle,
    validate_plain_resource,
)
from rakathon_backend.b6.permissions import canonical_action
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import AuthError, ContractError, TransportError
from rakathon_backend.common.fhir import ALLOWED_TYPES, check_bundle

SERVICE_NAME = "b2"
ALLOWED_CALLERS = frozenset({"b4", "b3"})
FHIR_TYPES = ALLOWED_TYPES

_ = TASK_STATUSES


class AuthCheck(Protocol):
    def __call__(self, *, user_id: str, action: str, correlation_id: str) -> Awaitable[bool]: ...


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
        is_privileged: Callable[[str], bool] | None = None,
    ) -> None:
        self._store = store
        self._auth = auth_check
        self._mode = mode
        self._privileged = frozenset(privileged_users) if privileged_users else frozenset()
        self._screening = screening
        self._is_privileged = is_privileged

    def _privileged_for(self, user_id: str) -> bool:
        if self._is_privileged is None:
            return user_id in self._privileged
        try:
            return bool(self._is_privileged(user_id))
        except (AuthError, ContractError, TransportError, OSError, ValueError, KeyError):
            return False

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
        metadata: dict[str, Any] = {}
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
                (items, server_total), metadata = await read_collection(total_fn, rtype, params)
            else:
                items, metadata = await read_collection(self._store.fhir_search, rtype, params)
            if params.get("_summary") == "count" and server_total is not None:
                total = server_total
            else:
                total = len(items)
        reply_payload = collection_payload(items, total, self._mode)
        if metadata:
            reply_payload["collection"] = metadata
        if server_total is not None:
            reply_payload["serverTotal"] = server_total
        return bounded_reply(
            request.reply(
                source=SERVICE_NAME,
                action=request.action,
                payload=reply_payload,
                data_kind=DataKind.FHIR,
            ),
            len(items),
            metadata,
        )

    async def _screening_query(self, request: Envelope) -> Envelope:
        return await screening_endpoint.handle_query(self._screening, self._mode, request)

    async def _fhir_write(self, request: Envelope) -> Envelope:
        if request.data_kind == DataKind.METADATA:
            raise ContractError(code="misclassified", message="fhir.write needs fhir kind")
        payload = request.payload
        tx = transaction_bundle(payload)
        if tx is not None:
            imported = import_context_present(tx, payload)
            check_bundle(dict(tx))
            if imported:
                response = await asyncio.to_thread(
                    persist_import, self._store, dict(tx), payload["ingestion"], self._mode
                )
            else:
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
            if "ingestion" in payload:
                stored_ids = [entry["request"]["url"] for entry in tx["entry"]]
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
        if "ingestion" in payload:
            raise ContractError(
                code="bad_payload", message="Ingestion requires an atomic transaction"
            )
        resources = collect_plain_resources(payload)
        for resource in resources:
            validate_plain_resource(resource)
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
        if self._privileged_for(user_id):
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
