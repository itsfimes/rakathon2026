from __future__ import annotations

import asyncio
import concurrent.futures
import json
import secrets
import signal
import subprocess
import sys
import threading
from collections.abc import Awaitable, Callable
from http.client import HTTPConnection, IncompleteRead
from pathlib import Path
from typing import Any

import pytest

from rakathon_backend.b2.auth.keys import generate_key_file, load_key_file
from rakathon_backend.b2.auth.sqlite_store import SQLiteDemoAuthStore
from rakathon_backend.b7.client import B7SocketClient
from rakathon_backend.b7.handler import B7AuthHandler
from rakathon_backend.b7.provider import LocalPasswordProvider
from rakathon_backend.b7.service import AuthService
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import AuthError, ContractError
from rakathon_backend.common.ipc import UnixJsonClient, UnixJsonServer
from rakathon_backend.common.rpc import make_client, new_envelope, socket_for
from rakathon_backend.runtime.auth_bundle import WEB_SOURCE
from rakathon_backend.runtime.auth_cmds import cmd_auth_init
from rakathon_backend.web.config import WebConfig
from rakathon_backend.web.edge import build_login_callables
from rakathon_backend.web.router import AuthHTTPRouter
from rakathon_backend.web.server import build_server, serve_forever

PW = "correct-horse-battery-staple-x"
PROXY = "K" * 43
ORIGIN = "http://127.0.0.1:5173"
SEED_ID = "ab" * 16

Handler = Callable[[Envelope], Awaitable[Envelope]]


def make_service(tmp_path: Path, now: list[int], name: str = "auth") -> AuthService:
    auth_dir = tmp_path / name
    auth_dir.mkdir(mode=0o700)
    keys = generate_key_file(auth_dir / "auth.authkey")
    store = SQLiteDemoAuthStore(auth_dir / "users.auth.db")
    store.init_schema()
    provider = LocalPasswordProvider(time_cost=2, memory_cost=19456, parallelism=1)
    return AuthService(store=store, keys=keys, provider=provider, clock=lambda: now[0])


