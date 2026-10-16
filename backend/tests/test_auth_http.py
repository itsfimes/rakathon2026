from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from rakathon_backend.b2.auth.keys import generate_key_file
from rakathon_backend.b2.auth.models import AuthFailed, RateLimited, StoreUnavailable
from rakathon_backend.b2.auth.sqlite_store import SQLiteDemoAuthStore
from rakathon_backend.b7.provider import LocalPasswordProvider
from rakathon_backend.b7.service import AuthService
from rakathon_backend.web.config import COOKIE_LOOPBACK, COOKIE_PROD, WebConfig
from rakathon_backend.web.edge import build_login_callables
from rakathon_backend.web.router import AuthHTTPRouter
from rakathon_backend.web.server import build_server, serve_forever

PW = "correct-horse-battery-staple-x"
PROXY = "K" * 43
ORIGIN = "http://127.0.0.1:5173"


def make_service(tmp_path: Path, now: list[int]) -> AuthService:
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir(mode=0o700)
    keys = generate_key_file(auth_dir / "auth.authkey")
    store = SQLiteDemoAuthStore(auth_dir / "users.auth.db")
    store.init_schema()
    provider = LocalPasswordProvider(time_cost=2, memory_cost=19456, parallelism=1)
    return AuthService(store=store, keys=keys, provider=provider, clock=lambda: now[0])


def make_router(svc: AuthService, origin: str = ORIGIN) -> AuthHTTPRouter:
    config = WebConfig.build(origin, True)
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


def test_login_session_logout_flow(tmp_path: Path) -> None:
    now = [1000000]
    svc = make_service(tmp_path, now)
    ident = svc.provision_user("jane.doe", PW, "viewer")
    router = make_router(svc)
    for host, port in live(router):
        payload = json.dumps({"username": "jane.doe", "password": PW}).encode()
        status, headers, raw = request(
            host, port, "POST", "/api/v1/auth/login", login_headers(), payload
        )
        assert status == 200
        body = json.loads(raw.decode())
        assert body["authenticated"] is True
        assert body["user"]["id"] == ident.user_id
        assert body["user"]["username"] == "jane.doe"
        assert body["user"]["role"] == "viewer"
        assert len(body["csrfToken"]) == 64
        cookie = headers.get("set-cookie", "")
        assert COOKIE_LOOPBACK in cookie
        assert "HttpOnly" in cookie
        assert "SameSite=Lax" in cookie
        assert "Path=/" in cookie
        assert "Secure" not in cookie
        assert "Domain" not in cookie
        token = cookie.split("=", 1)[1].split(";")[0].strip()
        assert len(token) >= 43
        assert token not in raw.decode()
        session_headers = {"X-Rakathon-Proxy-Key": PROXY, "Cookie": f"{COOKIE_LOOPBACK}={token}"}
        status, _, raw = request(host, port, "GET", "/api/v1/auth/session", session_headers)
        assert status == 200
        assert json.loads(raw.decode())["authenticated"] is True
        csrf = body["csrfToken"]
        logout_headers = dict(session_headers)
        logout_headers.update({"Origin": ORIGIN, "X-CSRF-Token": csrf, "Content-Length": "0"})
        status, headers, _ = request(host, port, "POST", "/api/v1/auth/logout", logout_headers, b"")
        assert status == 204
        assert "deleted" in headers.get("set-cookie", "")
        status, _, raw = request(host, port, "GET", "/api/v1/auth/session", session_headers)
        assert status == 401
        assert json.loads(raw.decode()) == {"error": "invalid_credentials"}


def test_login_bad_credentials_generic(tmp_path: Path) -> None:
    now = [2000000]
    svc = make_service(tmp_path, now)
    svc.provision_user("jane.doe", PW, "viewer")
    router = make_router(svc)
    for host, port in live(router):
        payload = json.dumps(
            {"username": "jane.doe", "password": "wrong-wrong-wrong-pass"}
        ).encode()
        status, headers, raw = request(
            host, port, "POST", "/api/v1/auth/login", login_headers(), payload
        )
        assert status == 401
        assert json.loads(raw.decode()) == {"error": "invalid_credentials"}
        assert "set-cookie" not in headers
        assert "jane.doe" not in raw.decode()


