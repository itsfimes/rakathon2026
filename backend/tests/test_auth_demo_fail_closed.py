from __future__ import annotations

import json
from pathlib import Path

from auth_demo_http_helpers import (
    ORIGIN,
    PROXY,
    demo_headers,
    live,
    make_router,
    make_service,
    provision_all,
    request,
    write_mapping,
)

from rakathon_backend.b2.auth.models import StoreUnavailable
from rakathon_backend.web.config import COOKIE_LOOPBACK, WebConfig
from rakathon_backend.web.demo_login import load_demo_login_file
from rakathon_backend.web.edge import build_login_callables
from rakathon_backend.web.router import AuthHTTPRouter, VerifiedIdentity


def test_role_mismatch_revokes_session(tmp_path: Path) -> None:
    now = [6000000]
    svc = make_service(tmp_path, now)
    svc.provision_user("demo.koordinator", "koordinator-pw-correct-horse-01", "viewer")
    demo = load_demo_login_file(write_mapping(tmp_path))
    config = WebConfig.build(ORIGIN, True)
    login, resolve, csrf_for, logout = build_login_callables(svc)
    issued: list[str] = []

    def recording(username: str, password: str) -> tuple[str, VerifiedIdentity, str]:
        token, identity, csrf = login(username, password)
        issued.append(token)
        return (token, identity, csrf)

    router = AuthHTTPRouter(config, PROXY, recording, resolve, csrf_for, logout, demo=demo)
    for host, port in live(router):
        payload = json.dumps({"account": "koordinator"}).encode()
        status, headers, raw = request(
            host, port, "POST", "/api/v1/auth/demo-login", demo_headers(), payload
        )
        assert status == 401
        assert json.loads(raw.decode()) == {"error": "invalid_credentials"}
        assert "set-cookie" not in headers
        assert "koordinator-pw-correct-horse-01" not in raw.decode()
        assert headers.get("cache-control") == "no-store"
        assert len(issued) == 1
        stale = {"X-Rakathon-Proxy-Key": PROXY, "Cookie": f"{COOKIE_LOOPBACK}={issued[0]}"}
        status, _, _ = request(host, port, "GET", "/api/v1/auth/session", stale)
        assert status == 401


def test_username_mismatch_revokes_and_rejects(tmp_path: Path) -> None:
    now = [7000000]
    svc = make_service(tmp_path, now)
    provision_all(svc)
    demo = load_demo_login_file(write_mapping(tmp_path))
    config = WebConfig.build(ORIGIN, True)
    _, resolve, csrf_for, _ = build_login_callables(svc)
    revoked: list[str] = []

    def forged(username: str, password: str) -> tuple[str, VerifiedIdentity, str]:
        _ = (username, password)
        return (
            "A" * 43,
            VerifiedIdentity(
                user_id="u" * 32, username="somebody.else", role="viewer", auth_version=1
            ),
            "c" * 64,
        )

    def record_logout(token: str) -> None:
        revoked.append(token)

    router = AuthHTTPRouter(config, PROXY, forged, resolve, csrf_for, record_logout, demo=demo)
    for host, port in live(router):
        payload = json.dumps({"account": "pacient"}).encode()
        status, _, raw = request(
            host, port, "POST", "/api/v1/auth/demo-login", demo_headers(), payload
        )
        assert status == 401
        assert json.loads(raw.decode()) == {"error": "invalid_credentials"}
        assert revoked == ["A" * 43]


def test_demo_login_rate_limited(tmp_path: Path) -> None:
    now = [8000000]
    svc = make_service(tmp_path, now, account_limit=1, global_limit=1000)
    provision_all(svc)
    demo = load_demo_login_file(write_mapping(tmp_path))
    router = make_router(svc, demo)
    for host, port in live(router):
        payload = json.dumps({"account": "pacient"}).encode()
        status, _, _ = request(
            host, port, "POST", "/api/v1/auth/demo-login", demo_headers(), payload
        )
        assert status == 200
        status, headers, raw = request(
            host, port, "POST", "/api/v1/auth/demo-login", demo_headers(), payload
        )
        assert status == 429
        assert headers.get("retry-after") == "5"
        assert json.loads(raw.decode()) == {"error": "rate_limited"}
        assert headers.get("cache-control") == "no-store"


def test_backend_failures_map_503_without_secrets(tmp_path: Path) -> None:
    now = [9000000]
    svc = make_service(tmp_path, now)
    provision_all(svc)
    demo = load_demo_login_file(write_mapping(tmp_path))
    config = WebConfig.build(ORIGIN, True)
    _, resolve, csrf_for, logout = build_login_callables(svc)

    def down(username: str, password: str) -> tuple[str, VerifiedIdentity, str]:
        _ = (username, password)
        raise StoreUnavailable()

    router = AuthHTTPRouter(config, PROXY, down, resolve, csrf_for, logout, demo=demo)
    for host, port in live(router):
        payload = json.dumps({"account": "mdt"}).encode()
        status, _, raw = request(
            host, port, "POST", "/api/v1/auth/demo-login", demo_headers(), payload
        )
        assert status == 503
        assert json.loads(raw.decode()) == {"error": "not_configured"}
        assert "mdt-pw-correct-horse-03" not in raw.decode()
        assert "demo.mdt" not in raw.decode()


