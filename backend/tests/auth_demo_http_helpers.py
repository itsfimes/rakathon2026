from __future__ import annotations

import http.client
import json
import os
import threading
from collections.abc import Iterator
from pathlib import Path

from rakathon_backend.b2.auth.keys import generate_key_file
from rakathon_backend.b2.auth.sqlite_store import SQLiteDemoAuthStore
from rakathon_backend.b7.provider import LocalPasswordProvider
from rakathon_backend.b7.service import AuthService
from rakathon_backend.web.config import WebConfig
from rakathon_backend.web.demo_login import DEMO_ACCOUNT_IDS, DemoLoginConfig
from rakathon_backend.web.edge import build_login_callables
from rakathon_backend.web.router import AuthHTTPRouter
from rakathon_backend.web.server import build_server, serve_forever

PROXY = "K" * 43
ORIGIN = "http://127.0.0.1:5173"
ACCOUNTS: dict[str, tuple[str, str, str]] = {
    "koordinator": ("demo.koordinator", "coordinator", "koordinator-pw-correct-horse-01"),
    "lekar": ("demo.lekar", "clinician", "lekar-pw-correct-horse-02"),
    "mdt": ("demo.mdt", "clinician", "mdt-pw-correct-horse-03"),
    "pacient": ("demo.pacient", "viewer", "pacient-pw-correct-horse-04"),
}


def make_service(
    tmp_path: Path, now: list[int], account_limit: int = 10, global_limit: int = 100
) -> AuthService:
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir(mode=0o700, exist_ok=True)
    os.chmod(auth_dir, 0o700)
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
        global_limit=global_limit,
    )


def write_mapping(tmp_path: Path, name: str = "demo-login.json") -> Path:
    payload = {
        account: {"username": ACCOUNTS[account][0], "password": ACCOUNTS[account][2]}
        for account in DEMO_ACCOUNT_IDS
    }
    parent = tmp_path / "demo-dir"
    parent.mkdir(exist_ok=True)
    os.chmod(parent, 0o700)
    target = parent / name
    target.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(target, 0o600)
    return target


def make_router(
    svc: AuthService, demo: DemoLoginConfig | None = None, origin: str = ORIGIN
) -> AuthHTTPRouter:
    config = WebConfig.build(origin, True)
    login, resolve, csrf_for, logout = build_login_callables(svc)
    return AuthHTTPRouter(config, PROXY, login, resolve, csrf_for, logout, demo=demo)


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


def demo_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    base = {
        "Content-Type": "application/json",
        "X-Rakathon-Proxy-Key": PROXY,
        "Origin": ORIGIN,
        "X-Rakathon-Auth": "1",
    }
    if extra:
        base.update(extra)
    return base


def provision_all(svc: AuthService) -> None:
    for account in DEMO_ACCOUNT_IDS:
        username, role, password = ACCOUNTS[account]
        svc.provision_user(username, password, role)


def cookie_of(headers: dict[str, str]) -> str:
    return headers["set-cookie"].split("=", 1)[1].split(";")[0].strip()
