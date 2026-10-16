from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from rakathon_backend.b5.mock import mock_complete_bytes, mock_translate_bytes
from rakathon_backend.common.blob_store import BlobStore
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import AuthError, ContractError, TransportError

SERVICE_NAME = "b5"
ALLOWED_CALLERS = frozenset({"b1", "b4"})
DEFAULT_TIMEOUT = 60.0


class AuthCheck(Protocol):
    def __call__(self, *, user_id: str, action: str, correlation_id: str) -> Awaitable[bool]: ...


class AIAdapter(Protocol):
    async def translate(self, data: bytes, content_type: str) -> dict[str, Any]: ...
    async def complete(self, data: bytes, content_type: str) -> dict[str, Any]: ...
    async def close(self) -> None: ...


class MockAdapter:
    def __init__(self, delay: float = 0.0) -> None:
        self._delay = delay
        self.closed = False

    async def translate(self, data: bytes, content_type: str) -> dict[str, Any]:
        if self._delay:
            await asyncio.sleep(self._delay)
        return mock_translate_bytes(data, content_type)

    async def complete(self, data: bytes, content_type: str) -> dict[str, Any]:
        if self._delay:
            await asyncio.sleep(self._delay)
        return mock_complete_bytes(data, content_type)

    async def close(self) -> None:
        self.closed = True


class KillSwitch:
    def __init__(self, *, allow_remote: bool = False) -> None:
        self._tripped = False
        self._allow_remote = allow_remote
        self._lock = asyncio.Lock()

    @property
    def tripped(self) -> bool:
        return self._tripped

    @property
    def allow_remote(self) -> bool:
        return self._allow_remote

    async def trip(self) -> None:
        async with self._lock:
            self._tripped = True

    async def reset(self) -> None:
        async with self._lock:
            self._tripped = False

    def check(self, *, mode: str) -> None:
        if self._tripped:
            raise TransportError(code="killed", message="kill switch is tripped")
        if mode != "mock" and not self._allow_remote:
            raise TransportError(code="remote_disabled", message="remote AI is disabled")


class B5Gateway:
    def __init__(
        self,
        blob: BlobStore,
        adapter: AIAdapter,
        auth_check: AuthCheck,
        switch: KillSwitch | None = None,
        mode: str = "mock",
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        if timeout <= 0:
            raise ValueError("gateway timeout must be positive")
        self._blob = blob
        self._adapter = adapter
        self._auth = auth_check
        self._switch = switch or KillSwitch()
        self._mode = mode
        self._timeout = timeout
        self._active: set[asyncio.Task[Any]] = set()

    @property
    def switch(self) -> KillSwitch:
        return self._switch

    @property
    def mode(self) -> str:
        return self._mode

    async def trip(self) -> None:
        await self._switch.trip()
        for task in list(self._active):
            task.cancel()
        if self._active:
            await asyncio.gather(*self._active, return_exceptions=True)
        with contextlib.suppress(OSError, RuntimeError):
            await self._adapter.close()

    async def close(self) -> None:
        for task in list(self._active):
            task.cancel()
        if self._active:
            await asyncio.gather(*self._active, return_exceptions=True)
        with contextlib.suppress(OSError, RuntimeError):
            await self._adapter.close()

    async def handle(self, request: Envelope) -> Envelope:
        if request.target != SERVICE_NAME:
            raise ContractError(code="target_mismatch", message="request target mismatch")
        if request.source not in ALLOWED_CALLERS:
            raise AuthError(code="auth_failed", message="caller is not permitted")
        if request.action not in ("ai.translate", "ai.complete"):
            raise ContractError(code="bad_action", message="unsupported action")
        user_id = request.user_id
        if not user_id or not user_id.strip():
            raise ContractError(code="bad_payload", message="userId is required")
        if not await self._auth(
            user_id=user_id, action=request.action, correlation_id=request.correlation_id
        ):
            raise AuthError(code="auth_failed", message=f"{request.action} is not permitted")
        self._switch.check(mode=self._mode)
        task: asyncio.Task[dict[str, Any]] = asyncio.create_task(self._run(request))
        self._active.add(task)
        try:
            try:
                result = await asyncio.wait_for(task, self._timeout)
            except TimeoutError as exc:
                await self._finish(task)
                raise TransportError(code="timeout", message="AI call timed out") from exc
            except asyncio.CancelledError:
                await self._finish(task)
                raise TransportError(code="cancelled", message="AI call was cancelled")
        finally:
            self._active.discard(task)
        return request.reply(
            source=SERVICE_NAME,
            action=request.action,
            payload={**result, "mode": self._mode},
            data_kind=DataKind.PROPRIETARY,
        )

    async def _finish(self, task: asyncio.Task[Any]) -> None:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _run(self, request: Envelope) -> dict[str, Any]:
        payload = request.payload
        ref = payload.get("bytesRef")
        has_ref = isinstance(ref, str) and bool(ref.strip())
        if request.action == "ai.translate":
            if not has_ref:
                raise ContractError(code="bad_payload", message="bytesRef is required")
            try:
                record = self._blob.get(str(ref))
            except Exception as exc:
                raise ContractError(code="blob_not_found", message="blob unknown") from exc
            return await self._adapter.translate(record.data, record.content_type)
        prompt = payload.get("prompt", "")
        if isinstance(prompt, str) and prompt.strip():
            return await self._adapter.complete(prompt.encode(), "text/plain")
        if has_ref:
            try:
                record = self._blob.get(str(ref))
            except Exception as exc:
                raise ContractError(code="blob_not_found", message="blob unknown") from exc
            return await self._adapter.complete(record.data, record.content_type)
        raise ContractError(code="bad_payload", message="prompt or bytesRef is required")


def make_handler(gateway: B5Gateway) -> Callable[[Envelope], Awaitable[Envelope]]:
    async def handler(request: Envelope) -> Envelope:
        return await gateway.handle(request)

    return handler
