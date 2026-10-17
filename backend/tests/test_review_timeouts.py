from __future__ import annotations

import asyncio
import inspect
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

from rakathon_backend.b4.router import B4Router
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import TransportError
from rakathon_backend.common.ipc import UnixJsonClient, UnixJsonServer
from rakathon_backend.common.review_limits import (
    B2_REVIEW_ACTION_TIMEOUTS,
    B2_REVIEW_CLIENT_TIMEOUT,
    B2_REVIEW_HANDLER_TIMEOUT,
    B4_REVIEW_ACTION_TIMEOUTS,
    B4_REVIEW_HANDLER_TIMEOUT,
    B4_REVIEW_PENDING_TIMEOUT,
    REVIEW_ACTION,
    WEB_REVIEW_HTTP_TIMEOUT,
)
from rakathon_backend.runtime import application as app_module


def _sock_path() -> Path:
    base = Path(tempfile.mkdtemp(prefix="rakrev", dir="/tmp/opencode"))
    return base / "t.sock"


def _request(action: str) -> Envelope:
    tag = uuid.uuid4().hex
    return Envelope(
        request_id=f"r-{tag}",
        correlation_id=f"c-{tag}",
        source="b4",
        target="b6",
        action=action,
        data_kind=DataKind.METADATA,
        payload={},
    )


async def _delayed(request: Envelope) -> Envelope:
    if request.action == REVIEW_ACTION:
        await asyncio.sleep(0.2)
    else:
        await asyncio.sleep(0.2)
    return request.reply(
        source="b6", action=request.action, payload={"ok": True}, data_kind=DataKind.METADATA
    )


async def test_default_deadline_remains() -> None:
    path = _sock_path()
    try:
        server = UnixJsonServer(
            path,
            service_name="b6",
            token_registry={"tok": "b4"},
            handler=_delayed,
            timeout=0.05,
        )
        await server.start()
        try:
            client = UnixJsonClient(path, token="tok", source="b4", timeout=1.0)
            with pytest.raises(TransportError):
                await client.call(_request("tasks.read"), expect_source="b6")
        finally:
            await server.close()
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)


async def test_configured_approve_succeeds_longer() -> None:
    path = _sock_path()
    try:
        server = UnixJsonServer(
            path,
            service_name="b6",
            token_registry={"tok": "b4"},
            handler=_delayed,
            timeout=0.05,
            action_timeouts={REVIEW_ACTION: 0.5},
        )
        await server.start()
        try:
            client = UnixJsonClient(path, token="tok", source="b4", timeout=1.0)
            reply = await client.call(_request(REVIEW_ACTION), expect_source="b6")
            assert reply.action == REVIEW_ACTION
            with pytest.raises(TransportError):
                await client.call(_request("tasks.read"), expect_source="b6")
        finally:
            await server.close()
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)


async def test_invalid_timeout_config_fails() -> None:
    path = _sock_path()
    try:
        for bad in (0.0, -1.0, float("inf"), float("nan")):
            with pytest.raises(ValueError):
                UnixJsonServer(
                    path,
                    service_name="b6",
                    token_registry={"tok": "b4"},
                    handler=_delayed,
                    timeout=0.05,
                    action_timeouts={REVIEW_ACTION: bad},
                )
        for bad_key in ("", "  ", "has space", "bad/key", "bad;key"):
            with pytest.raises(ValueError):
                UnixJsonServer(
                    path,
                    service_name="b6",
                    token_registry={"tok": "b4"},
                    handler=_delayed,
                    timeout=0.05,
                    action_timeouts={bad_key: 1.0},
                )
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)


async def test_review_constants_and_wiring() -> None:
    assert REVIEW_ACTION == "document.approve"
    assert B2_REVIEW_HANDLER_TIMEOUT == 120.0
    assert B4_REVIEW_HANDLER_TIMEOUT == 130.0
    assert B4_REVIEW_PENDING_TIMEOUT == 125.0
    assert B2_REVIEW_CLIENT_TIMEOUT == 125.0
    assert WEB_REVIEW_HTTP_TIMEOUT == 135.0
    assert B2_REVIEW_ACTION_TIMEOUTS == {REVIEW_ACTION: 120.0}
    assert B4_REVIEW_ACTION_TIMEOUTS == {REVIEW_ACTION: 130.0}
    assert "tasks.read" not in B2_REVIEW_ACTION_TIMEOUTS
    assert "tasks.read" not in B4_REVIEW_ACTION_TIMEOUTS
    assert "ai.complete" not in B2_REVIEW_ACTION_TIMEOUTS
    sig = inspect.signature(app_module.BackendApp._add)
    assert "action_timeouts" in sig.parameters


async def test_b4_pending_deadline_context() -> None:
    async def allow(*, user_id: str, action: str, correlation_id: str) -> bool:
        _ = (user_id, correlation_id)
        return action in ("tasks.read", REVIEW_ACTION)

    async def slow(request: Envelope) -> Envelope:
        await asyncio.sleep(0.2)
        return request.reply(
            source="b2",
            action=request.action,
            payload={"ok": True},
            data_kind=DataKind.METADATA,
        )

    router = B4Router(
        allow,
        None,
        slow,
        None,
        {"frontend:clinician": "clinician"},
        pending_timeout=0.05,
        review_pending_timeout=0.5,
    )
    assert router._deadline_for(REVIEW_ACTION) == 0.5
    assert router._deadline_for("tasks.read") == 0.05

    def _front(action: str, rid: str) -> Envelope:
        return Envelope(
            request_id=rid,
            correlation_id="c-1",
            source="frontend:clinician",
            target="b4",
            action=action,
            data_kind=DataKind.METADATA,
            payload={},
            user_id="clinician",
        )

    reply = await router.handle(_front(REVIEW_ACTION, "r-ok"))
    assert reply.action == REVIEW_ACTION
    with pytest.raises(TransportError):
        await router.handle(_front("tasks.read", "r-slow"))
    assert router.pending_count() == 0
