from __future__ import annotations

import asyncio
import json
import secrets
from pathlib import Path
from typing import Any

from rakathon_backend.b2.auth.keys import generate_key_file
from rakathon_backend.b2.auth.sqlite_store import SQLiteDemoAuthStore
from rakathon_backend.b2.memory import MemoryStorage
from rakathon_backend.b4.router import web_envelope
from rakathon_backend.b5.gateway import MockAdapter
from rakathon_backend.b7.provider import LocalPasswordProvider
from rakathon_backend.b7.service import AuthService
from rakathon_backend.common.contracts import DataKind
from rakathon_backend.common.errors import AuthError
from rakathon_backend.common.rpc import new_envelope
from rakathon_backend.runtime.auth_bundle import (
    WEB_SOURCE,
    build_auth_app,
    fresh_tokens_with_auth,
)
from rakathon_backend.web.auth_bridge import AuthBridge, binding_key_for
from rakathon_backend.web.config import COOKIE_LOOPBACK, WebConfig
from rakathon_backend.web.edge import build_login_callables
from rakathon_backend.web.router import AuthHTTPRouter

PW = "correct-horse-battery-staple-x"
PROXY = "K" * 43
ORIGIN = "http://127.0.0.1:5173"


class FakeAI:
    async def translate(self, data: bytes, content_type: str) -> dict[str, Any]:
        return {"answer": "unused"}

    async def complete(self, data: bytes, content_type: str) -> dict[str, Any]:
        return {"answer": "Synthetic answer"}

    async def close(self) -> None:
        return None


def make_service(tmp_path: Path) -> AuthService:
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir(mode=0o700)
    keys = generate_key_file(auth_dir / "auth.authkey")
    store = SQLiteDemoAuthStore(auth_dir / "users.auth.db")
    store.init_schema()
    provider = LocalPasswordProvider(time_cost=2, memory_cost=19456, parallelism=1)
    return AuthService(store=store, keys=keys, provider=provider)


def seed_patient(store: MemoryStorage) -> None:
    store.fhir_write(
        {
            "resourceType": "Patient",
            "id": "synthetic-1",
            "name": [{"given": ["Synthetic"], "family": "Example"}],
        }
    )


async def make_stack(
    tmp_path: Path, ai_mode: str = "mock", assistant: bool = False
) -> dict[str, Any]:
    svc = make_service(tmp_path)
    viewer = svc.provision_user("viewer.one", PW, "viewer")
    clinician = svc.provision_user("clinician.one", PW, "clinician")
    admin = svc.provision_user("admin.one", PW, "admin")
    store = MemoryStorage()
    seed_patient(store)
    tokens = fresh_tokens_with_auth()
    adapter: Any = (
        FakeAI() if ai_mode == "direct" else (MockAdapter() if ai_mode != "mock" else None)
    )
    app = build_auth_app(
        tmp_path / "rt",
        tokens,
        svc,
        store=store,
        mode="iris-fhir",
        ai_adapter=adapter,
        ai_mode=ai_mode,
    )
    await app.start()
    root = secrets.token_bytes(32)
    bridge = AuthBridge(
        tmp_path / "rt",
        tokens[WEB_SOURCE],
        root,
        assistant_enabled=assistant,
        assistant_ready=lambda: app.gateway is not None and app.gateway.mode == "direct",
    )
    config = WebConfig.build(ORIGIN, True)
    login, resolve, csrf_for, logout = build_login_callables(svc)
    router = AuthHTTPRouter(config, PROXY, login, resolve, csrf_for, logout)
    router.set_protected(bridge.protected)
    return {
        "svc": svc,
        "app": app,
        "bridge": bridge,
        "router": router,
        "tokens": tokens,
        "root": root,
        "viewer": viewer,
        "clinician": clinician,
        "admin": admin,
        "login": login,
    }


def auth_headers(token: str, csrf: str | None = None, body: bytes | None = None) -> dict[str, str]:
    headers = {
        "X-Rakathon-Proxy-Key": PROXY,
        "Host": "127.0.0.1:8765",
        "Cookie": f"{COOKIE_LOOPBACK}={token}",
        "Origin": ORIGIN,
    }
    if csrf is not None:
        headers["X-CSRF-Token"] = csrf
    if body is not None:
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(body))
    return headers


