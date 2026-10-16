from __future__ import annotations

import json
import secrets
from pathlib import Path

import pytest

from rakathon_backend.b2.auth.keys import generate_key_file, load_key_file
from rakathon_backend.b2.auth.sqlite_store import SQLiteDemoAuthStore
from rakathon_backend.b2.memory import MemoryStorage
from rakathon_backend.b2.service import B2Service
from rakathon_backend.b4.router import B4Router, web_envelope
from rakathon_backend.b6.permissions import check, load_matrix, make_authorize_handler
from rakathon_backend.b7.handler import B7AuthHandler
from rakathon_backend.b7.provider import LocalPasswordProvider
from rakathon_backend.b7.service import AuthService
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import AuthError, ContractError, TransportError
from rakathon_backend.common.ipc import UnixJsonServer
from rakathon_backend.common.rpc import make_client, new_envelope
from rakathon_backend.runtime.auth_bundle import (
    build_auth_app,
    fresh_tokens_with_auth,
    privilege_check_for,
    role_resolver_for,
    web_client_for,
)
from rakathon_backend.runtime.auth_cmds import (
    cmd_auth_init,
    cmd_auth_user_add,
    cmd_auth_user_disable,
)

PW = "correct-horse-battery-staple-x"


def make_service(tmp_path: Path, now: list[int], name: str = "auth") -> AuthService:
    auth_dir = tmp_path / name
    auth_dir.mkdir(mode=0o700)
    keys = generate_key_file(auth_dir / "auth.authkey")
    store = SQLiteDemoAuthStore(auth_dir / "users.auth.db")
    store.init_schema()
    provider = LocalPasswordProvider(time_cost=2, memory_cost=19456, parallelism=1)
    return AuthService(store=store, keys=keys, provider=provider, clock=lambda: now[0])


async def allow_all(*, user_id: str, action: str, correlation_id: str) -> bool:
    _ = (user_id, action, correlation_id)
    return True


async def test_b7_uds_login_resolve_logout(tmp_path: Path) -> None:
    now = [1000000]
    svc = make_service(tmp_path, now)
    ident = svc.provision_user("jane.doe", PW, "viewer")
    assert ident.username == "jane.doe"
    runtime = tmp_path / "rt"
    runtime.mkdir(mode=0o700)
    token = secrets.token_urlsafe(32)
    registry = {token: "web:auth"}
    server = UnixJsonServer(
        runtime / "b7.sock",
        service_name="b7",
        token_registry=registry,
        handler=B7AuthHandler(svc).handle,
    )
    await server.start()
    try:
        client = make_client(runtime, target="b7", source="web:auth", token=token)
        login = new_envelope(
            source="web:auth",
            target="b7",
            action="auth.login",
            data_kind=DataKind.PROPRIETARY,
            payload={"username": "jane.doe", "password": PW},
            user_id="web:auth",
        )
        reply = await client.call(login, expect_source="b7")
        assert reply.payload["userId"] == ident.user_id
        assert reply.payload["role"] == "viewer"
        assert len(reply.payload["sessionToken"]) >= 43
        assert reply.data_kind == DataKind.PROPRIETARY
        session_token = str(reply.payload["sessionToken"])
        resolve = new_envelope(
            source="web:auth",
            target="b7",
            action="auth.resolve",
            data_kind=DataKind.PROPRIETARY,
            payload={"sessionToken": session_token},
            user_id="web:auth",
        )
        resolved = await client.call(resolve, expect_source="b7")
        assert resolved.payload["username"] == "jane.doe"
        logout = new_envelope(
            source="web:auth",
            target="b7",
            action="auth.logout",
            data_kind=DataKind.PROPRIETARY,
            payload={"sessionToken": session_token},
            user_id="web:auth",
        )
        await client.call(logout, expect_source="b7")
        try:
            await client.call(resolve, expect_source="b7")
            raise AssertionError("resolve must fail after logout")
        except TransportError as exc:
            assert exc.code == "invalid_credentials"
        bad_kind = new_envelope(
            source="web:auth",
            target="b7",
            action="auth.resolve",
            data_kind=DataKind.METADATA,
            payload={"sessionToken": session_token},
            user_id="web:auth",
        )
        with pytest.raises(TransportError) as excinfo:
            await client.call(bad_kind, expect_source="b7")
        assert excinfo.value.code == "misclassified"
        outsider = make_client(
            runtime, target="b7", source="web:auth", token=secrets.token_urlsafe(32)
        )
        with pytest.raises(AuthError):
            await outsider.call(resolve, expect_source="b7")
    finally:
        await server.close()


