from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

from rakathon_backend.common.contracts import DataKind, Envelope, Health
from rakathon_backend.common.errors import AuthError, ContractError, TransportError
from rakathon_backend.common.framing import (
    encode_envelope_frame,
    frame_error,
    is_socket,
    lookup_service,
    raise_frame_error,
)
from rakathon_backend.common.health import socket_present

MAX_FRAME_BYTES = 1_048_576
DEFAULT_TIMEOUT = 5.0
Handler = Callable[[Envelope], Awaitable[Envelope]]


def _checked_reply_frame(payload: dict[str, object]) -> bytes:
    frame = encode_envelope_frame(payload)
    if len(frame) > MAX_FRAME_BYTES + 1:
        return frame_error("oversized", "response exceeds size limit")
    return frame


class UnixJsonServer:
    def __init__(
        self,
        socket_path: Path,
        *,
        service_name: str,
        token_registry: Mapping[str, str],
        handler: Handler,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        if not service_name or not service_name.strip():
            raise ValueError("service_name must be nonempty")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._socket_path = socket_path
        self._service_name = service_name
        self._registry = dict(token_registry)
        self._handler = handler
        self._timeout = timeout
        self._server: asyncio.Server | None = None
        self._owns_socket = False

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    @property
    def service_name(self) -> str:
        return self._service_name

    async def start(self) -> None:
        target = self._socket_path
        parent = target.parent
        parent.mkdir(parents=True, exist_ok=True)
        os.chmod(parent, 0o700)
        if os.path.lexists(target):
            if os.path.islink(target):
                raise TransportError(code="socket_symlink", message="socket path is a symlink")
            if not is_socket(target):
                raise TransportError(code="socket_blocked", message="socket path is not a socket")
            try:
                _reader, writer = await asyncio.wait_for(
                    asyncio.open_unix_connection(path=str(target)), timeout=self._timeout
                )
            except (OSError, TimeoutError):
                target.unlink()
            else:
                writer.close()
                try:
                    await writer.wait_closed()
                except (OSError, TimeoutError):
                    pass
                raise TransportError(code="socket_active", message="socket already in use")
        self._server = await asyncio.start_unix_server(
            self._handle_connection, path=str(target), limit=MAX_FRAME_BYTES + 4096
        )
        os.chmod(target, 0o600)
        self._owns_socket = True

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            try:
                raw = await asyncio.wait_for(reader.readline(), timeout=self._timeout)
            except TimeoutError:
                writer.write(frame_error("timeout", "request timed out"))
                await writer.drain()
                return
            except ValueError:
                writer.write(frame_error("oversized", "frame exceeds size limit"))
                await writer.drain()
                return
            if not raw:
                return
            if len(raw) > MAX_FRAME_BYTES + 1:
                writer.write(frame_error("oversized", "frame exceeds size limit"))
                await writer.drain()
                return
            if not raw.endswith(b"\n"):
                writer.write(frame_error("truncated", "frame is truncated"))
                await writer.drain()
                return
            line = raw[:-1]
            if len(line) > MAX_FRAME_BYTES:
                writer.write(frame_error("oversized", "frame exceeds size limit"))
                await writer.drain()
                return
            if not line.strip():
                writer.write(frame_error("bad_frame", "empty frame"))
                await writer.drain()
                return
            try:
                wrapper = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                writer.write(frame_error("bad_frame", "frame is not valid JSON"))
                await writer.drain()
                return
            if not isinstance(wrapper, dict):
                writer.write(frame_error("bad_frame", "request must be a JSON object"))
                await writer.drain()
                return
            service = lookup_service(self._registry, wrapper.get("token"))
            if service is None:
                writer.write(frame_error("auth_failed", "authentication failed"))
                await writer.drain()
                return
            if "envelope" not in wrapper or not isinstance(wrapper["envelope"], dict):
                writer.write(frame_error("bad_frame", "missing envelope object"))
                await writer.drain()
                return
            try:
                request = Envelope.from_dict(wrapper["envelope"])
            except ContractError as exc:
                writer.write(frame_error(exc.code, exc.message))
                await writer.drain()
                return
            if service != request.source:
                writer.write(frame_error("spoofed_source", "source does not match credentials"))
                await writer.drain()
                return
            if request.target != self._service_name:
                writer.write(frame_error("target_mismatch", "request target mismatch"))
                await writer.drain()
                return
            if request.source == "frontend:web-assistant" and request.action != "ai.complete":
                writer.write(frame_error("auth_failed", "assistant action is not permitted"))
                await writer.drain()
                return
            if request.action == "health":
                reply = request.reply(
                    source=self._service_name,
                    action="health",
                    payload={
                        "service": self._service_name,
                        "healthy": True,
                        "scope": "liveness",
                        "deps": "not_checked",
                    },
                    data_kind=DataKind.METADATA,
                )
                writer.write(_checked_reply_frame({"envelope": reply.to_dict()}))
                await writer.drain()
                return
            try:
                result = await asyncio.wait_for(self._handler(request), timeout=self._timeout)
            except TimeoutError:
                writer.write(frame_error("timeout", "handler timed out"))
                await writer.drain()
                return
            except (ContractError, AuthError, TransportError) as exc:
                writer.write(frame_error(exc.code, exc.message, exc.metadata))
                await writer.drain()
                return
            except Exception:
                writer.write(frame_error("handler_error", "handler failed"))
                await writer.drain()
                return
            if not isinstance(result, Envelope):
                writer.write(frame_error("handler_error", "handler failed"))
                await writer.drain()
                return
            if result.request_id != request.request_id:
                writer.write(frame_error("id_mismatch", "request id mismatch"))
                await writer.drain()
                return
            if result.correlation_id != request.correlation_id:
                writer.write(frame_error("id_mismatch", "correlation id mismatch"))
                await writer.drain()
                return
            if result.target != request.source:
                writer.write(frame_error("source_mismatch", "response target mismatch"))
                await writer.drain()
                return
            writer.write(_checked_reply_frame({"envelope": result.to_dict()}))
            await writer.drain()
        except (OSError, TimeoutError):
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except (OSError, TimeoutError, RuntimeError):
                pass

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._owns_socket:
            self._owns_socket = False
            try:
                if is_socket(self._socket_path):
                    self._socket_path.unlink()
            except OSError:
                pass


class UnixJsonClient:
    def __init__(
        self, socket_path: Path, *, token: str, source: str, timeout: float = DEFAULT_TIMEOUT
    ) -> None:
        if not token:
            raise ValueError("token must be nonempty")
        if not source or not source.strip():
            raise ValueError("source must be nonempty")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._socket_path = socket_path
        self._token = token
        self._source = source
        self._timeout = timeout

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    @property
    def source(self) -> str:
        return self._source

    async def call(self, envelope: Envelope, *, expect_source: str | None = None) -> Envelope:
        if envelope.source != self._source:
            raise ContractError(code="spoofed_source", message="envelope source mismatch")
        frame = (json.dumps({"token": self._token, "envelope": envelope.to_dict()}) + "\n").encode()
        if len(frame) > MAX_FRAME_BYTES + 1:
            raise TransportError(code="oversized", message="frame exceeds size limit")
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(
                    path=str(self._socket_path), limit=MAX_FRAME_BYTES + 4096
                ),
                timeout=self._timeout,
            )
        except FileNotFoundError as exc:
            raise TransportError(code="no_socket", message="socket is missing") from exc
        except (OSError, TimeoutError) as exc:
            raise TransportError(code="connect_failed", message="cannot connect") from exc
        try:
            writer.write(frame)
            await asyncio.wait_for(writer.drain(), timeout=self._timeout)
            try:
                raw = await asyncio.wait_for(reader.readline(), timeout=self._timeout)
            except TimeoutError as exc:
                raise TransportError(code="timeout", message="response timed out") from exc
            if not raw or not raw.endswith(b"\n"):
                raise TransportError(code="truncated", message="response is truncated")
            if len(raw) > MAX_FRAME_BYTES + 1:
                raise TransportError(code="oversized", message="response exceeds size limit")
            try:
                response = json.loads(raw[:-1].decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise TransportError(
                    code="bad_frame", message="response is not valid JSON"
                ) from exc
            if not isinstance(response, dict):
                raise TransportError(code="bad_frame", message="response must be a JSON object")
            if "error" in response:
                raise_frame_error(response["error"])
            if "envelope" not in response or not isinstance(response["envelope"], dict):
                raise TransportError(code="bad_frame", message="response missing envelope")
            reply = Envelope.from_dict(response["envelope"])
            if reply.request_id != envelope.request_id:
                raise TransportError(code="id_mismatch", message="request id mismatch")
            if reply.correlation_id != envelope.correlation_id:
                raise TransportError(code="id_mismatch", message="correlation id mismatch")
            if reply.target != self._source:
                raise TransportError(code="source_mismatch", message="response target mismatch")
            if expect_source is not None and reply.source != expect_source:
                raise TransportError(code="source_mismatch", message="response source mismatch")
            return reply
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except (OSError, TimeoutError, RuntimeError):
                pass

    async def ping(self, target_service: str) -> Health:
        if not socket_present(self._socket_path):
            try:
                exists = self._socket_path.exists()
            except OSError:
                exists = False
            if not exists:
                return Health.DOWN
            return Health.DEGRADED
        request = Envelope(
            request_id=f"ping-{uuid.uuid4().hex}",
            correlation_id=f"ping-{uuid.uuid4().hex}",
            source=self._source,
            target=target_service,
            action="health",
            data_kind=DataKind.METADATA,
            payload={},
        )
        try:
            reply = await self.call(request, expect_source=target_service)
        except (OSError, TimeoutError, AuthError, ContractError, TransportError):
            return Health.DEGRADED
        if reply.action != "health":
            return Health.DEGRADED
        if reply.payload.get("healthy") is True:
            return Health.HEALTHY
        return Health.DEGRADED