async def call_router(
    router: AuthHTTPRouter, method: str, path: str, headers: dict[str, str], body: bytes | None
) -> tuple[int, dict[str, Any]]:
    status, _, payload = await asyncio.to_thread(router.handle, method, path, headers, body)
    return (status, payload)


async def login_pair(stack: dict[str, Any], username: str) -> tuple[str, str]:
    login = stack["login"]
    token, _, csrf = await asyncio.to_thread(login, username, PW)
    return (token, csrf)


async def test_anon_clinical_401(tmp_path: Path) -> None:
    stack = await make_stack(tmp_path)
    try:
        router = stack["router"]
        status, _ = await call_router(
            router, "GET", "/api/v1/session", {"X-Rakathon-Proxy-Key": PROXY}, None
        )
        assert status == 401
        status, _ = await call_router(
            router, "GET", "/api/v1/workspace", {"X-Rakathon-Proxy-Key": PROXY}, None
        )
        assert status == 401
    finally:
        await stack["app"].close()


async def test_viewer_clinical_200_opaque_uid(tmp_path: Path) -> None:
    stack = await make_stack(tmp_path)
    try:
        router = stack["router"]
        token, _ = await login_pair(stack, "viewer.one")
        headers = auth_headers(token)
        status, session = await call_router(router, "GET", "/api/v1/session", headers, None)
        assert status == 200 and session["version"] == 1
        assert session["capabilities"]["assistant"] is False
        status, workspace = await call_router(router, "GET", "/api/v1/workspace", headers, None)
        assert status == 200 and workspace["version"] == 1
        assert workspace["patients"][0]["patientId"] == "synthetic-1"
        status, case = await call_router(router, "GET", "/api/v1/cases/synthetic-1", headers, None)
        assert status == 200 and case["patient"]["id"] == "synthetic-1"
        viewer = stack["viewer"]
        assert viewer.user_id != "viewer" and len(viewer.user_id) == 32
        assert "assistantPreview" not in case
    finally:
        await stack["app"].close()


async def test_parallel_isolated_and_cross_user_409(tmp_path: Path) -> None:
    stack = await make_stack(tmp_path, ai_mode="direct", assistant=True)
    try:
        router = stack["router"]
        token_c, csrf_c = await login_pair(stack, "clinician.one")
        token_a, csrf_a = await login_pair(stack, "admin.one")
        headers_c = auth_headers(token_c)
        headers_a = auth_headers(token_a)
        status_c, case_c = await call_router(
            router, "GET", "/api/v1/cases/synthetic-1", headers_c, None
        )
        status_a, _ = await call_router(router, "GET", "/api/v1/cases/synthetic-1", headers_a, None)
        assert status_c == 200 and status_a == 200
        assert "assistantPreview" in case_c
        preview = case_c["assistantPreview"]["pacient"]
        good = {"role": "pacient", "text": "Explain supplied metadata", **preview}
        body = json.dumps(good).encode()
        status, resp = await call_router(
            router, "POST", "/api/v1/assistant", auth_headers(token_c, csrf_c, body), body
        )
        assert status == 200 and resp["text"] == "Synthetic answer"
        assert resp["provenance"] == "server"
        cross = {"role": "pacient", "text": "Explain supplied metadata", **preview}
        cross_body = json.dumps(cross).encode()
        status, resp = await call_router(
            router,
            "POST",
            "/api/v1/assistant",
            auth_headers(token_a, csrf_a, cross_body),
            cross_body,
        )
        assert status == 409
        assert "Synthetic" not in json.dumps(resp)
    finally:
        await stack["app"].close()