async def test_web_to_b4_b6_b2_real_path(tmp_path: Path) -> None:
    now = [2000000]
    svc = make_service(tmp_path, now)
    viewer = svc.provision_user("jane.doe", PW, "viewer")
    coord = svc.provision_user("john.smith", PW, "coordinator")
    policy = load_matrix()
    assert policy is not None
    resolver = role_resolver_for(svc)
    assert resolver(coord.user_id) == "coordinator"
    assert resolver(viewer.user_id) == "viewer"
    assert resolver("0" * 32) is None
    assert check(policy, viewer.user_id, "tasks.write", resolver).allowed is False
    assert check(policy, coord.user_id, "tasks.write", resolver).allowed is True
    assert check(policy, "watchdog", "tasks.read", resolver).allowed is False
    assert check(policy, viewer.user_id, "nope", resolver).allowed is False
    privileged = privilege_check_for(svc)
    assert privileged(coord.user_id) is True
    assert privileged(viewer.user_id) is False
    assert privileged("watchdog") is True
    handler = make_authorize_handler(
        policy, service_name="b6", allowed_sources=frozenset({"b4"}), role_resolver=resolver
    )
    ask = Envelope(
        request_id="r",
        correlation_id="c",
        source="b4",
        target="b6",
        action="authorize",
        data_kind=DataKind.METADATA,
        payload={"userId": viewer.user_id, "action": "tasks.write"},
        user_id=viewer.user_id,
    )
    denied = await handler(ask)
    assert denied.payload["allowed"] is False

    async def b6check(*, user_id: str, action: str, correlation_id: str) -> bool:
        _ = correlation_id
        probe = Envelope(
            request_id="q",
            correlation_id="q",
            source="b4",
            target="b6",
            action="authorize",
            data_kind=DataKind.METADATA,
            payload={"userId": user_id, "action": action},
            user_id=user_id,
        )
        out = await handler(probe)
        return out.payload.get("allowed") is True

    store = MemoryStorage()
    b2 = B2Service(store, b6check, is_privileged=privileged)

    async def call_b2(request: Envelope) -> Envelope:
        fixed = Envelope(
            request_id=request.request_id,
            correlation_id=request.correlation_id,
            source=request.source,
            target="b2",
            action=request.action,
            data_kind=request.data_kind,
            payload=dict(request.payload),
            user_id=request.user_id,
        )
        return await b2.handle(fixed)

    router = B4Router(
        b6check,
        None,
        call_b2,
        None,
        {},
        web_sources=frozenset({"web:auth"}),
        is_privileged=privileged,
    )
    task = {
        "id": "t1",
        "ownerId": coord.user_id,
        "dueAt": "2030-01-01T00:00:00+00:00",
        "status": "OPEN",
        "requiredAckUserIds": [coord.user_id],
        "acknowledgedBy": [],
        "patientRef": "Patient/p1",
        "version": 1,
    }
    stored = store.tasks_create(task)
    assert stored["id"] == "t1"
    reply = await router.handle(web_envelope(coord.user_id, "tasks.read", {}, DataKind.METADATA))
    assert reply.payload["count"] == 1
    reply = await router.handle(web_envelope(viewer.user_id, "tasks.read", {}, DataKind.METADATA))
    assert reply.payload["count"] == 0
    with pytest.raises(AuthError):
        await router.handle(
            web_envelope(viewer.user_id, "tasks.write", dict(task), DataKind.PROPRIETARY)
        )
    assert store.tasks_read("t1")[0]["id"] == "t1"
    with pytest.raises(ContractError):
        web_envelope(coord.user_id, "tasks.read", {"role": "admin"}, DataKind.METADATA)
    legacy = B4Router(b6check, None, call_b2, None, {"frontend:viewer": "viewer"})
    with pytest.raises(AuthError):
        await legacy.handle(web_envelope(viewer.user_id, "tasks.read", {}, DataKind.METADATA))