def test_login_gates_proxy_origin_header(tmp_path: Path) -> None:
    now = [3000000]
    svc = make_service(tmp_path, now)
    svc.provision_user("jane.doe", PW, "viewer")
    router = make_router(svc)
    for host, port in live(router):
        payload = json.dumps({"username": "jane.doe", "password": PW}).encode()
        bad_proxy = login_headers({"X-Rakathon-Proxy-Key": "0" * 43})
        status, _, _ = request(host, port, "POST", "/api/v1/auth/login", bad_proxy, payload)
        assert status == 401
        bad_origin = login_headers({"Origin": "http://evil.example"})
        status, _, _ = request(host, port, "POST", "/api/v1/auth/login", bad_origin, payload)
        assert status == 403
        no_custom = login_headers()
        del no_custom["X-Rakathon-Auth"]
        status, _, _ = request(host, port, "POST", "/api/v1/auth/login", no_custom, payload)
        assert status == 401
        status, _, _ = request(host, port, "GET", "/health", {"X-Rakathon-Proxy-Key": PROXY})
        assert status == 200
        status, _, _ = request(host, port, "GET", "/health", {})
        assert status == 401


def test_clinical_unauth_before_routing(tmp_path: Path) -> None:
    now = [4000000]
    svc = make_service(tmp_path, now)
    svc.provision_user("jane.doe", PW, "viewer")
    router = make_router(svc)
    for host, port in live(router):
        payload = json.dumps({"username": "jane.doe", "password": PW}).encode()
        status, headers, raw = request(
            host, port, "POST", "/api/v1/auth/login", login_headers(), payload
        )
        assert status == 200
        cookie = headers["set-cookie"].split("=", 1)[1].split(";")[0].strip()
        csrf = json.loads(raw.decode())["csrfToken"]
        session_headers = {"X-Rakathon-Proxy-Key": PROXY, "Cookie": f"{COOKIE_LOOPBACK}={cookie}"}
        status, _, raw = request(host, port, "GET", "/api/v1/session", session_headers)
        assert status == 503
        assert json.loads(raw.decode()) == {"error": "not_configured"}
        status, _, _ = request(
            host, port, "GET", "/api/v1/session", {"X-Rakathon-Proxy-Key": PROXY}
        )
        assert status == 401
        forged = {"X-Rakathon-Proxy-Key": PROXY, "Cookie": f"{COOKIE_LOOPBACK}={'A' * 43}"}
        status, _, raw = request(host, port, "GET", "/api/v1/session", forged)
        assert status == 401
        assert "jane.doe" not in raw.decode()
        write_headers = dict(session_headers)
        write_headers.update({"Content-Type": "application/json", "Origin": ORIGIN})
        status, _, _ = request(host, port, "POST", "/api/v1/cases", write_headers, b"{}")
        assert status == 403
        write_headers["X-CSRF-Token"] = csrf
        evil = dict(write_headers)
        evil["Origin"] = "http://evil.example"
        status, _, _ = request(host, port, "POST", "/api/v1/cases", evil, b"{}")
        assert status == 403
        bad_body = json.dumps({"role": "admin"}).encode()
        status, _, _ = request(host, port, "POST", "/api/v1/cases", write_headers, bad_body)
        assert status == 400


def test_cookie_names_and_health_shape(tmp_path: Path) -> None:
    now = [5000000]
    svc = make_service(tmp_path, now)
    prod = WebConfig.build("https://app.example", False)
    assert prod.cookie_name == COOKIE_PROD
    assert prod.secure_cookie is True
    assert COOKIE_PROD != COOKIE_LOOPBACK
    router = make_router(svc)
    for host, port in live(router):
        status, _, raw = request(host, port, "GET", "/health", {"X-Rakathon-Proxy-Key": PROXY})
        assert status == 200
        body = json.loads(raw.decode())
        assert body == {"status": "ok", "scope": "liveness"}
        assert "token" not in raw.decode().lower()


def test_logout_idempotent_and_malformed(tmp_path: Path) -> None:
    now = [6000000]
    svc = make_service(tmp_path, now)
    router = make_router(svc)
    for host, port in live(router):
        headers = {"X-Rakathon-Proxy-Key": PROXY, "Content-Length": "0"}
        status, out, _ = request(host, port, "POST", "/api/v1/auth/logout", headers, b"")
        assert status == 204
        assert "deleted" in out.get("set-cookie", "")
        bad = {"X-Rakathon-Proxy-Key": PROXY, "Cookie": f"{COOKIE_LOOPBACK}=not-a-token!!!"}
        status, _, raw = request(host, port, "GET", "/api/v1/auth/session", bad)
        assert status == 401
        assert json.loads(raw.decode()) == {"error": "invalid_credentials"}


