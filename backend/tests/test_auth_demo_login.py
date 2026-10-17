from __future__ import annotations

import json
from pathlib import Path

from auth_demo_http_helpers import (
    ACCOUNTS,
    cookie_of,
    demo_headers,
    live,
    make_router,
    make_service,
    provision_all,
    request,
    write_mapping,
)

from rakathon_backend.web.config import COOKIE_LOOPBACK
from rakathon_backend.web.demo_login import DEMO_ACCOUNT_IDS, load_demo_login_file


def test_off_by_default_404_and_unchanged_shapes(tmp_path: Path) -> None:
    now = [1000000]
    svc = make_service(tmp_path, now)
    svc.provision_user("jane.doe", "correct-horse-battery-staple-x", "viewer")
    router = make_router(svc)
    for host, port in live(router):
        payload = json.dumps({"account": "lekar"}).encode()
        status, headers, raw = request(
            host, port, "POST", "/api/v1/auth/demo-login", demo_headers(), payload
        )
        assert status == 404
        assert json.loads(raw.decode()) == {"error": "not_found"}
        assert headers.get("cache-control") == "no-store"
        status, headers, raw = request(
            host, port, "GET", "/api/v1/auth/session", {"X-Rakathon-Proxy-Key": "K" * 43}
        )
        assert status == 200
        assert json.loads(raw.decode()) == {"authenticated": False}
        assert headers.get("cache-control") == "no-store"
        login_body = json.dumps(
            {"username": "jane.doe", "password": "correct-horse-battery-staple-x"}
        ).encode()
        status, headers, raw = request(
            host, port, "POST", "/api/v1/auth/login", demo_headers(), login_body
        )
        assert status == 200
        body = json.loads(raw.decode())
        assert "demoAccounts" not in body
        assert "demoView" not in body
        assert set(body.keys()) == {"authenticated", "user", "csrfToken"}
        assert headers.get("cache-control") == "no-store"


def test_demo_session_anon_lists_accounts(tmp_path: Path) -> None:
    now = [2000000]
    svc = make_service(tmp_path, now)
    demo = load_demo_login_file(write_mapping(tmp_path))
    router = make_router(svc, demo)
    for host, port in live(router):
        status, headers, raw = request(
            host, port, "GET", "/api/v1/auth/session", {"X-Rakathon-Proxy-Key": "K" * 43}
        )
        assert status == 200
        assert json.loads(raw.decode()) == {
            "authenticated": False,
            "demoAccounts": ["koordinator", "lekar", "mdt", "pacient"],
        }
        assert headers.get("cache-control") == "no-store"


def test_demo_login_closed_gates(tmp_path: Path) -> None:
    now = [3000000]
    svc = make_service(tmp_path, now)
    provision_all(svc)
    demo = load_demo_login_file(write_mapping(tmp_path))
    router = make_router(svc, demo)
    for host, port in live(router):
        payload = json.dumps({"account": "lekar"}).encode()
        bad_proxy = demo_headers({"X-Rakathon-Proxy-Key": "0" * 43})
        status, _, _ = request(host, port, "POST", "/api/v1/auth/demo-login", bad_proxy, payload)
        assert status == 401
        bad_origin = demo_headers({"Origin": "http://evil.example"})
        status, _, _ = request(host, port, "POST", "/api/v1/auth/demo-login", bad_origin, payload)
        assert status == 403
        no_custom = demo_headers()
        del no_custom["X-Rakathon-Auth"]
        status, _, _ = request(host, port, "POST", "/api/v1/auth/demo-login", no_custom, payload)
        assert status == 401
        bad_type = demo_headers({"Content-Type": "text/plain"})
        status, _, raw = request(host, port, "POST", "/api/v1/auth/demo-login", bad_type, payload)
        assert status == 400
        assert json.loads(raw.decode()) == {"error": "bad_request"}
        for bad_body in (
            b"",
            b"not-json",
            json.dumps(["lekar"]).encode(),
            json.dumps({"account": "unknown"}).encode(),
            json.dumps({"account": 1}).encode(),
            json.dumps({"account": "lekar", "extra": 1}).encode(),
            json.dumps({"username": "demo.lekar", "password": "x"}).encode(),
            json.dumps({}).encode(),
        ):
            status, headers, raw = request(
                host, port, "POST", "/api/v1/auth/demo-login", demo_headers(), bad_body
            )
            assert status == 400
            assert json.loads(raw.decode()) == {"error": "bad_request"}
            assert "set-cookie" not in headers
            assert headers.get("cache-control") == "no-store"
        status, _, _ = request(
            host, port, "GET", "/api/v1/auth/demo-login", {"X-Rakathon-Proxy-Key": "K" * 43}
        )
        assert status == 404


