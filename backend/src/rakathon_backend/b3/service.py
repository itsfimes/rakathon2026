from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from rakathon_backend.b3.watchdog import ReminderDeduper, compute_reminders
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import AuthError, ContractError, TransportError
from rakathon_backend.common.rpc import new_envelope

SERVICE_NAME = "b3"
WATCHDOG_USER = "watchdog"


class AuthCheck(Protocol):
    def __call__(self, *, user_id: str, action: str, correlation_id: str) -> Awaitable[bool]: ...


class B2Fetch(Protocol):
    def __call__(self, correlation_id: str) -> Awaitable[list[dict[str, Any]]]: ...


class B4Deliver(Protocol):
    def __call__(self, reminders: list[dict[str, Any]], correlation_id: str) -> Awaitable[None]: ...


class B3Service:
    def __init__(
        self,
        fetch_tasks: B2Fetch,
        deliver: B4Deliver | None,
        auth_check: AuthCheck,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._fetch = fetch_tasks
        self._deliver = deliver
        self._auth = auth_check
        self._clock = clock or (lambda: datetime.now(UTC))
        self._deduper = ReminderDeduper()
        self._loop_task: asyncio.Task[None] | None = None
        self._interval = 1.0
        self._stopped = asyncio.Event()

    async def tick(self, correlation_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        tasks = await self._fetch(correlation_id)
        now = self._clock()
        computed = compute_reminders(tasks, now)
        fresh = self._deduper.filter_new(computed)
        if fresh and self._deliver is not None:
            await self._deliver(fresh, correlation_id)
        return (fresh, computed)

    async def handle(self, request: Envelope) -> Envelope:
        if request.target != SERVICE_NAME:
            raise ContractError(code="target_mismatch", message="request target mismatch")
        if request.action != "watchdog.tick":
            raise ContractError(code="bad_action", message="unsupported action")
        user_id = request.user_id or ""
        if user_id != WATCHDOG_USER:
            raise AuthError(code="auth_failed", message="watchdog user only")
        if not await self._auth(
            user_id=user_id, action="watchdog.tick", correlation_id=request.correlation_id
        ):
            raise AuthError(code="auth_failed", message="watchdog.tick is not permitted")
        fresh, computed = await self.tick(request.correlation_id)
        _ = fresh
        return request.reply(
            source=SERVICE_NAME,
            action="watchdog.tick",
            payload={"count": len(computed), "mode": "mock"},
            data_kind=DataKind.METADATA,
        )

    async def start_loop(self, interval: float = 1.0) -> None:
        if interval <= 0 or interval > 3600:
            raise ValueError("interval out of bounds")
        if self._loop_task is not None and not self._loop_task.done():
            raise RuntimeError("loop already running")
        self._interval = interval
        self._stopped.clear()
        self._loop_task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while not self._stopped.is_set():
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self._interval)
            except TimeoutError:
                _elapsed = True
            if self._stopped.is_set():
                break
            try:
                await self.tick(f"corr-{uuid.uuid4().hex}")
            except (AuthError, ContractError, OSError, TimeoutError) as exc:
                _ = exc
                continue

    async def stop_loop(self) -> None:
        self._stopped.set()
        task = self._loop_task
        self._loop_task = None
        if task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                task.cancel()
                with contextlib.suppress(
                    asyncio.CancelledError,
                    AuthError,
                    ContractError,
                    TransportError,
                    OSError,
                ):
                    await task

    def pending_snapshot(self) -> dict[str, str]:
        return self._deduper.snapshot()


def make_handler(service: B3Service) -> Callable[[Envelope], Awaitable[Envelope]]:
    async def handler(request: Envelope) -> Envelope:
        return await service.handle(request)

    return handler


def b2_fetch_via_client(
    call: Callable[[Envelope], Awaitable[Envelope]], *, source: str = "b3"
) -> B2Fetch:
    async def fetch(correlation_id: str) -> list[dict[str, Any]]:
        request = new_envelope(
            source=source,
            target="b2",
            action="tasks.read",
            data_kind=DataKind.PROPRIETARY,
            payload={},
            user_id=WATCHDOG_USER,
            correlation_id=correlation_id,
        )
        reply = await call(request)
        if reply.correlation_id != correlation_id:
            raise ContractError(code="id_mismatch", message="correlation id mismatch")
        items = reply.payload.get("tasks", [])
        if not isinstance(items, list):
            raise ContractError(code="bad_payload", message="tasks payload invalid")
        out: list[dict[str, Any]] = [t for t in items if isinstance(t, dict)]
        return out

    return fetch


def watch_request(correlation_id: str | None = None) -> Envelope:
    return new_envelope(
        source="b3",
        target="b3",
        action="watchdog.tick",
        data_kind=DataKind.METADATA,
        payload={},
        user_id=WATCHDOG_USER,
        correlation_id=correlation_id or f"corr-{uuid.uuid4().hex}",
    )


EnvelopeForB3 = Envelope
AnyDict = dict[str, Any]
