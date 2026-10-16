from __future__ import annotations

import asyncio
import http.client
import json
import secrets
import threading
from pathlib import Path
from typing import Any

import pytest

from rakathon_backend.b2.auth.keys import generate_key_file
from rakathon_backend.b2.auth.models import StoreUnavailable
from rakathon_backend.b2.auth.sqlite_store import SQLiteDemoAuthStore
from rakathon_backend.b7.client import B7SocketClient
from rakathon_backend.b7.handler import B7AuthHandler
from rakathon_backend.b7.provider import LocalPasswordProvider
from rakathon_backend.b7.service import AuthService
from rakathon_backend.runtime.application import BackendApp
from rakathon_backend.runtime.auth_bundle import build_auth_app, fresh_tokens_with_auth
from rakathon_backend.web.config import COOKIE_LOOPBACK, WebConfig
from rakathon_backend.web.edge import build_login_callables
from rakathon_backend.web.router import AuthHTTPRouter
from rakathon_backend.web.server import build_server, serve_forever

PW = "correct-horse-battery-staple-x"
PROXY = "K" * 43
ORIGIN = "http://127.0.0.1:5173"


def make_service(
    tmp_path: Path, now: list[int], name: str = "auth", account_limit: int = 10
) -> AuthService:
    auth_dir = tmp_path / name
    auth_dir.mkdir(mode=0o700)
    keys = generate_key_file(auth_dir / "auth.authkey")
    store = SQLiteDemoAuthStore(auth_dir / "users.auth.db")
    store.init_schema()
    provider = LocalPasswordProvider(time_cost=2, memory_cost=19456, parallelism=1)
    return AuthService(
        store=store,
        keys=keys,
        provider=provider,
        clock=lambda: now[0],
        account_limit=account_limit,
    )


