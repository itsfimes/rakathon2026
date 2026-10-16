from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from rakathon_backend.b2.auth.keys import generate_key_file
from rakathon_backend.b2.auth.sqlite_store import SQLiteDemoAuthStore
from rakathon_backend.b2.memory import MemoryStorage
from rakathon_backend.b7.provider import LocalPasswordProvider
from rakathon_backend.b7.service import AuthService
from rakathon_backend.common.contracts import Envelope
from rakathon_backend.common.errors import AuthError, ContractError, TransportError
from rakathon_backend.runtime.application import BackendApp
from rakathon_backend.runtime.auth_bundle import build_auth_app, fresh_tokens_with_auth
from rakathon_backend.web.config import COOKIE_LOOPBACK, WebConfig
from rakathon_backend.web.edge import (
    AuthMiddleware,
    B4ActionClient,
    build_login_callables,
    make_b4_action_client,
)
from rakathon_backend.web.router import AuthHTTPRouter, VerifiedIdentity

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


async def launch(tmp_path: Path) -> dict[str, Any]:
    now = [1000000]
    svc = make_service(tmp_path, now)
    viewer = svc.provision_user("jane.doe", PW, "viewer")
    coord = svc.provision_user("john.smith", PW, "coordinator")
    store = MemoryStorage()
    store.tasks_create(
        {
            "id": "t1",
            "ownerId": coord.user_id,
            "dueAt": "2030-01-01T00:00:00+00:00",
            "status": "OPEN",
            "requiredAckUserIds": [coord.user_id],
            "acknowledgedBy": [],
            "patientRef": "Patient/p1",
            "version": 1,
        }
    )
    runtime = tmp_path / "rt"
    runtime.mkdir(mode=0o700)
    tokens = fresh_tokens_with_auth()
    app = build_auth_app(runtime, tokens, svc, store=store, mode="mock")
    await app.start()
    client = make_b4_action_client(runtime, tokens["web:auth"])
    assert isinstance(client, B4ActionClient)
    assert repr(client) == "B4ActionClient()"
    live: dict[str, Any] = {
        "app": app,
        "client": client,
        "store": store,
        "svc": svc,
        "viewer": VerifiedIdentity(
            user_id=viewer.user_id,
            username="jane.doe",
            role="viewer",
            auth_version=1,
        ),
        "coord": VerifiedIdentity(
            user_id=coord.user_id,
            username="john.smith",
            role="coordinator",
            auth_version=1,
        ),
    }
    return live


async def land(live: dict[str, Any]) -> None:
    app = live["app"]
    assert isinstance(app, BackendApp)
    await app.close()


async def invoke(
    client: B4ActionClient, identity: VerifiedIdentity, action: str, payload: dict[str, Any]
) -> Envelope:
    return await asyncio.to_thread(client.call, identity, action, payload)


async def test_b4_forwards_exact_requested_actions(tmp_path: Path) -> None:
    live = await launch(tmp_path)
    try:
        client = live["client"]
        assert isinstance(client, B4ActionClient)
        coord = live["coord"]
        assert isinstance(coord, VerifiedIdentity)
        reply = await invoke(client, coord, "tasks.read", {})
        assert reply.source == "b4"
        assert reply.action == "tasks.read"
        assert reply.payload["count"] == 1
        reply = await invoke(client, coord, "fhir.search", {"resourceType": "Patient"})
        assert reply.action == "fhir.search"
        assert reply.payload["bundle"]["total"] == 0
        reply = await invoke(client, coord, "fhir.read", {"resourceType": "Patient", "id": "p9"})
        assert reply.action == "fhir.read"
        assert reply.payload["bundle"]["total"] == 0
        reply = await invoke(client, coord, "health", {})
        assert reply.action == "health"
        assert reply.payload["service"] == "b4"
    finally:
        await land(live)


