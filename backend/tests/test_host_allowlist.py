from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path

from rakathon_backend.b2.auth.keys import generate_key_file
from rakathon_backend.b2.auth.sqlite_store import SQLiteDemoAuthStore
from rakathon_backend.b7.provider import LocalPasswordProvider
from rakathon_backend.b7.service import AuthService
from rakathon_backend.web.config import (
    WebConfig,
    check_host_allowlist,
    listener_authority,
    normalize_authority,
)
from rakathon_backend.web.edge import build_login_callables
from rakathon_backend.web.router import AuthHTTPRouter
from rakathon_backend.web.server import build_server, serve_forever

PW = "correct-horse-battery-staple-x"
PROXY = "K" * 43
ORIGIN = "http://127.0.0.1:5173"


def make_router(svc: AuthService, allowed: frozenset[str] | None = None) -> AuthHTTPRouter:
    config = WebConfig.build(ORIGIN, True)
    login, resolve, csrf_for, logout = build_login_callables(svc)
    return AuthHTTPRouter(config, PROXY, login, resolve, csrf_for, logout, allowed_hosts=allowed)


def make_service(tmp_path: Path, now: list[int]) -> AuthService:
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir(mode=0o700)
    keys = generate_key_file(auth_dir / "auth.authkey")
    store = SQLiteDemoAuthStore(auth_dir / "users.auth.db")
    store.init_schema()
    provider = LocalPasswordProvider(time_cost=2, memory_cost=19456, parallelism=1)
    return AuthService(store=store, keys=keys, provider=provider, clock=lambda: now[0])


def raw_request(host: str, port: int, headers: dict[str, str]) -> int:
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request("GET", "/health", headers=headers)
        reply = conn.getresponse()
        reply.read()
        return reply.status
    finally:
        conn.close()


def test_allowlist_exact_and_port_sensitive() -> None:
    allowed = frozenset({"127.0.0.1:8765"})
    assert check_host_allowlist("127.0.0.1:8765", allowed) is True
    assert check_host_allowlist("127.0.0.1:5173", allowed) is False
    assert check_host_allowlist("localhost:8765", allowed) is False
    assert check_host_allowlist("127.0.0.2:8765", allowed) is False
    assert check_host_allowlist("127.0.0.1:8765, evil", allowed) is False
    assert check_host_allowlist("", allowed) is False
    assert normalize_authority("not-a-host") is None
    assert listener_authority("localhost", 8765) == "127.0.0.1:8765"
    assert listener_authority("::1", 8765) == "[::1]:8765"


def test_router_rejects_unlisted_host(tmp_path: Path) -> None:
    svc = make_service(tmp_path, [1000000])
    router = make_router(svc, frozenset({"127.0.0.1:8765"}))
    base = {"x-rakathon-proxy-key": PROXY}
    status, _, _ = router.handle("GET", "/health", dict(base, host="127.0.0.1:8765"), None)
    assert status == 200
    status, _, _ = router.handle("GET", "/health", dict(base, host="127.0.0.1:5173"), None)
    assert status == 403
    status, _, _ = router.handle("GET", "/health", dict(base, host="localhost:8765"), None)
    assert status == 403
    status, _, _ = router.handle("GET", "/health", dict(base), None)
    assert status == 200


def test_live_server_pins_listener_authority(tmp_path: Path) -> None:
    svc = make_service(tmp_path, [2000000])
    router = make_router(svc)
    server = build_server("127.0.0.1", 0, router)
    port = int(server.server_address[1])
    thread = threading.Thread(target=serve_forever, args=(server,), daemon=True)
    thread.start()
    try:
        good = {"X-Rakathon-Proxy-Key": PROXY, "Host": f"127.0.0.1:{port}"}
        assert raw_request("127.0.0.1", port, good) == 200
        wrong_port = {"X-Rakathon-Proxy-Key": PROXY, "Host": "127.0.0.1:5173"}
        assert raw_request("127.0.0.1", port, wrong_port) == 403
        alias = {"X-Rakathon-Proxy-Key": PROXY, "Host": f"localhost:{port}"}
        assert raw_request("127.0.0.1", port, alias) == 403
        forwarded = dict(good, **{"X-Forwarded-Host": "example.com"})
        assert raw_request("127.0.0.1", port, forwarded) == 403
    finally:
        server.shutdown()
        thread.join(timeout=5.0)
        server.server_close()


def test_login_flow_keeps_origin_contract(tmp_path: Path) -> None:
    svc = make_service(tmp_path, [3000000])
    svc.provision_user("jane.doe", PW, "viewer")
    router = make_router(svc)
    server = build_server("127.0.0.1", 0, router)
    port = int(server.server_address[1])
    thread = threading.Thread(target=serve_forever, args=(server,), daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            body = json.dumps({"username": "jane.doe", "password": PW}).encode()
            conn.request(
                "POST",
                "/api/v1/auth/login",
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Rakathon-Proxy-Key": PROXY,
                    "Origin": ORIGIN,
                    "X-Rakathon-Auth": "1",
                },
            )
            reply = conn.getresponse()
            raw = reply.read()
            assert reply.status == 200
            assert json.loads(raw.decode())["authenticated"] is True
        finally:
            conn.close()
    finally:
        server.shutdown()
        thread.join(timeout=5.0)
        server.server_close()