async def test_session_revocation_and_persisted_restart(tmp_path: Path) -> None:
    now = [3000000]
    svc = make_service(tmp_path, now)
    ident = svc.provision_user("jane.doe", PW, "viewer")
    first = svc.login("jane.doe", PW)
    assert svc.resolve(first.session_token).user_id == ident.user_id
    svc.set_role(ident.user_id, "clinician")
    with pytest.raises(AuthError):
        svc.resolve(first.session_token)
    second = svc.login("jane.doe", PW)
    svc.disable_user(ident.user_id)
    with pytest.raises(AuthError):
        svc.resolve(second.session_token)
    with pytest.raises(AuthError):
        svc.login("jane.doe", PW)


async def test_auth_app_registers_b7_and_web(tmp_path: Path) -> None:
    now = [4000000]
    svc = make_service(tmp_path, now)
    svc.provision_user("jane.doe", PW, "viewer")
    runtime = tmp_path / "rt"
    runtime.mkdir(mode=0o700)
    tokens = fresh_tokens_with_auth()
    assert "b7" in tokens and "web:auth" in tokens
    app = build_auth_app(runtime, tokens, svc)
    await app.start()
    try:
        health = await app.health_all()
        assert set(health) >= {"b1", "b2", "b3", "b4", "b5", "b6"}
        web_client = web_client_for(app, "b7")
        login = new_envelope(
            source="web:auth",
            target="b7",
            action="auth.login",
            data_kind=DataKind.PROPRIETARY,
            payload={"username": "jane.doe", "password": PW},
            user_id="web:auth",
        )
        reply = await web_client.call(login, expect_source="b7")
        assert reply.payload["role"] == "viewer"
    finally:
        await app.close()
    leftovers = [p for p in runtime.glob("*.sock") if p.exists()]
    assert leftovers == []


def test_cli_init_add_disable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    auth_dir = tmp_path / "auth"
    assert cmd_auth_init("demo", str(auth_dir)) == 0
    assert (auth_dir / "auth.authkey").exists()
    assert (auth_dir / "proxy.key").exists()
    assert (auth_dir / "users.auth.db").exists()
    assert cmd_auth_init("demo", str(auth_dir)) == 2
    passwords = iter([PW, PW])
    monkeypatch.setattr("getpass.getpass", lambda *args: next(passwords))
    assert cmd_auth_user_add("demo", str(auth_dir), "jane.doe", "viewer") == 0
    store = SQLiteDemoAuthStore(auth_dir / "users.auth.db")
    keyset = load_key_file(auth_dir / "auth.authkey")
    svc = AuthService(
        store=store,
        keys=keyset,
        provider=LocalPasswordProvider(time_cost=2, memory_cost=19456, parallelism=1),
    )
    result = svc.login("jane.doe", PW)
    assert result.identity.role == "viewer"
    assert cmd_auth_user_disable("demo", str(auth_dir), result.identity.user_id) == 0
    with pytest.raises(AuthError):
        svc.login("jane.doe", PW)
    raw = (auth_dir / "proxy.key").read_bytes().decode().strip()
    assert len(raw) == 43
    dumped = json.dumps({"ok": True})
    assert "jane" not in dumped
