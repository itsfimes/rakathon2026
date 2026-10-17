from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from rakathon_backend.b2.auth.keys import generate_key_file
from rakathon_backend.b2.auth.sqlite_store import SQLiteDemoAuthStore
from rakathon_backend.b7.provider import LocalPasswordProvider
from rakathon_backend.b7.service import AuthService
from rakathon_backend.web.config import (
    COOKIE_LOOPBACK,
    MAX_BODY_BYTES,
    MAX_RESPONSE_BYTES,
    WebConfig,
)
from rakathon_backend.web.edge import build_login_callables
from rakathon_backend.web.router import AuthHTTPRouter, VerifiedIdentity
from rakathon_backend.web.server import build_server, serve_forever

PW = "correct-horse-battery-staple-x"
PROXY = "K" * 43
ORIGIN = "http://127.0.0.1:5173"


def make_service(tmp_path: Path) -> AuthService:
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir(mode=0o700)
    keys = generate_key_file(auth_dir / "auth.authkey")
    store = SQLiteDemoAuthStore(auth_dir / "users.auth.db")
    store.init_schema()
    provider = LocalPasswordProvider(time_cost=2, memory_cost=19456, parallelism=1)
    return AuthService(store=store, keys=keys, provider=provider, clock=lambda: 1000000)


def make_router(svc: AuthService) -> AuthHTTPRouter:
    config = WebConfig.build(ORIGIN, True)
    login, resolve, csrf_for, logout = build_login_callables(svc)
    return AuthHTTPRouter(config, PROXY, login, resolve, csrf_for, logout)


def live(router: AuthHTTPRouter) -> Iterator[tuple[str, int]]:
    server = build_server("127.0.0.1", 0, router)
    port = int(server.server_address[1])
    thread = threading.Thread(target=serve_forever, args=(server,), daemon=True)
    thread.start()
    try:
        yield ("127.0.0.1", port)
    finally:
        server.shutdown()
        thread.join(timeout=5.0)
        server.server_close()


def request(
    host: str,
    port: int,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        reply = conn.getresponse()
        data = reply.read()
        out_headers = {k.lower(): v for k, v in reply.getheaders()}
        return (reply.status, out_headers, data)
    finally:
        conn.close()


def login_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    base = {
        "Content-Type": "application/json",
        "X-Rakathon-Proxy-Key": PROXY,
        "Origin": ORIGIN,
        "X-Rakathon-Auth": "1",
    }
    if extra:
        base.update(extra)
    return base


def authed_headers(host: str, port: int) -> dict[str, str]:
    payload = json.dumps({"username": "jane.doe", "password": PW}).encode()
    status, headers, _ = request(host, port, "POST", "/api/v1/auth/login", login_headers(), payload)
    assert status == 200
    token = headers["set-cookie"].split("=", 1)[1].split(";")[0].strip()
    return {"X-Rakathon-Proxy-Key": PROXY, "Cookie": f"{COOKIE_LOOPBACK}={token}"}


def large_ok(
    identity: VerifiedIdentity, method: str, path: str, body: dict[str, Any]
) -> tuple[int, dict[str, Any]]:
    _ = (identity, method, path, body)
    return (200, {"blob": "x" * 75000})


def oversized(
    identity: VerifiedIdentity, method: str, path: str, body: dict[str, Any]
) -> tuple[int, dict[str, Any]]:
    _ = (identity, method, path, body)
    return (200, {"blob": "x" * (1024 * 1024)})


def test_large_clinical_response_succeeds(tmp_path: Path) -> None:
    assert MAX_RESPONSE_BYTES == 1024 * 1024
    svc = make_service(tmp_path)
    svc.provision_user("jane.doe", PW, "viewer")
    router = make_router(svc)
    router.set_protected(large_ok)
    for host, port in live(router):
        headers = authed_headers(host, port)
        status, _, raw = request(host, port, "GET", "/api/v1/workspace", headers)
        assert status == 200
        assert len(raw) > 64 * 1024
        assert len(raw) < MAX_RESPONSE_BYTES
        assert json.loads(raw.decode())["blob"] == "x" * 75000


def test_oversized_clinical_response_rejected(tmp_path: Path) -> None:
    svc = make_service(tmp_path)
    svc.provision_user("jane.doe", PW, "viewer")
    router = make_router(svc)
    router.set_protected(oversized)
    for host, port in live(router):
        headers = authed_headers(host, port)
        status, _, raw = request(host, port, "GET", "/api/v1/workspace", headers)
        assert status == 503
        assert json.loads(raw.decode()) == {"error": "not_configured"}
        assert len(raw) < 1024


def test_request_body_limit_preserved(tmp_path: Path) -> None:
    assert MAX_BODY_BYTES == 16 * 1024
    svc = make_service(tmp_path)
    svc.provision_user("jane.doe", PW, "viewer")
    router = make_router(svc)
    for host, port in live(router):
        big = b"a" * (MAX_BODY_BYTES + 1)
        status, _, raw = request(host, port, "POST", "/api/v1/auth/login", login_headers(), big)
        assert status == 413
        assert json.loads(raw.decode()) == {"error": "too_large"}
