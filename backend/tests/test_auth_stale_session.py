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

from rakathon_backend.web.config import COOKIE_LOOPBACK, WebConfig
from rakathon_backend.web.demo_login import load_demo_login_file
from rakathon_backend.web.edge import build_login_callables
from rakathon_backend.web.router import AuthHTTPRouter, VerifiedIdentity

EXPECTED = {
    "authenticated": False,
    "demoAccounts": ["koordinator", "lekar", "mdt", "pacient"],
    "error": "invalid_credentials",
}


def stale_headers(token: str) -> dict[str, str]:
    return {"X-Rakathon-Proxy-Key": PROXY, "Cookie": f"{COOKIE_LOOPBACK}={token}"}


def test_no_cookie_lists_public_accounts(tmp_path: Path) -> None:
    svc = make_service(tmp_path, [1000000])
    demo = load_demo_login_file(write_mapping(tmp_path))
    router = make_router(svc, demo)
    for host, port in live(router):
        status, headers, raw = request(
            host, port, "GET", "/api/v1/auth/session", {"X-Rakathon-Proxy-Key": PROXY}
        )
        assert status == 200
        assert json.loads(raw.decode()) == {
            "authenticated": False,
            "demoAccounts": ["koordinator", "lekar", "mdt", "pacient"],
        }
        assert "set-cookie" not in headers
        assert headers.get("cache-control") == "no-store"


def test_invalid_format_cookie_clears_and_lists_accounts(tmp_path: Path) -> None:
    svc = make_service(tmp_path, [2000000])
    demo = load_demo_login_file(write_mapping(tmp_path))
    router = make_router(svc, demo)
    for host, port in live(router):
        status, headers, raw = request(
            host, port, "GET", "/api/v1/auth/session", stale_headers("!!!not-valid!!!")
        )
        assert status == 401
        assert json.loads(raw.decode()) == EXPECTED
        assert headers.get("set-cookie", "").startswith(f"{COOKIE_LOOPBACK}=deleted")
        assert "Max-Age=0" in headers.get("set-cookie", "")
        assert headers.get("cache-control") == "no-store"


def test_wellformed_unknown_token_clears_and_lists_accounts(tmp_path: Path) -> None:
    svc = make_service(tmp_path, [3000000])
    demo = load_demo_login_file(write_mapping(tmp_path))
    router = make_router(svc, demo)
    for host, port in live(router):
        status, headers, raw = request(
            host, port, "GET", "/api/v1/auth/session", stale_headers("T" * 43)
        )
        assert status == 401
        assert json.loads(raw.decode()) == EXPECTED
        assert headers.get("set-cookie", "").startswith(f"{COOKIE_LOOPBACK}=deleted")
        assert "Max-Age=0" in headers.get("set-cookie", "")
        assert headers.get("cache-control") == "no-store"


def test_revoked_token_clears_and_lists_accounts(tmp_path: Path) -> None:
    now = [4000000]
    svc = make_service(tmp_path, now)
    provision_all(svc)
    demo = load_demo_login_file(write_mapping(tmp_path))
    router = make_router(svc, demo)
    for host, port in live(router):
        payload = json.dumps({"account": "lekar"}).encode()
        status, headers, raw = request(
            host, port, "POST", "/api/v1/auth/demo-login", demo_headers(), payload
        )
        assert status == 200
        body = json.loads(raw.decode())
        token = headers["set-cookie"].split("=", 1)[1].split(";")[0].strip()
        csrf = body["csrfToken"]
        logout_headers = dict(stale_headers(token))
        logout_headers.update({"Origin": ORIGIN, "X-CSRF-Token": csrf, "Content-Length": "0"})
        status, _, _ = request(host, port, "POST", "/api/v1/auth/logout", logout_headers, b"")
        assert status == 204
        status, headers, raw = request(
            host, port, "GET", "/api/v1/auth/session", stale_headers(token)
        )
        assert status == 401
        assert json.loads(raw.decode()) == EXPECTED
        assert headers.get("set-cookie", "").startswith(f"{COOKIE_LOOPBACK}=deleted")
        assert "Max-Age=0" in headers.get("set-cookie", "")


def test_configured_wrong_role_lists_accounts_and_clears(tmp_path: Path) -> None:
    svc = make_service(tmp_path, [5000000])
    provision_all(svc)
    demo = load_demo_login_file(write_mapping(tmp_path))
    config = WebConfig.build(ORIGIN, True)
    login, _, _, logout = build_login_callables(svc)

    def wrong_role_resolve(token: str) -> VerifiedIdentity:
        _ = token
        return VerifiedIdentity(
            user_id="u" * 32, username="demo.pacient", role="coordinator", auth_version=1
        )

    def fake_csrf(token: str) -> str:
        _ = token
        return "c" * 64

    router = AuthHTTPRouter(config, PROXY, login, wrong_role_resolve, fake_csrf, logout, demo=demo)
    for host, port in live(router):
        status, headers, raw = request(
            host, port, "GET", "/api/v1/auth/session", stale_headers("T" * 43)
        )
        assert status == 401
        assert json.loads(raw.decode()) == EXPECTED
        assert headers.get("set-cookie", "").startswith(f"{COOKIE_LOOPBACK}=deleted")
        assert "Max-Age=0" in headers.get("set-cookie", "")


def test_default_off_wire_stays_compatible(tmp_path: Path) -> None:
    svc = make_service(tmp_path, [6000000])
    svc.provision_user("jane.doe", "correct-horse-battery-staple-x", "viewer")
    router = make_router(svc)
    for host, port in live(router):
        status, headers, raw = request(
            host, port, "GET", "/api/v1/auth/session", {"X-Rakathon-Proxy-Key": PROXY}
        )
        assert status == 200
        assert json.loads(raw.decode()) == {"authenticated": False}
        status, headers, raw = request(
            host, port, "GET", "/api/v1/auth/session", stale_headers("!!!not-valid!!!")
        )
        assert status == 401
        assert json.loads(raw.decode()) == {"error": "invalid_credentials"}
        assert "set-cookie" not in headers
        status, headers, raw = request(
            host, port, "GET", "/api/v1/auth/session", stale_headers("T" * 43)
        )
        assert status == 401
        assert json.loads(raw.decode()) == {"error": "invalid_credentials"}
        assert "set-cookie" not in headers