def request(
    host: str,
    port: int,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> tuple[int, dict[str, str], bytes]:
    conn = HTTPConnection(host, port, timeout=10)
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


async def over_http(
    host: str,
    port: int,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> tuple[int, dict[str, str], bytes]:
    return await asyncio.to_thread(request, host, port, method, path, headers, body)


async def fake_live(tmp_path: Path, sub: str, handler: Handler) -> dict[str, Any]:
    runtime = tmp_path / sub
    runtime.mkdir(mode=0o700)
    token = secrets.token_urlsafe(32)
    server = UnixJsonServer(
        runtime / "b7.sock",
        service_name="b7",
        token_registry={token: WEB_SOURCE},
        handler=handler,
    )
    await server.start()
    config = WebConfig.build(ORIGIN, True)
    router = AuthHTTPRouter(config, PROXY, *build_login_callables(B7SocketClient(runtime, token)))
    http_server = build_server("127.0.0.1", 0, router)
    thread = threading.Thread(target=serve_forever, args=(http_server,), daemon=True)
    thread.start()
    return {
        "host": "127.0.0.1",
        "port": int(http_server.server_address[1]),
        "server": server,
        "http": http_server,
        "thread": thread,
    }


async def fake_land(live: dict[str, Any]) -> None:
    live["http"].shutdown()
    live["thread"].join(timeout=10.0)
    live["http"].server_close()
    await live["server"].close()


def bad_handler(flavor: str) -> Handler:
    async def handle(request: Envelope) -> Envelope:
        base: dict[str, Any] = {
            "userId": "u1",
            "username": "jane.doe",
            "role": "viewer",
            "authVersion": 1,
            "sessionToken": "A" * 43,
            "csrfToken": "B" * 64,
        }
        source = "b7"
        action = request.action
        kind = DataKind.PROPRIETARY
        payload = dict(base)
        if flavor == "kind":
            kind = DataKind.METADATA
        elif flavor == "source":
            source = "b9"
        elif flavor == "action":
            action = "auth.evil"
        elif flavor == "types":
            payload = dict(base, authVersion=True, role="root")
        else:
            raise ContractError(code="bad_payload", message="shape invalid")
        return request.reply(source=source, action=action, payload=payload, data_kind=kind)

    return handle


async def test_b7_rejects_foreign_source(tmp_path: Path) -> None:
    now = [1000000]
    svc = make_service(tmp_path, now)
    svc.provision_user("jane.doe", PW, "viewer")
    runtime = tmp_path / "rtw"
    runtime.mkdir(mode=0o700)
    web_token = secrets.token_urlsafe(32)
    other_token = secrets.token_urlsafe(32)
    server = UnixJsonServer(
        runtime / "b7.sock",
        service_name="b7",
        token_registry={web_token: "web:auth", other_token: "b4"},
        handler=B7AuthHandler(svc).handle,
    )
    await server.start()
    try:
        intruder = make_client(runtime, target="b7", source="b4", token=other_token)
        attempt = new_envelope(
            source="b4",
            target="b7",
            action="auth.login",
            data_kind=DataKind.PROPRIETARY,
            payload={"username": "jane.doe", "password": PW},
        )
        with pytest.raises(AuthError):
            await intruder.call(attempt, expect_source="b7")
        spoof_client = UnixJsonClient(
            socket_for(runtime, "b7"), token=web_token, source="b4", timeout=5.0
        )
        spoof_attempt = new_envelope(
            source="b4",
            target="b7",
            action="auth.login",
            data_kind=DataKind.PROPRIETARY,
            payload={"username": "jane.doe", "password": PW},
        )
        with pytest.raises(AuthError):
            await spoof_client.call(spoof_attempt, expect_source="b7")
    finally:
        await server.close()


@pytest.mark.parametrize("flavor", ["kind", "source", "action", "types", "protocol"])
async def test_bad_b7_reply_shape_maps_503(tmp_path: Path, flavor: str) -> None:
    live = await fake_live(tmp_path, f"bad-{flavor}", bad_handler(flavor))
    try:
        host, port = str(live["host"]), int(live["port"])
        body = json.dumps({"username": "jane.doe", "password": PW}).encode()
        status, _, raw = await over_http(
            host, port, "POST", "/api/v1/auth/login", login_headers(), body
        )
        assert status == 503
        assert json.loads(raw.decode()) == {"error": "not_configured"}
        assert "jane.doe" not in raw.decode()
    finally:
        await fake_land(live)


def seed_handler() -> Handler:
    sessions: dict[str, bool] = {}

    async def handle(request: Envelope) -> Envelope:
        if request.action == "auth.login":
            token = secrets.token_urlsafe(32)
            sessions[token] = True
            return request.reply(
                source="b7",
                action="auth.login",
                payload={
                    "userId": SEED_ID,
                    "username": "seed.user",
                    "role": "viewer",
                    "authVersion": 1,
                    "sessionToken": token,
                    "csrfToken": "C" * 64,
                },
                data_kind=DataKind.PROPRIETARY,
            )
        if request.action == "auth.resolve":
            presented = request.payload.get("sessionToken")
            if not isinstance(presented, str) or presented not in sessions:
                raise AuthError(code="invalid_credentials", message="invalid credentials")
            return request.reply(
                source="b7",
                action="auth.resolve",
                payload={
                    "userId": SEED_ID,
                    "username": "seed.user",
                    "role": "viewer",
                    "authVersion": 1,
                    "csrfToken": "C" * 64,
                },
                data_kind=DataKind.PROPRIETARY,
            )
        if request.action == "auth.logout":
            finished = request.payload.get("sessionToken")
            if isinstance(finished, str):
                sessions.pop(finished, None)
            return request.reply(
                source="b7",
                action="auth.logout",
                payload={},
                data_kind=DataKind.PROPRIETARY,
            )
        raise ContractError(code="bad_action", message="unsupported action")

    return handle


async def test_fake_b7_provider_answers_http_unchanged(tmp_path: Path) -> None:
    live = await fake_live(tmp_path, "seed", seed_handler())
    try:
        host, port = str(live["host"]), int(live["port"])
        body = json.dumps({"username": "seed.user", "password": "anything-at-all"}).encode()
        status, headers, raw = await over_http(
            host, port, "POST", "/api/v1/auth/login", login_headers(), body
        )
        assert status == 200
        payload = json.loads(raw.decode())
        assert payload["user"]["id"] == SEED_ID
        assert payload["csrfToken"] == "C" * 64
        token = headers["set-cookie"].split("=", 1)[1].split(";")[0].strip()
        session_headers = {
            "X-Rakathon-Proxy-Key": PROXY,
            "Cookie": f"rakathon_session_loopback={token}",
        }
        status, _, raw = await over_http(host, port, "GET", "/api/v1/auth/session", session_headers)
        assert status == 200
        assert json.loads(raw.decode())["user"]["id"] == SEED_ID
        logout_headers = dict(session_headers)
        logout_headers.update({"Origin": ORIGIN, "X-CSRF-Token": "C" * 64, "Content-Length": "0"})
        status, _, _ = await over_http(
            host, port, "POST", "/api/v1/auth/logout", logout_headers, b""
        )
        assert status == 204
        status, _, raw = await over_http(host, port, "GET", "/api/v1/auth/session", session_headers)
        assert status == 401
    finally:
        await fake_land(live)


def burst_login(port: int, headers: dict[str, str]) -> None:
    try:
        body = json.dumps({"username": "jane.doe", "password": PW}).encode()
        request("127.0.0.1", port, "POST", "/api/v1/auth/login", headers, body)
    except (OSError, ValueError, RuntimeError, IncompleteRead):
        return


def test_burst_login_swallows_incomplete_read(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: Any, **kwargs: Any) -> tuple[int, dict[str, str], bytes]:
        raise IncompleteRead(b"partial", 8)

    monkeypatch.setattr(sys.modules[__name__], "request", _boom)
    burst_login(0, {})


def test_auth_serve_sigterm_bounded_shutdown(tmp_path: Path) -> None:
    auth_dir = tmp_path / "auth"
    assert cmd_auth_init("demo", str(auth_dir)) == 0
    keys = load_key_file(auth_dir / "auth.authkey")
    store = SQLiteDemoAuthStore(auth_dir / "users.auth.db")
    svc = AuthService(
        store=store,
        keys=keys,
        provider=LocalPasswordProvider(time_cost=2, memory_cost=19456, parallelism=1),
    )
    svc.provision_user("jane.doe", PW, "viewer")
    runtime = tmp_path / "rt"
    runtime.mkdir(mode=0o700)
    proxy = (auth_dir / "proxy.key").read_text(encoding="ascii").strip()
    headers = {**login_headers(), "X-Rakathon-Proxy-Key": proxy}
    cmd = [sys.executable, "-m", "rakathon_backend", "auth-serve", "--auth-store", "demo"]
    cmd += ["--auth-dir", str(auth_dir), "--origin", ORIGIN, "--allow-loopback-http", "--bind"]
    cmd += ["127.0.0.1", "--port", "0", "--storage", "mock", "--runtime-dir", str(runtime)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout is not None
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            line = pool.submit(proc.stdout.readline).result(timeout=90.0)
        proc.stdout.close()
        info = json.loads(line)
        assert info["serving"] is True
        port = int(info["port"])
        body = json.dumps({"username": "jane.doe", "password": PW}).encode()
        status, _, _ = request("127.0.0.1", port, "POST", "/api/v1/auth/login", headers, body)
        assert status == 200
        workers = [threading.Thread(target=burst_login, args=(port, headers)) for _ in range(4)]
        for worker in workers:
            worker.start()
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=90.0) == 0
        for worker in workers:
            worker.join(timeout=30.0)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert [p for p in runtime.glob("*.sock") if p.exists()] == []
