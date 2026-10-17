from __future__ import annotations

import asyncio
from typing import Any

import pytest

from rakathon_backend.b5.gateway import B5Gateway, KillSwitch, MockAdapter
from rakathon_backend.common.blob_store import BlobStore
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import AuthError, TransportError


async def _ok_auth(*, user_id: str, action: str, correlation_id: str) -> bool:
    _ = (user_id, action, correlation_id)
    return action in ("ai.translate", "ai.complete")


def _req(user: str, action: str, payload: dict[str, Any], source: str = "b1") -> Envelope:
    return Envelope(
        request_id="r-1",
        correlation_id="c-1",
        source=source,
        target="b5",
        action=action,
        data_kind=DataKind.PROPRIETARY,
        payload=payload,
        user_id=user,
    )


async def test_mock_translate_labels_mock() -> None:
    blob = BlobStore()
    ref = blob.put(
        b'{"patient": {"id": "p1", "name": "N"}, "referralReason": "r"}', "application/json"
    )
    gateway = B5Gateway(blob, MockAdapter(), _ok_auth, KillSwitch(), "mock")
    reply = await gateway.handle(_req("coordinator", "ai.translate", {"bytesRef": ref}))
    assert reply.payload["mode"] == "mock"
    assert reply.payload["bundle"]["resourceType"] == "Bundle"


async def test_remote_disabled_by_default() -> None:
    blob = BlobStore()
    gateway = B5Gateway(blob, MockAdapter(), _ok_auth, KillSwitch(), "remote")
    ref = blob.put(b"hi", "text/plain")
    _ = ref
    with pytest.raises(TransportError):
        await gateway.handle(_req("coordinator", "ai.translate", {"bytesRef": ref}))


async def test_kill_disables_mock_when_tripped() -> None:
    blob = BlobStore()
    blob.put(b"hi", "text/plain")
    gateway = B5Gateway(blob, MockAdapter(), _ok_auth, KillSwitch(), "mock")
    await gateway.trip()
    with pytest.raises(TransportError):
        await gateway.handle(_req("coordinator", "ai.complete", {"prompt": "hi"}, source="b4"))


async def test_inflight_cancel_no_fallback() -> None:
    blob = BlobStore()
    ref = blob.put(b"hi", "text/plain")
    gateway = B5Gateway(blob, MockAdapter(delay=5.0), _ok_auth, KillSwitch(), "mock")
    task = asyncio.create_task(
        gateway.handle(_req("coordinator", "ai.translate", {"bytesRef": ref}))
    )
    await asyncio.sleep(0.05)
    await gateway.trip()
    with pytest.raises((TransportError, asyncio.CancelledError)):
        await task


async def test_unknown_caller_rejected() -> None:
    blob = BlobStore()
    gateway = B5Gateway(blob, MockAdapter(), _ok_auth, KillSwitch(), "mock")
    with pytest.raises(AuthError):
        await gateway.handle(_req("coordinator", "ai.translate", {"bytesRef": "x"}, source="b9"))


class _RecordingAdapter:
    def __init__(self, delay: float = 0.0, mode: str = "direct") -> None:
        self._delay = delay
        self._mode = mode
        self.closed = False
        self.cancelled = False
        self.calls = 0

    async def translate(self, data: bytes, content_type: str) -> dict[str, Any]:
        _ = (data, content_type)
        return await self._answer()

    async def complete(self, data: bytes, content_type: str) -> dict[str, Any]:
        _ = (data, content_type)
        return await self._answer()

    async def _answer(self) -> dict[str, Any]:
        self.calls += 1
        try:
            if self._delay:
                await asyncio.sleep(self._delay)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return {"answer": "x", "mode": self._mode}

    async def close(self) -> None:
        self.closed = True


async def test_complete_uses_bytes_ref_when_prompt_empty() -> None:
    blob = BlobStore()
    ref = blob.put(b"hello-ref", "text/plain")
    adapter = _RecordingAdapter()
    gateway = B5Gateway(blob, adapter, _ok_auth, KillSwitch(allow_remote=True), "direct")
    reply = await gateway.handle(
        _req("coordinator", "ai.complete", {"prompt": "", "bytesRef": ref}, source="b4")
    )
    assert reply.payload["mode"] == "direct"
    assert adapter.calls == 1


async def test_complete_uses_bytes_ref_when_prompt_missing() -> None:
    blob = BlobStore()
    ref = blob.put(b"hello-ref", "text/plain")
    adapter = _RecordingAdapter()
    gateway = B5Gateway(blob, adapter, _ok_auth, KillSwitch(allow_remote=True), "direct")
    reply = await gateway.handle(_req("coordinator", "ai.complete", {"bytesRef": ref}, source="b4"))
    assert reply.payload["mode"] == "direct"
    assert adapter.calls == 1


async def test_complete_prefers_prompt_over_bytes_ref() -> None:
    blob = BlobStore()
    ref = blob.put(b"hello-ref", "text/plain")
    adapter = _RecordingAdapter()
    gateway = B5Gateway(blob, adapter, _ok_auth, KillSwitch(), "mock")
    reply = await gateway.handle(
        _req("coordinator", "ai.complete", {"prompt": "hi", "bytesRef": ref}, source="b4")
    )
    assert reply.payload["mode"] == "mock"
    assert adapter.calls == 1


async def test_mode_label_uses_gateway_mode() -> None:
    blob = BlobStore()
    ref = blob.put(b"hi", "text/plain")
    gateway = B5Gateway(blob, _RecordingAdapter(mode="bridge"), _ok_auth, KillSwitch(), "mock")
    reply = await gateway.handle(_req("coordinator", "ai.translate", {"bytesRef": ref}))
    assert reply.payload["mode"] == "mock"


async def test_gateway_timeout_cancels_without_orphan() -> None:
    blob = BlobStore()
    ref = blob.put(b"hi", "text/plain")
    adapter = _RecordingAdapter(delay=30.0)
    gateway = B5Gateway(blob, adapter, _ok_auth, KillSwitch(), "mock", timeout=0.05)
    with pytest.raises(TransportError, match="timed out"):
        await gateway.handle(_req("coordinator", "ai.translate", {"bytesRef": ref}))
    assert adapter.cancelled is True
    assert len(gateway._active) == 0


async def test_caller_cancel_cancels_underlying_without_orphan() -> None:
    blob = BlobStore()
    ref = blob.put(b"hi", "text/plain")
    adapter = _RecordingAdapter(delay=30.0)
    gateway = B5Gateway(blob, adapter, _ok_auth, KillSwitch(), "mock", timeout=30.0)
    task = asyncio.create_task(
        gateway.handle(_req("coordinator", "ai.translate", {"bytesRef": ref}))
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises((TransportError, asyncio.CancelledError)):
        await task
    assert adapter.cancelled is True
    assert len(gateway._active) == 0


async def test_trip_closes_adapter() -> None:
    blob = BlobStore()
    adapter = _RecordingAdapter()
    gateway = B5Gateway(blob, adapter, _ok_auth, KillSwitch(), "mock")
    await gateway.trip()
    assert adapter.closed is True
    assert gateway.switch.tripped is True


async def test_close_closes_adapter_without_trip() -> None:
    blob = BlobStore()
    adapter = _RecordingAdapter()
    gateway = B5Gateway(blob, adapter, _ok_auth, KillSwitch(), "mock")
    await gateway.close()
    assert adapter.closed is True
    assert gateway.switch.tripped is False
