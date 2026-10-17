from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from rakathon_backend.b4.reminders import ReminderStore
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import AuthError, ContractError, TransportError
from rakathon_backend.common.kinds import request_kind
from rakathon_backend.common.review_limits import B4_REVIEW_PENDING_TIMEOUT
from rakathon_backend.common.rpc import new_envelope

SERVICE_NAME = "b4"

ROUTE_INGEST = "ingest"
ROUTE_FHIR_READ = "fhir.read"
ROUTE_FHIR_WRITE = "fhir.write"
ROUTE_DOCUMENT_APPROVE = "document.approve"
ROUTE_SCREENING = "screening.query"
ROUTE_TASKS = ("tasks.read", "tasks.write", "tasks.ack")
ROUTE_VECTOR = ("vector.anonymized.search", "vector.patient.search")
ROUTE_AI = "ai.complete"
ROUTE_TICK = "watchdog.tick"
ROUTE_REMINDERS = "reminders.read"
MAX_PENDING = 1000
AI_PENDING_TIMEOUT = 200.0

USER_ACTIONS = frozenset(
    {
        "ingest",
        "fhir.read",
        "fhir.search",
        "fhir.write",
        "document.approve",
        "screening.query",
        "tasks.read",
        "tasks.write",
        "tasks.ack",
        "vector.anonymized.search",
        "vector.patient.search",
        "ai.complete",
        "reminders.read",
        "watchdog.tick",
        "health",
    }
)


class AuthCheck(Protocol):
    def __call__(self, *, user_id: str, action: str, correlation_id: str) -> Awaitable[bool]: ...


class Downstream(Protocol):
    def __call__(self, request: Envelope) -> Awaitable[Envelope]: ...


PrivilegeCheck = Callable[[str], bool]

WEB_AUTH_SOURCE = "web:auth"


