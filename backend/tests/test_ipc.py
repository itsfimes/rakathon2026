from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import stat
import tempfile
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from rakathon_backend.b6.permissions import load_matrix, make_authorize_handler
from rakathon_backend.common.contracts import DataKind, Envelope, Health
from rakathon_backend.common.errors import AuthError, TransportError
from rakathon_backend.common.ipc import MAX_FRAME_BYTES, UnixJsonClient, UnixJsonServer

Handler = Callable[[Envelope], Awaitable[Envelope]]


def _sock_path() -> Path:
    base = Path(tempfile.mkdtemp(prefix="raks", dir="/tmp/opencode"))
    return base / "t.sock"


async def _echo(request: Envelope) -> Envelope:
    return request.reply(
        source="b6", action="pong", payload={"ok": True}, data_kind=DataKind.METADATA
    )


def _request(source: str = "b4", target: str = "b6", action: str = "ping-x") -> Envelope:
    tag = uuid.uuid4().hex
    return Envelope(
        request_id=f"r-{tag}",
        correlation_id=f"c-{tag}",
        source=source,
        target=target,
        action=action,
        data_kind=DataKind.METADATA,
        payload={},
    )


@asynccontextmanager
async def _serve(
    path: Path, handler: Handler, registry: dict[str, str], name: str = "b6"
) -> AsyncIterator[UnixJsonServer]:
    server = UnixJsonServer(
        path, service_name=name, token_registry=registry, handler=handler, timeout=3.0
    )
    await server.start()
    try:
        yield server
    finally:
        await server.close()


async def _raw_exchange(path: Path, payload: bytes) -> dict[str, Any]:
    reader, writer = await asyncio.open_unix_connection(path=str(path))
    try:
        writer.write(payload)
        await writer.drain()
        raw = await asyncio.wait_for(reader.readline(), timeout=3.0)
    finally:
        writer.close()
    assert raw.endswith(b"\n")
    parsed: dict[str, Any] = json.loads(raw[:-1].decode())
    return parsed


async def test_roundtrip_and_modes() -> None:
    path = _sock_path()
    try:
        async with _serve(path, _echo, {"tok-b4": "b4"}):
            client = UnixJsonClient(path, token="tok-b4", source="b4", timeout=3.0)
            reply = await client.call(_request(), expect_source="b6")
            assert reply.action == "pong"
            assert reply.source == "b6"
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)


async def test_socket_mode_0600_while_serving() -> None:
    path = _sock_path()
    try:
        async with _serve(path, _echo, {"tok-b4": "b4"}):
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)


async def test_wrong_token_rejected() -> None:
    path = _sock_path()
    try:
        async with _serve(path, _echo, {"tok-b4": "b4"}):
            client = UnixJsonClient(path, token="wrong-token", source="b4", timeout=3.0)
            with pytest.raises(AuthError):
                await client.call(_request(), expect_source="b6")
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)


async def test_source_spoof_rejected() -> None:
    path = _sock_path()
    try:
        async with _serve(path, _echo, {"tok-b4": "b4"}):
            client = UnixJsonClient(path, token="tok-b4", source="b5", timeout=3.0)
            with pytest.raises(AuthError):
                await client.call(_request(source="b5"), expect_source="b6")
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)


async def test_truncated_frame_rejected() -> None:
    path = _sock_path()
    try:
        async with _serve(path, _echo, {"tok-b4": "b4"}):

            def exchange() -> bytes:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    sock.settimeout(5.0)
                    sock.connect(str(path))
                    sock.sendall(b'{"token": "tok-b4"')
                    sock.shutdown(socket.SHUT_WR)
                    chunks = b""
                    while not chunks.endswith(b"\n"):
                        part = sock.recv(4096)
                        if not part:
                            break
                        chunks += part
                    return chunks
                finally:
                    sock.close()

            chunks = await asyncio.to_thread(exchange)
            assert chunks.endswith(b"\n")
            response = json.loads(chunks[:-1].decode())
            assert response["error"]["code"] == "truncated"
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)


async def test_malformed_frame_rejected() -> None:
    path = _sock_path()
    try:
        async with _serve(path, _echo, {"tok-b4": "b4"}):
            response = await _raw_exchange(path, b"not-json\n")
            assert response["error"]["code"] == "bad_frame"
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)


async def test_oversized_frame_rejected() -> None:
    path = _sock_path()
    try:
        async with _serve(path, _echo, {"tok-b4": "b4"}):
            response = await _raw_exchange(path, b"x" * (MAX_FRAME_BYTES + 2) + b"\n")
            assert response["error"]["code"] == "oversized"
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)


async def test_ids_mismatch_rejected() -> None:
    async def bad_ids(request: Envelope) -> Envelope:
        return Envelope(
            request_id="other",
            correlation_id=request.correlation_id,
            source="b6",
            target=request.source,
            action="pong",
            data_kind=DataKind.METADATA,
            payload={},
        )

    path = _sock_path()
    try:
        async with _serve(path, bad_ids, {"tok-b4": "b4"}):
            client = UnixJsonClient(path, token="tok-b4", source="b4", timeout=3.0)
            with pytest.raises(TransportError):
                await client.call(_request(), expect_source="b6")
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)


async def test_health_healthy_and_missing() -> None:
    path = _sock_path()
    try:
        async with _serve(path, _echo, {"tok-b4": "b4"}):
            client = UnixJsonClient(path, token="tok-b4", source="b4", timeout=3.0)
            assert await client.ping("b6") == Health.HEALTHY
        gone = path.parent / "gone.sock"
        client = UnixJsonClient(gone, token="tok-b4", source="b4", timeout=1.0)
        assert await client.ping("b6") == Health.DOWN
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)


async def test_non_socket_path_preserved() -> None:
    path = _sock_path()
    path.write_text("busy", encoding="utf-8")
    server = UnixJsonServer(
        path, service_name="b6", token_registry={"tok-b4": "b4"}, handler=_echo, timeout=1.0
    )
    try:
        with pytest.raises(TransportError):
            await server.start()
        assert path.read_text(encoding="utf-8") == "busy"
    finally:
        await server.close()
        shutil.rmtree(path.parent, ignore_errors=True)


async def test_close_cleans_up_socket() -> None:
    path = _sock_path()
    server = UnixJsonServer(
        path, service_name="b6", token_registry={"tok-b4": "b4"}, handler=_echo, timeout=3.0
    )
    try:
        await server.start()
        assert path.exists()
        await server.close()
        assert not os.path.lexists(path)
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)


async def test_b6_unknown_permission_denied_over_ipc() -> None:
    policy = load_matrix()
    handler = make_authorize_handler(policy, service_name="b6", allowed_sources=frozenset({"b4"}))
    path = _sock_path()
    try:
        async with _serve(path, handler, {"tok-b4": "b4"}):
            client = UnixJsonClient(path, token="tok-b4", source="b4", timeout=3.0)
            tag = uuid.uuid4().hex
            request = Envelope(
                request_id=f"r-{tag}",
                correlation_id=f"c-{tag}",
                source="b4",
                target="b6",
                action="authorize",
                data_kind=DataKind.METADATA,
                payload={"userId": "ghost", "action": "tasks.read"},
                user_id="ghost",
            )
            reply = await client.call(request, expect_source="b6")
            assert reply.payload["allowed"] is False
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)
