from __future__ import annotations

import asyncio
import concurrent.futures
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from rakathon_backend.b5.direct_http import _reject_constant, _unique_object
from rakathon_backend.web.projection import ID
from rakathon_backend.web.service import UPSTREAM_FAILURES, WebError, WebService

MAX_RESPONSE = 1024 * 1024
REQUEST_TIMEOUT = 35
MAX_REQUEST = 16 * 1024


class WebServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    request_queue_size = 8

    def __init__(
        self,
        bind: str,
        port: int,
        service: WebService,
        loop: asyncio.AbstractEventLoop,
        key: str,
        origins: frozenset[str],
    ) -> None:
        if bind != "127.0.0.1" or not 0 <= port <= 65535:
            raise ValueError("literal IPv4 loopback required")
        self.service = service
        self.loop = loop
        self.key = key
        self.origins = origins
        self.slots = threading.BoundedSemaphore(8)
        super().__init__((bind, port), Handler)
        actual_port = self.server_address[1]
        self.hosts = frozenset({f"127.0.0.1:{actual_port}", f"localhost:{actual_port}"})

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request: Any, client_address: Any) -> None:
        pass


class Handler(BaseHTTPRequestHandler):
    server: WebServer
    raw_requestline: bytes
    server_version = "RakathonDev"
    sys_version = ""

    def setup(self) -> None:
        self.request.settimeout(5)
        super().setup()

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        self._reply(
            code, {"version": 1, "error": {"code": "bad_request", "message": "Request rejected"}}
        )

    def _reply(self, status: int, body: dict[str, Any]) -> None:
        raw = json.dumps(body, ensure_ascii=True, allow_nan=False).encode("utf-8")
        if len(raw) > MAX_RESPONSE:
            status = 503
            raw = b'{"version":1,"error":{"code":"unavailable","message":"Response unavailable"}}'
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.send_header("Content-Length", str(len(raw)))
        if status == 405:
            self.send_header("Allow", "POST" if self.path == "/api/v1/assistant" else "GET")
        self.end_headers()
        self.wfile.write(raw)

    def parse_request(self) -> bool:
        if not super().parse_request():
            return False
        try:
            self._guard()
        except WebError as exc:
            self._reply(
                exc.status, {"version": 1, "error": {"code": exc.code, "message": exc.message}}
            )
            return False
        return True

    def _guard(self) -> None:
        if (
            len(self.raw_requestline) > 2048
            or sum(len(k) + len(v) for k, v in self.headers.items()) > 16384
        ):
            raise WebError(400, "bad_request", "Request rejected")
        for header in ("Host", "Origin", "X-Rakathon-Proxy-Key", "Content-Length", "Content-Type"):
            if len(self.headers.get_all(header, [])) > 1:
                raise WebError(400, "bad_request", "Request rejected")
        if self.headers.get("Host") not in self.server.hosts:
            raise WebError(403, "forbidden", "Request forbidden")
        if "Origin" in self.headers and self.headers["Origin"] not in self.server.origins:
            raise WebError(403, "forbidden", "Request forbidden")
        if any(
            header.lower() in ("forwarded", "x-forwarded-host", "x-original-host")
            for header in self.headers
        ):
            raise WebError(403, "forbidden", "Request forbidden")
        supplied = self.headers.get("X-Rakathon-Proxy-Key", "")
        if not hmac.compare_digest(supplied.encode("utf-8"), self.server.key.encode("ascii")):
            raise WebError(403, "forbidden", "Request forbidden")
        assistant_post = self.command == "POST" and self.path == "/api/v1/assistant"
        if self.command != "GET" and not assistant_post:
            raise WebError(405, "method_not_allowed", "Only GET is supported")
        if assistant_post:
            if "Origin" not in self.headers:
                raise WebError(403, "forbidden", "Explicit Origin required")
            length = self.headers.get("Content-Length", "")
            if not length.isascii() or not length.isdigit() or not 0 < int(length) <= MAX_REQUEST:
                raise WebError(400, "bad_request", "Invalid body length")
            if self.headers.get("Content-Type") not in (
                "application/json",
                "application/json; charset=utf-8",
            ):
                raise WebError(400, "bad_request", "JSON body required")
        if (
            "Transfer-Encoding" in self.headers
            or (not assistant_post and self.headers.get("Content-Length", "0") != "0")
            or "Expect" in self.headers
        ):
            raise WebError(400, "bad_request", "Request body not supported")
        if (
            "?" in self.path
            or "#" in self.path
            or "%" in self.path
            or not self.path.startswith("/")
        ):
            raise WebError(400, "bad_request", "Request path rejected")

    def handle_expect_100(self) -> bool:
        self.send_error(400)
        return False

    def do_POST(self) -> None:
        future: concurrent.futures.Future[tuple[int, dict[str, Any]]] | None = None
        try:
            length = int(self.headers["Content-Length"])
            data = self.rfile.read(length)
            if len(data) != length:
                raise ValueError("incomplete body")
            request = json.loads(
                data.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
            )
            future = asyncio.run_coroutine_threadsafe(
                self.server.service.send_assistant(request), self.server.loop
            )
            status, body = future.result(timeout=85)
        except WebError as exc:
            status, body = (
                exc.status,
                {"version": 1, "error": {"code": exc.code, "message": exc.message}},
            )
        except (ValueError, UnicodeError, RecursionError):
            status, body = (
                400,
                {"version": 1, "error": {"code": "bad_request", "message": "Invalid JSON request"}},
            )
        except UPSTREAM_FAILURES:
            if future is not None:
                future.cancel()
            status, body = (
                503,
                {
                    "version": 1,
                    "error": {"code": "unavailable", "message": "Assistant unavailable"},
                },
            )
        self._reply(status, body)

    def do_GET(self) -> None:
        future: concurrent.futures.Future[tuple[int, dict[str, Any]]] | None = None
        try:
            if self.path == "/api/v1/assistant":
                raise WebError(405, "method_not_allowed", "Only POST is supported")
            if self.path == "/api/v1/session":
                operation = self.server.service.session()
            elif self.path == "/api/v1/workspace":
                operation = self.server.service.workspace()
            elif self.path.startswith("/api/v1/cases/"):
                patient_id = self.path.removeprefix("/api/v1/cases/")
                if ID.fullmatch(patient_id) is None:
                    raise WebError(400, "bad_request", "Invalid case identifier")
                operation = self.server.service.case(patient_id)
            else:
                raise WebError(404, "not_found", "Endpoint not found")
            future = asyncio.run_coroutine_threadsafe(operation, self.server.loop)
            status, body = future.result(timeout=REQUEST_TIMEOUT)
        except WebError as exc:
            status, body = (
                exc.status,
                {"version": 1, "error": {"code": exc.code, "message": exc.message}},
            )
        except UPSTREAM_FAILURES:
            if future is not None:
                future.cancel()
            status, body = (
                503,
                {"version": 1, "error": {"code": "unavailable", "message": "Backend unavailable"}},
            )
        self._reply(status, body)