def count_b7(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    counts = {"auth.login": 0, "auth.resolve": 0, "auth.logout": 0}
    original = B7AuthHandler.handle

    async def counting(self: B7AuthHandler, request: Any) -> Any:
        counts[request.action] = counts.get(request.action, 0) + 1
        return await original(self, request)

    monkeypatch.setattr(B7AuthHandler, "handle", counting)
    return counts


async def launch(tmp_path: Path, svc: AuthService, sub: str) -> dict[str, Any]:
    runtime = tmp_path / sub
    runtime.mkdir(mode=0o700)
    tokens = fresh_tokens_with_auth()
    app = build_auth_app(runtime, tokens, svc)
    await app.start()
    token = tokens["web:auth"]
    login, resolve, csrf_for, logout = build_login_callables(B7SocketClient(runtime, token))
    router = AuthHTTPRouter(WebConfig.build(ORIGIN, True), PROXY, login, resolve, csrf_for, logout)
    server = build_server("127.0.0.1", 0, router)
    thread = threading.Thread(target=serve_forever, args=(server,), daemon=True)
    thread.start()
    live: dict[str, Any] = {
        "app": app,
        "host": "127.0.0.1",
        "port": int(server.server_address[1]),
        "server": server,
        "thread": thread,
        "tokens": tokens,
        "runtime": runtime,
    }
    return live


async def land(live: dict[str, Any]) -> None:
    app = live["app"]
    assert isinstance(app, BackendApp)
    live["server"].shutdown()
    live["thread"].join(timeout=10.0)
    live["server"].server_close()
    await app.close()


def request(
    host: str,
    port: int,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection(host, port, timeout=10)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        reply = conn.getresponse()
        data = reply.read()
        out = {k.lower(): v for k, v in reply.getheaders()}
        return (reply.status, out, data)
    finally:
        conn.close()


def login_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Rakathon-Proxy-Key": PROXY,
        "Origin": ORIGIN,
        "X-Rakathon-Auth": "1",
    }


def login_payload(username: str, password: str) -> bytes:
    return json.dumps({"username": username, "password": password}).encode()


def cookie_of(headers: dict[str, str]) -> str:
    return headers["set-cookie"].split("=", 1)[1].split(";")[0].strip()


async def over_http(
    host: str,
    port: int,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> tuple[int, dict[str, str], bytes]:
    return await asyncio.to_thread(request, host, port, method, path, headers, body)


async def post_login(
    host: str, port: int, username: str, password: str
) -> tuple[int, dict[str, str], bytes]:
    return await over_http(
        host, port, "POST", "/api/v1/auth/login", login_headers(), login_payload(username, password)
    )


async def test_http_auth_traverses_b7_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000000]
    svc = make_service(tmp_path, now)
    ident = svc.provision_user("jane.doe", PW, "viewer")
    counts = count_b7(monkeypatch)
    live = await launch(tmp_path, svc, "rt1")
    try:
        host = str(live["host"])
        port = int(live["port"])
        status, headers, raw = await post_login(host, port, "jane.doe", PW)
        assert status == 200
        body = json.loads(raw.decode())
        assert body["user"]["id"] == ident.user_id
        assert counts["auth.login"] == 1
        assert cookie_of(headers) not in raw.decode()
        token = cookie_of(headers)
        session_headers = {
            "X-Rakathon-Proxy-Key": PROXY,
            "Cookie": f"{COOKIE_LOOPBACK}={token}",
        }
        status, _, _ = await over_http(host, port, "GET", "/api/v1/auth/session", session_headers)
        assert status == 200
        assert counts["auth.resolve"] >= 1
        csrf = str(body["csrfToken"])
        logout_headers = dict(session_headers)
        logout_headers.update({"Origin": ORIGIN, "X-CSRF-Token": csrf, "Content-Length": "0"})
        status, _, _ = await over_http(
            host, port, "POST", "/api/v1/auth/logout", logout_headers, b""
        )
        assert status == 204
        assert counts["auth.logout"] == 1
        status, _, raw = await over_http(host, port, "GET", "/api/v1/auth/session", session_headers)
        assert status == 401
        assert json.loads(raw.decode()) == {"error": "invalid_credentials"}
    finally:
        await land(live)


async def test_wrong_token_or_socket_fails_closed_core_alive(tmp_path: Path) -> None:
    now = [2000000]
    svc = make_service(tmp_path, now)
    svc.provision_user("jane.doe", PW, "viewer")
    live = await launch(tmp_path, svc, "rt2")
    bad_thread: threading.Thread | None = None
    bad_server: Any = None
    try:
        host = str(live["host"])
        port = int(live["port"])
        runtime = live["runtime"]
        assert isinstance(runtime, Path)
        tokens = live["tokens"]
        assert isinstance(tokens, dict)
        config = WebConfig.build(ORIGIN, True)
        bad_callables = build_login_callables(B7SocketClient(runtime, secrets.token_urlsafe(32)))
        bad_router = AuthHTTPRouter(config, PROXY, *bad_callables)
        bad_server = build_server("127.0.0.1", 0, bad_router)
        bad_thread = threading.Thread(target=serve_forever, args=(bad_server,), daemon=True)
        bad_thread.start()
        bad_port = int(bad_server.server_address[1])
        status, _, raw = await post_login(host, bad_port, "jane.doe", PW)
        assert status == 503
        assert json.loads(raw.decode()) == {"error": "not_configured"}
        forged = {
            "X-Rakathon-Proxy-Key": PROXY,
            "Cookie": f"{COOKIE_LOOPBACK}={'A' * 43}",
        }
        status, _, _ = await over_http(host, bad_port, "GET", "/api/v1/auth/session", forged)
        assert status == 503
        logout_headers = dict(forged)
        logout_headers.update({"Origin": ORIGIN, "X-CSRF-Token": "0" * 64, "Content-Length": "0"})
        status, _, _ = await over_http(
            host, bad_port, "POST", "/api/v1/auth/logout", logout_headers, b""
        )
        assert status == 503
        orphan = B7SocketClient(tmp_path / "rt2missing", str(tokens["web:auth"]))
        with pytest.raises(StoreUnavailable):
            await asyncio.to_thread(orphan.login, "jane.doe", PW)
        status, _, raw = await post_login(host, port, "jane.doe", PW)
        assert status == 200
        assert json.loads(raw.decode())["authenticated"] is True
    finally:
        if bad_server is not None:
            bad_server.shutdown()
        if bad_thread is not None:
            bad_thread.join(timeout=10.0)
        if bad_server is not None:
            bad_server.server_close()
        await land(live)


async def test_bad_credentials_401_across_uds(tmp_path: Path) -> None:
    now = [3000000]
    svc = make_service(tmp_path, now)
    svc.provision_user("jane.doe", PW, "viewer")
    live = await launch(tmp_path, svc, "rt3")
    try:
        host = str(live["host"])
        port = int(live["port"])
        status, headers, raw = await post_login(host, port, "jane.doe", "wrong-wrong-wrong-pass")
        assert status == 401
        assert json.loads(raw.decode()) == {"error": "invalid_credentials"}
        assert "set-cookie" not in headers
        for malformed in ("badnodot", "a b.c", "a..b"):
            status, headers, raw = await post_login(host, port, malformed, PW)
            assert status == 401
            assert json.loads(raw.decode()) == {"error": "invalid_credentials"}
            assert "set-cookie" not in headers
            assert malformed not in raw.decode()
    finally:
        await land(live)


async def test_rate_limit_429_across_uds(tmp_path: Path) -> None:
    now = [4000000]
    svc = make_service(tmp_path, now, name="auth4", account_limit=1)
    svc.provision_user("jane.doe", PW, "viewer")
    live = await launch(tmp_path, svc, "rt4")
    try:
        host = str(live["host"])
        port = int(live["port"])
        status, _, _ = await over_http(
            host,
            port,
            "POST",
            "/api/v1/auth/login",
            login_headers(),
            login_payload("jane.doe", "wrong-wrong-wrong-pass"),
        )
        assert status == 401
        status, headers, _ = await over_http(
            host,
            port,
            "POST",
            "/api/v1/auth/login",
            login_headers(),
            login_payload("jane.doe", PW),
        )
        assert status == 429
        assert headers.get("retry-after") == "5"
    finally:
        await land(live)


async def test_logout_outage_503_no_clear_then_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [5000000]
    svc = make_service(tmp_path, now, name="auth5")
    svc.provision_user("jane.doe", PW, "viewer")
    live = await launch(tmp_path, svc, "rt5")
    try:
        host = str(live["host"])
        port = int(live["port"])
        status, headers, raw = await post_login(host, port, "jane.doe", PW)
        assert status == 200
        token = cookie_of(headers)
        csrf = str(json.loads(raw.decode())["csrfToken"])
        session_headers = {
            "X-Rakathon-Proxy-Key": PROXY,
            "Cookie": f"{COOKIE_LOOPBACK}={token}",
        }
        logout_headers = dict(session_headers)
        logout_headers.update({"Origin": ORIGIN, "X-CSRF-Token": csrf, "Content-Length": "0"})
        original = svc.store.delete_session

        def failing(token_hash: str) -> None:
            _ = token_hash
            raise StoreUnavailable()

        monkeypatch.setattr(svc.store, "delete_session", failing)
        try:
            status, out, raw = await over_http(
                host, port, "POST", "/api/v1/auth/logout", logout_headers, b""
            )
            assert status == 503
            assert "set-cookie" not in out
            assert token not in raw.decode()
            assert csrf not in raw.decode()
            status, _, raw = await over_http(
                host, port, "GET", "/api/v1/auth/session", session_headers
            )
            assert status == 200
        finally:
            monkeypatch.setattr(svc.store, "delete_session", original)
        status, out, _ = await over_http(
            host, port, "POST", "/api/v1/auth/logout", logout_headers, b""
        )
        assert status == 204
        assert "deleted" in out.get("set-cookie", "")
        status, _, raw = await over_http(host, port, "GET", "/api/v1/auth/session", session_headers)
        assert status == 401
    finally:
        await land(live)