def test_all_four_real_sessions_reload_logout(tmp_path: Path) -> None:
    now = [4000000]
    svc = make_service(tmp_path, now)
    provision_all(svc)
    demo = load_demo_login_file(write_mapping(tmp_path))
    router = make_router(svc, demo)
    for host, port in live(router):
        for account in DEMO_ACCOUNT_IDS:
            username, role, _ = ACCOUNTS[account]
            payload = json.dumps({"account": account}).encode()
            status, headers, raw = request(
                host, port, "POST", "/api/v1/auth/demo-login", demo_headers(), payload
            )
            assert status == 200
            body = json.loads(raw.decode())
            assert body["authenticated"] is True
            assert body["user"]["username"] == username
            assert body["user"]["role"] == role
            assert body["demoAccounts"] == ["koordinator", "lekar", "mdt", "pacient"]
            assert body["demoView"] == account
            assert len(body["csrfToken"]) == 64
            assert headers.get("cache-control") == "no-store"
            token = cookie_of(headers)
            assert token not in raw.decode()
            session_headers = {
                "X-Rakathon-Proxy-Key": "K" * 43,
                "Cookie": f"{COOKIE_LOOPBACK}={token}",
            }
            status, headers, raw = request(
                host, port, "GET", "/api/v1/auth/session", session_headers
            )
            assert status == 200
            reloaded = json.loads(raw.decode())
            assert reloaded["authenticated"] is True
            assert reloaded["user"]["username"] == username
            assert reloaded["demoView"] == account
            assert reloaded["demoAccounts"] == ["koordinator", "lekar", "mdt", "pacient"]
            assert headers.get("cache-control") == "no-store"
            logout_headers = dict(session_headers)
            logout_headers.update(
                {
                    "Origin": "http://127.0.0.1:5173",
                    "X-CSRF-Token": body["csrfToken"],
                    "Content-Length": "0",
                }
            )
            status, headers, _ = request(
                host, port, "POST", "/api/v1/auth/logout", logout_headers, b""
            )
            assert status == 204
            assert headers.get("cache-control") == "no-store"
            status, _, raw = request(host, port, "GET", "/api/v1/auth/session", session_headers)
            assert status == 401


def test_password_login_keeps_working_with_demo_view(tmp_path: Path) -> None:
    now = [5000000]
    svc = make_service(tmp_path, now)
    provision_all(svc)
    svc.provision_user("jane.doe", "correct-horse-battery-staple-x", "viewer")
    demo = load_demo_login_file(write_mapping(tmp_path))
    router = make_router(svc, demo)
    for host, port in live(router):
        payload = json.dumps({"username": "demo.mdt", "password": ACCOUNTS["mdt"][2]}).encode()
        status, _, raw = request(host, port, "POST", "/api/v1/auth/login", demo_headers(), payload)
        assert status == 200
        body = json.loads(raw.decode())
        assert body["demoView"] == "mdt"
        assert body["demoAccounts"] == ["koordinator", "lekar", "mdt", "pacient"]
        other = json.dumps(
            {"username": "jane.doe", "password": "correct-horse-battery-staple-x"}
        ).encode()
        status, _, raw = request(host, port, "POST", "/api/v1/auth/login", demo_headers(), other)
        assert status == 200
        plain = json.loads(raw.decode())
        assert "demoView" not in plain
        assert plain["demoAccounts"] == ["koordinator", "lekar", "mdt", "pacient"]
