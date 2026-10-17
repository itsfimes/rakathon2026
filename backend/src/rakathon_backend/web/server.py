from __future__ import annotations

import contextlib
import ipaddress
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from rakathon_backend.web.config import (
    MAX_BODY_BYTES,
    MAX_HEADER_CHARS,
    MAX_PATH_CHARS,
    MAX_RESPONSE_BYTES,
    listener_authority,
)
from rakathon_backend.web.router import AuthHTTPRouter

MAX_WORKERS = 16
REQUEST_TIMEOUT = 10.0
ALLOW_BIND = frozenset({"127.0.0.1", "::1", "localhost"})


def check_bind_host(bind: str) -> str:
    text = bind.strip().strip("[]")
    lowered = text.lower()
    if lowered == "localhost":
        return "127.0.0.1"
    if text in ("127.0.0.1", "::1"):
        return text
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        raise ValueError("bind must be loopback")
    if not addr.is_loopback:
        raise ValueError("bind must be loopback")
    return text


def check_port(port: int) -> int:
    if isinstance(port, bool) or not isinstance(port, int):
        raise TypeError("port invalid")
    if port < 0 or port > 65535:
        raise ValueError("port invalid")
    return port


class _AuthHandler(BaseHTTPRequestHandler):
    router: AuthHTTPRouter | None = None
    request_timeout: float = REQUEST_TIMEOUT
    worker_slots: threading.Semaphore | None = None

    def log_message(self, *args: object) -> None:
        return None

    def setup(self) -> None:
        super().setup()
        with contextlib.suppress(OSError):
            self.connection.settimeout(type(self).request_timeout)

    def do_GET(self) -> None:
        self._dispatch()

    def do_POST(self) -> None:
        self._dispatch()

    def do_PUT(self) -> None:
        self._dispatch()

    def do_PATCH(self) -> None:
        self._dispatch()

    def do_DELETE(self) -> None:
        self._dispatch()

    def do_HEAD(self) -> None:
        self._dispatch()

    def do_OPTIONS(self) -> None:
        self._refuse(404, {})

    def do_PUT_PATCH(self) -> None:
        self._refuse(404, {})

    def _dispatch(self) -> None:
        slots = type(self).worker_slots
        if slots is not None and not slots.acquire(blocking=False):
            self._refuse(503, {})
            return
        try:
            self._serve()
        finally:
            if slots is not None:
                slots.release()

    def _refuse(self, code: int, headers: dict[str, str]) -> None:
        if code == 401:
            body: dict[str, Any] = {"error": "auth_failed"}
        elif code == 403:
            body = {"error": "auth_failed"}
        elif code == 404:
            body = {"error": "not_found"}
        elif code == 413:
            body = {"error": "too_large"}
        elif code == 429:
            body = {"error": "rate_limited"}
        elif code == 503:
            body = {"error": "not_configured"}
        else:
            body = {"error": "bad_request"}
        raw = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            with contextlib.suppress(OSError):
                self.wfile.write(raw)

    def _serve(self) -> None:
        raw_path = self.path
        if len(raw_path) > MAX_PATH_CHARS:
            self._refuse(413, {})
            return
        path = raw_path.split("?", 1)[0].split("#", 1)[0]
        if not path.startswith("/") or len(path) > MAX_PATH_CHARS:
            self._refuse(400, {})
            return
        if self.headers.get("Transfer-Encoding") is not None:
            self._refuse(400, {})
            return
        getter = getattr(self.headers, "get_all", None)
        dup_check: dict[str, int] = {}
        if callable(getter):
            for name in ("Content-Length", "X-Rakathon-Proxy-Key", "Origin", "Cookie", "Host"):
                try:
                    values = getter(name) or []
                except (ValueError, AttributeError):
                    values = []
                dup_check[name] = len([str(v) for v in values])
            if dup_check.get("Content-Length", 0) > 1:
                self._refuse(400, {})
                return
            if dup_check.get("X-Rakathon-Proxy-Key", 0) > 1:
                self._refuse(400, {})
                return
            if dup_check.get("Origin", 0) > 1:
                self._refuse(400, {})
                return
            if dup_check.get("Cookie", 0) > 1:
                self._refuse(400, {})
                return
            if dup_check.get("Host", 0) > 1:
                self._refuse(400, {})
                return
        total_headers = sum(len(str(k)) + len(str(v)) for k, v in self.headers.items())
        if total_headers > MAX_HEADER_CHARS * 4:
            self._refuse(413, {})
            return
        needs_body = self.command in ("POST", "PUT", "PATCH", "DELETE")
        data: bytes | None = None
        if needs_body:
            length_raw = self.headers.get("Content-Length")
            if length_raw is None:
                self._refuse(400, {})
                return
            try:
                length = int(str(length_raw).strip())
            except ValueError:
                self._refuse(400, {})
                return
            if length < 0 or length > MAX_BODY_BYTES:
                self._refuse(413 if length > MAX_BODY_BYTES else 400, {})
                return
            try:
                data = self.rfile.read(length) if length > 0 else b""
            except OSError:
                self._refuse(400, {})
                return
            if data is None or len(data) != length:
                self._refuse(400, {})
                return
        else:
            length_raw = self.headers.get("Content-Length")
            if length_raw is not None and str(length_raw).strip() not in ("", "0"):
                try:
                    if int(str(length_raw).strip()) != 0:
                        self._refuse(400, {})
                        return
                except ValueError:
                    self._refuse(400, {})
                    return
        headers = {str(k): str(v) for k, v in self.headers.items()}
        router = type(self).router
        assert router is not None
        try:
            status, out_headers, payload = router.handle(self.command, path, headers, data)
        except (ValueError, KeyError, RuntimeError, OSError, TypeError):
            self._refuse(503, {})
            return
        if status == 204:
            self.send_response(204)
            self.send_header("Cache-Control", "no-store")
            for key, value in out_headers.items():
                self.send_header(key, value)
            self.end_headers()
            return
        try:
            raw = json.dumps(payload).encode("utf-8")
        except (ValueError, TypeError):
            self._refuse(503, {})
            return
        if len(raw) > MAX_RESPONSE_BYTES:
            self._refuse(503, {})
            return
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        for key, value in out_headers.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            with contextlib.suppress(OSError):
                self.wfile.write(raw)

    def version_string(self) -> str:
        return "auth"


def build_server(
    bind: str,
    port: int,
    router: AuthHTTPRouter,
    *,
    request_timeout: float = REQUEST_TIMEOUT,
    max_workers: int = MAX_WORKERS,
) -> ThreadingHTTPServer:
    host = check_bind_host(bind)
    checked_port = check_port(port)
    handler_cls = type(
        "AuthWebHandler",
        (_AuthHandler,),
        {
            "router": router,
            "request_timeout": request_timeout,
            "worker_slots": threading.Semaphore(max_workers),
        },
    )
    server = ThreadingHTTPServer((host, checked_port), handler_cls)
    server.daemon_threads = True
    server.timeout = 10.0
    with contextlib.suppress(ValueError, TypeError, OSError):
        router.set_allowed_hosts(
            frozenset({listener_authority(host, int(server.server_address[1]))})
        )
    return server


def serve_forever(server: ThreadingHTTPServer) -> None:
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()


def start_in_thread(server: ThreadingHTTPServer) -> threading.Thread:
    thread = threading.Thread(target=serve_forever, args=(server,), daemon=True)
    thread.start()
    return thread


def server_port(server: ThreadingHTTPServer) -> int:
    return int(server.server_address[1])


def key_file_hint(path: Path) -> str:
    return str(Path(path))