async def test_b4_coordinator_sees_own_viewer_sees_none(tmp_path: Path) -> None:
    live = await launch(tmp_path)
    try:
        client = live["client"]
        assert isinstance(client, B4ActionClient)
        coord = live["coord"]
        viewer = live["viewer"]
        assert isinstance(coord, VerifiedIdentity)
        assert isinstance(viewer, VerifiedIdentity)
        reply = await invoke(client, coord, "tasks.read", {})
        assert reply.payload["count"] == 1
        reply = await invoke(client, viewer, "tasks.read", {})
        assert reply.payload["count"] == 0
    finally:
        await land(live)


async def test_b4_rejects_authority_fields_and_unknown_action(tmp_path: Path) -> None:
    live = await launch(tmp_path)
    try:
        client = live["client"]
        assert isinstance(client, B4ActionClient)
        coord = live["coord"]
        assert isinstance(coord, VerifiedIdentity)
        with pytest.raises(ContractError):
            await invoke(client, coord, "tasks.read", {"role": "admin"})
        with pytest.raises(ContractError):
            await invoke(client, coord, "tasks.read", {"userId": "someone"})
        with pytest.raises(ContractError):
            await invoke(client, coord, "clinical.project", {})
    finally:
        await land(live)


async def test_b4_viewer_write_denied_before_storage(tmp_path: Path) -> None:
    live = await launch(tmp_path)
    try:
        client = live["client"]
        assert isinstance(client, B4ActionClient)
        viewer = live["viewer"]
        assert isinstance(viewer, VerifiedIdentity)
        task = {
            "id": "evil",
            "ownerId": viewer.user_id,
            "dueAt": "2030-01-01T00:00:00+00:00",
            "status": "OPEN",
            "requiredAckUserIds": [viewer.user_id],
            "acknowledgedBy": [],
            "patientRef": "Patient/p1",
            "version": 1,
        }
        with pytest.raises(AuthError):
            await invoke(client, viewer, "tasks.write", task)
        store = live["store"]
        assert isinstance(store, MemoryStorage)
        assert store.tasks_read("evil") == []
    finally:
        await land(live)


async def test_b4_client_surfaces_transport_without_socket(tmp_path: Path) -> None:
    runtime = tmp_path / "empty"
    runtime.mkdir(mode=0o700)
    client = make_b4_action_client(runtime, "T" * 43)
    identity = VerifiedIdentity(user_id="u", username="x.y", role="viewer", auth_version=1)
    with pytest.raises((TransportError, ContractError, AuthError, OSError)):
        await asyncio.to_thread(client.call, identity, "tasks.read", {})
    with pytest.raises(ValueError):
        make_b4_action_client("https://example.com/run", "T" * 43)


async def test_clinical_default_503_without_b4_network(tmp_path: Path) -> None:
    now = [2000000]
    svc = make_service(tmp_path, now)
    svc.provision_user("jane.doe", PW, "viewer")
    config = WebConfig.build(ORIGIN, True)
    router = AuthHTTPRouter(config, PROXY, *build_login_callables(svc))
    middleware = AuthMiddleware(router)
    body = {"username": "jane.doe", "password": PW}
    status, headers, payload = router.handle(
        "POST",
        "/api/v1/auth/login",
        {
            "x-rakathon-proxy-key": PROXY,
            "origin": ORIGIN,
            "x-rakathon-auth": "1",
            "content-type": "application/json",
        },
        json.dumps(body).encode(),
    )
    assert status == 200
    cookie = headers["Set-Cookie"].split("=", 1)[1].split(";")[0].strip()
    assert cookie not in json.dumps(payload)
    clinical = {
        "x-rakathon-proxy-key": PROXY,
        "cookie": f"{COOKIE_LOOPBACK}={cookie}",
    }
    status, _, payload = router.handle("GET", "/api/v1/session", clinical, None)
    assert status == 503
    assert payload == {"error": "not_configured"}

    def probe(
        identity: VerifiedIdentity, method: str, path: str, clean: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        _ = (identity, method, clean)
        return (200, {"served": path})

    middleware.protect(probe)
    status, _, payload = router.handle("GET", "/api/v1/session", clinical, None)
    assert status == 200
    assert payload == {"served": "/api/v1/session"}