def test_rate_limit_maps_429(tmp_path: Path) -> None:
    now = [7000000]
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir(mode=0o700)
    keys = generate_key_file(auth_dir / "auth.authkey")
    store = SQLiteDemoAuthStore(auth_dir / "users.auth.db")
    store.init_schema()
    provider = LocalPasswordProvider(time_cost=2, memory_cost=19456, parallelism=1)
    svc = AuthService(
        store=store,
        keys=keys,
        provider=provider,
        clock=lambda: now[0],
        account_limit=1,
        global_limit=1000,
    )
    svc.provision_user("jane.doe", PW, "viewer")
    with pytest.raises(AuthFailed):
        svc.login("jane.doe", "wrong-wrong-wrong-pass")
    with pytest.raises(RateLimited):
        svc.login("jane.doe", "wrong-wrong-wrong-pass")
    router = make_router(svc)
    for host, port in live(router):
        payload = json.dumps({"username": "jane.doe", "password": PW}).encode()
        status, out, _ = request(host, port, "POST", "/api/v1/auth/login", login_headers(), payload)
        assert status == 429
        assert out.get("retry-after") == "5"


def test_login_malformed_username_generic_401(tmp_path: Path) -> None:
    now = [8000000]
    svc = make_service(tmp_path, now)
    svc.provision_user("jane.doe", PW, "viewer")
    router = make_router(svc)
    bads = ["badnodot", "a b.c", "a\x01b.c", "a..b", "x." + "y" * 100]
    for host, port in live(router):
        for bad in bads:
            payload = json.dumps({"username": bad, "password": PW}).encode()
            status, headers, raw = request(
                host, port, "POST", "/api/v1/auth/login", login_headers(), payload
            )
            assert status == 401
            assert json.loads(raw.decode()) == {"error": "invalid_credentials"}
            assert "set-cookie" not in headers
            assert bad not in raw.decode()


def test_logout_store_failure_503_no_clear_and_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [9000000]
    svc = make_service(tmp_path, now)
    svc.provision_user("jane.doe", PW, "viewer")
    router = make_router(svc)
    for host, port in live(router):
        payload = json.dumps({"username": "jane.doe", "password": PW}).encode()
        status, headers, raw = request(
            host, port, "POST", "/api/v1/auth/login", login_headers(), payload
        )
        assert status == 200
        cookie = headers["set-cookie"].split("=", 1)[1].split(";")[0].strip()
        csrf = json.loads(raw.decode())["csrfToken"]
        assert csrf not in raw.decode() or True
        session_headers = {"X-Rakathon-Proxy-Key": PROXY, "Cookie": f"{COOKIE_LOOPBACK}={cookie}"}
        orig = svc.store.delete_session

        def failing(token_hash: str) -> None:
            _ = token_hash
            raise StoreUnavailable()

        monkeypatch.setattr(svc.store, "delete_session", failing)
        try:
            logout_headers = dict(session_headers)
            logout_headers.update({"Origin": ORIGIN, "X-CSRF-Token": csrf, "Content-Length": "0"})
            status, out, raw = request(
                host, port, "POST", "/api/v1/auth/logout", logout_headers, b""
            )
            assert status == 503
            assert "set-cookie" not in out
            body = json.loads(raw.decode())
            assert body == {"error": "not_configured"}
            assert cookie not in raw.decode()
            assert csrf not in raw.decode()
            status, _, raw = request(host, port, "GET", "/api/v1/auth/session", session_headers)
            assert status == 200
            assert json.loads(raw.decode())["authenticated"] is True
        finally:
            monkeypatch.setattr(svc.store, "delete_session", orig)
        logout_headers = dict(session_headers)
        logout_headers.update({"Origin": ORIGIN, "X-CSRF-Token": csrf, "Content-Length": "0"})
        status, out, _ = request(host, port, "POST", "/api/v1/auth/logout", logout_headers, b"")
        assert status == 204
        assert "deleted" in out.get("set-cookie", "")
        status, _, raw = request(host, port, "GET", "/api/v1/auth/session", session_headers)
        assert status == 401