class B4Router:
    def __init__(
        self,
        auth_check: AuthCheck,
        call_b1: Downstream | None = None,
        call_b2: Downstream | None = None,
        call_b5: Downstream | None = None,
        source_users: dict[str, str] | None = None,
        pending_timeout: float = 30.0,
        ai_pending_timeout: float = AI_PENDING_TIMEOUT,
        privileged_users: frozenset[str] | None = None,
        web_sources: frozenset[str] | None = None,
        is_privileged: PrivilegeCheck | None = None,
        review_pending_timeout: float = B4_REVIEW_PENDING_TIMEOUT,
    ) -> None:
        if pending_timeout <= 0 or ai_pending_timeout <= 0 or review_pending_timeout <= 0:
            raise ValueError("pending timeouts must be positive")
        self._auth = auth_check
        self._b1 = call_b1
        self._b2 = call_b2
        self._b5 = call_b5
        self._source_users = dict(source_users or {})
        self._pending: dict[tuple[str, str], tuple[str, float, float]] = {}
        self._lock = asyncio.Lock()
        self._reminders = ReminderStore()
        self._pending_timeout = pending_timeout
        self._ai_pending_timeout = ai_pending_timeout
        self._review_pending_timeout = review_pending_timeout
        self._privileged = frozenset(privileged_users) if privileged_users else frozenset()
        self._web_sources = frozenset(web_sources) if web_sources else frozenset()
        self._is_privileged = is_privileged

    def register_source(self, source: str, user_id: str) -> None:
        self._source_users[source] = user_id

    def store_reminder(self, reminder: dict[str, Any]) -> None:
        self._reminders.store_all([reminder])

    def pending_count(self) -> int:
        return len(self._pending)

    def _privileged_for(self, user_id: str) -> bool:
        if self._is_privileged is not None:
            try:
                return bool(self._is_privileged(user_id))
            except (ContractError, AuthError, TransportError, OSError, ValueError):
                return False
            except (KeyError, RuntimeError, AttributeError, TypeError):
                return False
        return user_id in self._privileged

    def _visible_set(self, user_id: str) -> frozenset[str]:
        if self._is_privileged is not None:
            return frozenset({user_id}) if self._privileged_for(user_id) else frozenset()
        return self._privileged

    async def handle(self, request: Envelope) -> Envelope:
        if request.target != SERVICE_NAME:
            raise ContractError(code="target_mismatch", message="request target mismatch")
        if request.source.startswith("frontend:"):
            return await self._handle_frontend(request)
        if request.source in self._web_sources:
            return await self._handle_web(request)
        if request.source == "b3":
            return await self._handle_b3(request)
        if request.source in ("b1", "b2", "b5"):
            return await self._handle_reply(request)
        raise AuthError(code="auth_failed", message="unknown source")

    async def _handle_frontend(self, request: Envelope) -> Envelope:
        expected = self._source_users.get(request.source)
        if expected is None:
            raise AuthError(code="auth_failed", message="unknown frontend identity")
        claimed = request.user_id or ""
        if claimed != expected:
            raise AuthError(code="auth_failed", message="user identity mismatch")
        return await self._authorize_and_route(request, expected)

    async def _handle_web(self, request: Envelope) -> Envelope:
        user_id = request.user_id or ""
        if not user_id or not user_id.strip():
            raise AuthError(code="auth_failed", message="web identity is missing")
        return await self._authorize_and_route(request, user_id.strip())

    async def _authorize_and_route(self, request: Envelope, user_id: str) -> Envelope:
        action = request.action
        if user_id == "web-assistant" and action != ROUTE_AI:
            raise AuthError(code="auth_failed", message="assistant action is not permitted")
        if action not in USER_ACTIONS:
            raise ContractError(code="bad_action", message="unsupported action")
        if action == "health":
            return request.reply(
                source=SERVICE_NAME,
                action="health",
                payload={
                    "service": SERVICE_NAME,
                    "healthy": True,
                    "scope": "liveness",
                    "deps": "not_checked",
                },
                data_kind=DataKind.METADATA,
            )
        if action == ROUTE_REMINDERS:
            return await self._reminders_read(request, user_id)
        allowed = await self._auth(
            user_id=user_id, action=action, correlation_id=request.correlation_id
        )
        if not allowed:
            raise AuthError(code="auth_failed", message=f"{action} is not permitted")
        if action == ROUTE_TICK:
            return await self._route_tick(request, user_id)
        key = (request.source, request.request_id)
        async with self._lock:
            self._prune_locked()
            if key in self._pending:
                raise ContractError(code="duplicate_id", message="duplicate request id")
            if len(self._pending) >= MAX_PENDING:
                raise TransportError(code="temporarily_unavailable", message="too many pending")
            self._pending[key] = (user_id, time.monotonic(), self._deadline_for(action))
        try:
            routed = await self._route(request, user_id)
        finally:
            async with self._lock:
                self._pending.pop(key, None)
        return routed

    async def _handle_b3(self, request: Envelope) -> Envelope:
        if request.action == "reminders.deliver":
            items = request.payload.get("reminders", [])
            if not isinstance(items, list):
                raise ContractError(code="bad_payload", message="reminders payload invalid")
            stored = self._reminders.store_all(items)
            return request.reply(
                source=SERVICE_NAME,
                action="reminders.deliver",
                payload={"stored": stored},
                data_kind=DataKind.METADATA,
            )
        raise ContractError(code="bad_action", message="unsupported b3 action")

    async def _handle_reply(self, request: Envelope) -> Envelope:
        raise ContractError(code="bad_action", message="unexpected service ingress")

    async def _reminders_read(self, request: Envelope, user_id: str) -> Envelope:
        allowed = await self._auth(
            user_id=user_id, action="reminders.read", correlation_id=request.correlation_id
        )
        if not allowed:
            raise AuthError(code="auth_failed", message="reminders.read is not permitted")
        raw_filter = request.payload.get("ownerId")
        owner_filter = raw_filter if isinstance(raw_filter, str) else None
        items = self._reminders.visible(user_id, self._visible_set(user_id), owner_filter)
        ids = [{"taskId": r.get("taskId"), "reason": r.get("reason")} for r in items]
        return request.reply(
            source=SERVICE_NAME,
            action="reminders.read",
            payload={"count": len(items), "reminders": ids},
            data_kind=DataKind.PROPRIETARY,
        )

    async def _route(self, request: Envelope, user_id: str) -> Envelope:
        action = request.action
        if action == ROUTE_INGEST:
            if self._b1 is None:
                raise TransportError(code="no_route", message="B1 route is not configured")
            downstream = new_envelope(
                source="b4",
                target="b1",
                action="ingest",
                data_kind=DataKind.PROPRIETARY,
                payload=dict(request.payload),
                user_id=user_id,
                correlation_id=request.correlation_id,
            )
            reply = await self._with_ai_timeout(self._b1(downstream))
            return self._to_caller(request, reply)
        if action in (
            ROUTE_FHIR_READ,
            ROUTE_FHIR_WRITE,
            ROUTE_DOCUMENT_APPROVE,
            ROUTE_SCREENING,
            "fhir.search",
            *ROUTE_TASKS,
            *ROUTE_VECTOR,
        ):
            if self._b2 is None:
                raise TransportError(code="no_route", message="B2 route is not configured")
            downstream = new_envelope(
                source="b4",
                target="b2",
                action=action,
                data_kind=request_kind(action),
                payload=dict(request.payload),
                user_id=user_id,
                correlation_id=request.correlation_id,
            )
            reply = await self._with_timeout(
                self._b2(downstream), timeout=self._deadline_for(action)
            )
            return self._to_caller(request, reply)
        if action == ROUTE_AI:
            if self._b5 is None:
                raise TransportError(code="no_route", message="B5 route is not configured")
            downstream = new_envelope(
                source="b4",
                target="b5",
                action="ai.complete",
                data_kind=DataKind.PROPRIETARY,
                payload=dict(request.payload),
                user_id=user_id,
                correlation_id=request.correlation_id,
            )
            reply = await self._with_ai_timeout(self._b5(downstream))
            return self._to_caller(request, reply)
        raise ContractError(code="bad_action", message="no route for action")

    async def _route_tick(self, request: Envelope, user_id: str) -> Envelope:
        _ = user_id
        return request.reply(
            source=SERVICE_NAME,
            action="watchdog.tick",
            payload={"note": "tick is performed by watchdog service", "count": 0},
            data_kind=DataKind.METADATA,
        )

    def _deadline_for(self, action: str) -> float:
        if action == ROUTE_DOCUMENT_APPROVE:
            return self._review_pending_timeout
        return self._pending_timeout

    async def _with_timeout(
        self, awaitable: Awaitable[Envelope], *, timeout: float | None = None
    ) -> Envelope:
        try:
            return await asyncio.wait_for(
                awaitable, timeout=self._pending_timeout if timeout is None else timeout
            )
        except TimeoutError as exc:
            raise TransportError(code="timeout", message="downstream timed out") from exc

    async def _with_ai_timeout(self, awaitable: Awaitable[Envelope]) -> Envelope:
        try:
            return await asyncio.wait_for(awaitable, timeout=self._ai_pending_timeout)
        except TimeoutError as exc:
            raise TransportError(code="timeout", message="downstream timed out") from exc

    def _to_caller(self, original: Envelope, reply: Envelope) -> Envelope:
        if reply.correlation_id != original.correlation_id:
            raise TransportError(code="id_mismatch", message="correlation id mismatch")
        return Envelope(
            request_id=original.request_id,
            correlation_id=original.correlation_id,
            source=SERVICE_NAME,
            target=original.source,
            action=reply.action,
            data_kind=reply.data_kind,
            payload=dict(reply.payload),
            user_id=original.user_id,
        )

    def _prune_locked(self) -> None:
        now = time.monotonic()
        expired = [k for k, (_, ts, limit) in self._pending.items() if now - ts > limit]
        for key in expired:
            self._pending.pop(key, None)


def make_handler(router: B4Router) -> Callable[[Envelope], Awaitable[Envelope]]:
    async def handler(request: Envelope) -> Envelope:
        return await router.handle(request)

    return handler


def web_envelope(
    user_id: str, action: str, payload: dict[str, Any], data_kind: DataKind
) -> Envelope:
    for key in ("userId", "user_id", "role", "username"):
        if key in payload:
            raise ContractError(code="bad_payload", message="authority fields are rejected")
    clean = dict(payload)
    uid = user_id.strip()
    if not uid:
        raise ContractError(code="bad_payload", message="verified identity is required")
    tag = uuid.uuid4().hex
    return Envelope(
        request_id=f"web-{tag}",
        correlation_id=f"web-{tag}",
        source=WEB_AUTH_SOURCE,
        target=SERVICE_NAME,
        action=action,
        data_kind=data_kind,
        payload=clean,
        user_id=uid,
    )