async def test_viewer_assistant_403_before_ai(tmp_path: Path) -> None:
    stack = await make_stack(tmp_path, ai_mode="direct", assistant=True)
    try:
        router = stack["router"]
        token_v, csrf_v = await login_pair(stack, "viewer.one")
        token_c, _csrf_c = await login_pair(stack, "clinician.one")
        headers_c = auth_headers(token_c)
        _, case = await call_router(router, "GET", "/api/v1/cases/synthetic-1", headers_c, None)
        preview = case["assistantPreview"]["pacient"]
        good = {"role": "pacient", "text": "Question", **preview}
        body = json.dumps(good).encode()
        status, _ = await call_router(
            router, "POST", "/api/v1/assistant", auth_headers(token_v, csrf_v, body), body
        )
        assert status == 403
    finally:
        await stack["app"].close()


async def test_service_principal_and_csrf_and_shape(tmp_path: Path) -> None:
    stack = await make_stack(tmp_path)
    try:
        app = stack["app"]
        router = stack["router"]
        try:
            web_envelope(stack["viewer"].user_id, "fhir.read", {"role": "admin"}, DataKind.FHIR)
            assert False
        except (ValueError, KeyError, RuntimeError):
            pass
        token_v, _ = await login_pair(stack, "viewer.one")
        status, _ = await call_router(router, "GET", "/api/v1/session", auth_headers(token_v), None)
        assert status == 200
        bad = json.dumps({"role": "pacient", "text": "Q", "userId": "x"}).encode()
        status, _ = await call_router(
            router, "POST", "/api/v1/assistant", auth_headers(token_v, "bad", bad), bad
        )
        assert status in (400, 403)
        forged = new_envelope(
            source="frontend:web-assistant",
            target="b4",
            action="fhir.read",
            data_kind=DataKind.PROPRIETARY,
            payload={},
            user_id="web-assistant",
        )
        assistant_client = app.frontend_client("web-assistant")
        try:
            await assistant_client.call(forged, expect_source="b4")
            assert False
        except AuthError:
            pass
        token_c, csrf_c = await login_pair(stack, "clinician.one")
        headers = dict(auth_headers(token_c, csrf_c, b"{}"))
        del headers["X-CSRF-Token"]
        status, _ = await call_router(router, "POST", "/api/v1/assistant", headers, b"{}")
        assert status == 403
    finally:
        await stack["app"].close()


async def test_stale_concurrency_and_mapping(tmp_path: Path) -> None:
    stack = await make_stack(tmp_path, ai_mode="direct", assistant=True)
    try:
        router = stack["router"]
        bridge = stack["bridge"]
        token_c, csrf_c = await login_pair(stack, "clinician.one")
        headers_c = auth_headers(token_c)
        _, case = await call_router(router, "GET", "/api/v1/cases/synthetic-1", headers_c, None)
        preview = case["assistantPreview"]["pacient"]
        tampered = json.loads(json.dumps(preview))
        tampered["binding"]["token"] = "1." + "0" * 64
        bad = {"role": "pacient", "text": "Q", **tampered}
        bad_body = json.dumps(bad).encode()
        status, resp = await call_router(
            router, "POST", "/api/v1/assistant", auth_headers(token_c, csrf_c, bad_body), bad_body
        )
        assert status == 409
        assert "Synthetic" not in json.dumps(resp)
        assert bridge._ai_gate.acquire(blocking=False)
        try:
            good = {"role": "pacient", "text": "Q"}
            good_body = json.dumps(good).encode()
            status, _ = await call_router(
                router,
                "POST",
                "/api/v1/assistant",
                auth_headers(token_c, csrf_c, good_body),
                good_body,
            )
            assert status == 429
        finally:
            bridge._ai_gate.release()
        status, resp = await call_router(router, "GET", "/api/v1/nope", headers_c, None)
        assert status == 404 and resp["version"] == 1
        probe_body = b"{}"
        status, _ = await call_router(
            router,
            "POST",
            "/api/v1/session",
            auth_headers(token_c, csrf_c, probe_body),
            probe_body,
        )
        assert status == 405
        status, _ = await call_router(router, "GET", "/api/v1/cases/bad id!", headers_c, None)
        assert status in (400, 404)
        key = binding_key_for(stack["root"], stack["clinician"].user_id, 1)
        assert len(key) == 32
        other = binding_key_for(stack["root"], stack["admin"].user_id, 1)
        assert key != other
    finally:
        await stack["app"].close()
