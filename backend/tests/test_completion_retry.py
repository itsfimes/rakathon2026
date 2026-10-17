from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Any

import httpx
import pytest
from direct_fixtures import response
from test_direct_http import config

from rakathon_backend.b5 import completion_retry
from rakathon_backend.b5.direct import DirectAdapter
from rakathon_backend.b5.direct_http import DirectHttpTransport
from rakathon_backend.common.errors import TransportError


class Clock:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.now = 0.0
        self.wall = 1_800_000_000.0
        self.sleeps: list[float] = []
        self.on_sleep: Callable[[], None] = lambda: None
        self.yield_once = asyncio.sleep
        monkeypatch.setattr(completion_retry, "monotonic", lambda: self.now)
        monkeypatch.setattr(completion_retry, "time", lambda: self.wall + self.now)
        monkeypatch.setattr(asyncio, "sleep", self.sleep)
        monkeypatch.delenv("RAKATHON_AI_KILL_FILE", raising=False)
        monkeypatch.setenv("AI_DISABLED", "0")

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.on_sleep()
        self.now += seconds
        await self.yield_once(0)


def adapter(handler: Any, **changes: Any) -> DirectAdapter:
    return DirectAdapter(
        DirectHttpTransport(config(**changes), transport=httpx.MockTransport(handler))
    )


@pytest.mark.parametrize("kind", ["seconds", "date", "zero", "past-date"])
async def test_retry_after_then_success_releases_response_and_preserves_request(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    clock = Clock(monkeypatch)
    calls: list[httpx.Request] = []
    rejected: list[httpx.Response] = []
    delay = 0 if kind in ("zero", "past-date") else 11
    header = (
        format_datetime(
            datetime.fromtimestamp(clock.wall + (-1 if kind == "past-date" else delay), UTC),
            usegmt=True,
        )
        if kind in ("date", "past-date")
        else str(delay)
    )

    def send(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            rejected.append(
                httpx.Response(
                    429, headers={"Retry-After": header}, stream=httpx.ByteStream(b"PRIVATE")
                )
            )
            return rejected[0]
        assert clock.now >= delay and rejected[0].is_closed
        assert request.content == calls[0].content
        assert request.headers["api-key"] == "synthetic-key"
        assert request.headers["Accept-Encoding"] == "identity"
        return response("CONNECTION_OK")

    def check_closed() -> None:
        assert rejected[0].is_closed

    clock.on_sleep = check_closed
    client = adapter(send)
    try:
        assert await client.complete(b"Synthetic question", "text/plain") == {
            "answer": "CONNECTION_OK"
        }
        assert len(calls) == 2 and sum(clock.sleeps) == pytest.approx(delay)
    finally:
        await client.close()


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Retry-After": "bad"},
        {"Retry-After": "-1"},
        {"Retry-After": "1.5"},
        {"Retry-After": "Wed, 21 Oct 2015 07:28:00"},
        [("Retry-After", "1"), ("Retry-After", "2")],
    ],
)
async def test_missing_malformed_or_ambiguous_delay_fails_without_replay(
    monkeypatch: pytest.MonkeyPatch, headers: Any
) -> None:
    clock = Clock(monkeypatch)
    calls = 0

    def send(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers=headers, content=b"PRIVATE")

    client = adapter(send)
    try:
        with pytest.raises(TransportError) as rejected:
            await client.complete(b"Synthetic question", "text/plain")
        assert rejected.value.code == "ai_rate_limited"
        assert "PRIVATE" not in str(rejected.value)
        assert calls == 1 and clock.sleeps == []
    finally:
        await client.close()


async def test_retry_after_larger_than_remaining_budget_never_retries_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock(monkeypatch)
    calls = 0

    def send(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        clock.now += 2
        return httpx.Response(429, headers={"Retry-After": "11"})

    client = adapter(send, timeout_seconds=12)
    try:
        with pytest.raises(TransportError) as rejected:
            await client.complete(b"Synthetic question", "text/plain")
        assert rejected.value.code == "ai_rate_limited" and calls == 1 and not clock.sleeps
    finally:
        await client.close()


async def test_three_attempts_maximum(monkeypatch: pytest.MonkeyPatch) -> None:
    Clock(monkeypatch)
    calls = 0

    def send(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "0"})

    client = adapter(send)
    try:
        with pytest.raises(TransportError) as rejected:
            await client.complete(b"Synthetic question", "text/plain")
        assert rejected.value.code == "ai_rate_limited" and calls == 3
    finally:
        await client.close()


async def test_deadline_is_shared_by_requests_and_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock(monkeypatch)
    calls = 0

    def send(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        clock.now += 2
        return httpx.Response(429, headers={"Retry-After": "2"})

    client = adapter(send, timeout_seconds=5)
    try:
        with pytest.raises(TransportError) as rejected:
            await client.complete(b"Synthetic question", "text/plain")
        assert rejected.value.code == "ai_timeout" and calls == 2
        assert sum(clock.sleeps) == pytest.approx(2)
    finally:
        await client.close()


@pytest.mark.parametrize("status", [400, 401, 403, 500, 302])
async def test_non_429_never_retries(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    clock = Clock(monkeypatch)
    calls = 0

    def send(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, headers={"Retry-After": "0"})

    client = adapter(send)
    try:
        with pytest.raises(TransportError) as rejected:
            await client.complete(b"Synthetic question", "text/plain")
        assert rejected.value.code == "ai_http_error" and calls == 1 and not clock.sleeps
    finally:
        await client.close()


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadTimeout])
async def test_ambiguous_network_failures_never_replay(
    monkeypatch: pytest.MonkeyPatch, failure: type[httpx.RequestError]
) -> None:
    Clock(monkeypatch)
    calls = 0

    def send(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise failure("PRIVATE", request=request)

    client = adapter(send)
    try:
        with pytest.raises(TransportError) as rejected:
            await client.complete(b"Synthetic question", "text/plain")
        assert rejected.value.code in ("ai_timeout", "ai_transport_error") and calls == 1
        assert "PRIVATE" not in str(rejected.value)
    finally:
        await client.close()


async def test_cancellation_during_wait_stops_further_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Clock(monkeypatch)
    waiting = asyncio.Event()
    calls = 0

    async def wait(seconds: float) -> None:
        waiting.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(asyncio, "sleep", wait)

    def send(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "11"})

    client = adapter(send)
    task = asyncio.create_task(client.complete(b"Synthetic question", "text/plain"))
    try:
        await waiting.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert calls == 1
    finally:
        await client.close()


async def test_operator_kill_during_wait_stops_further_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock(monkeypatch)
    calls = 0
    clock.on_sleep = lambda: monkeypatch.setenv("AI_DISABLED", "1")

    def send(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "11"})

    client = adapter(send)
    try:
        with pytest.raises(TransportError) as killed:
            await client.complete(b"Synthetic question", "text/plain")
        assert killed.value.code == "killed" and calls == 1
    finally:
        await client.close()


async def test_translation_does_not_opt_into_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock(monkeypatch)
    calls = 0

    def send(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "0"})

    client = adapter(send)
    try:
        with pytest.raises(TransportError) as rejected:
            await client.translate(b"Synthetic source", "text/plain")
        assert rejected.value.code == "ai_http_error" and calls == 1 and not clock.sleeps
    finally:
        await client.close()