def test_password_login_demo_username_wrong_role_fails_closed(tmp_path: Path) -> None:
    now = [10000000]
    svc = make_service(tmp_path, now)
    svc.provision_user("demo.lekar", "lekar-pw-correct-horse-02", "viewer")
    demo = load_demo_login_file(write_mapping(tmp_path))
    config = WebConfig.build(ORIGIN, True)
    login, resolve, csrf_for, logout = build_login_callables(svc)
    issued: list[str] = []

    def recording(username: str, password: str) -> tuple[str, VerifiedIdentity, str]:
        token, identity, csrf = login(username, password)
        issued.append(token)
        return (token, identity, csrf)

    router = AuthHTTPRouter(config, PROXY, recording, resolve, csrf_for, logout, demo=demo)
    for host, port in live(router):
        payload = json.dumps(
            {"username": "demo.lekar", "password": "lekar-pw-correct-horse-02"}
        ).encode()
        status, headers, raw = request(
            host, port, "POST", "/api/v1/auth/login", demo_headers(), payload
        )
        assert status == 401
        assert json.loads(raw.decode()) == {"error": "invalid_credentials"}
        assert "set-cookie" not in headers
        assert headers.get("cache-control") == "no-store"
        assert len(issued) == 1
        stale = {"X-Rakathon-Proxy-Key": PROXY, "Cookie": f"{COOKIE_LOOPBACK}={issued[0]}"}
        status, _, _ = request(host, port, "GET", "/api/v1/auth/session", stale)
        assert status == 401


def test_session_refresh_demo_username_wrong_role_fails_closed(tmp_path: Path) -> None:
    now = [11000000]
    svc = make_service(tmp_path, now)
    provision_all(svc)
    demo = load_demo_login_file(write_mapping(tmp_path))
    config = WebConfig.build(ORIGIN, True)
    login, _, _csrf_for, logout = build_login_callables(svc)
    _ = _csrf_for
    revoked: list[str] = []

    def record_logout(token: str) -> None:
        revoked.append(token)
        logout(token)

    def wrong_role_resolve(token: str) -> VerifiedIdentity:
        _ = token
        return VerifiedIdentity(
            user_id="u" * 32, username="demo.pacient", role="coordinator", auth_version=1
        )

    def fake_csrf(token: str) -> str:
        _ = token
        return "c" * 64

    router = AuthHTTPRouter(
        config, PROXY, login, wrong_role_resolve, fake_csrf, record_logout, demo=demo
    )
    for host, port in live(router):
        stale = {"X-Rakathon-Proxy-Key": PROXY, "Cookie": f"{COOKIE_LOOPBACK}={'T' * 43}"}
        status, headers, raw = request(host, port, "GET", "/api/v1/auth/session", stale)
        assert status == 401
        assert json.loads(raw.decode()) == {
            "authenticated": False,
            "demoAccounts": ["koordinator", "lekar", "mdt", "pacient"],
            "error": "invalid_credentials",
        }
        assert revoked == ["T" * 43]
        assert headers.get("set-cookie", "").startswith(f"{COOKIE_LOOPBACK}=deleted")
        assert "Max-Age=0" in headers.get("set-cookie", "")


def test_b7_role_change_revokes_demo_session(tmp_path: Path) -> None:
    now = [12000000]
    svc = make_service(tmp_path, now)
    provision_all(svc)
    demo = load_demo_login_file(write_mapping(tmp_path))
    router = make_router(svc, demo)
    for host, port in live(router):
        payload = json.dumps({"account": "mdt"}).encode()
        status, headers, raw = request(
            host, port, "POST", "/api/v1/auth/demo-login", demo_headers(), payload
        )
        assert status == 200
        body = json.loads(raw.decode())
        assert body["demoView"] == "mdt"
        token = headers["set-cookie"].split("=", 1)[1].split(";")[0].strip()
        authed = svc.resolve(token)
        svc.set_role(authed.user_id, "viewer")
        stale = {"X-Rakathon-Proxy-Key": PROXY, "Cookie": f"{COOKIE_LOOPBACK}={token}"}
        status, headers, raw = request(host, port, "GET", "/api/v1/auth/session", stale)
        assert status == 401
        assert json.loads(raw.decode()) == {
            "authenticated": False,
            "demoAccounts": ["koordinator", "lekar", "mdt", "pacient"],
            "error": "invalid_credentials",
        }
        assert headers.get("set-cookie", "").startswith(f"{COOKIE_LOOPBACK}=deleted")
