from __future__ import annotations

import base64
import json
from dataclasses import replace
from typing import Any

import httpx
import pytest

from rakathon_backend.b2.auth.https_config import SERVICE_URL, AuthHTTPSConfig
from rakathon_backend.b2.auth.https_contract import session_wire, user_wire
from rakathon_backend.b2.auth.https_store import IrisHTTPSAuthStore
from rakathon_backend.b2.auth.models import RateLimited, SessionRecord, StoreUnavailable, UserRecord
from rakathon_backend.b2.auth.protocol import PersistentAuthStore
from rakathon_backend.common.errors import ContractError

USER = UserRecord(
    "a" * 32,
    "b" * 64,
    "$argon2id$v=19$m=65536,t=3,p=1$c2FsdA$aGFzaA",
    b"n" * 12,
    b"c" * 32,
    "c" * 16,
    "viewer",
    True,
    1,
    100,
    100,
)
SESSION = SessionRecord("d" * 64, USER.user_id, 1, "viewer", 100, 100, 200)


def config() -> AuthHTTPSConfig:
    return AuthHTTPSConfig(SERVICE_URL, "synthetic-service", "synthetic-secret")


def reply(result: Any) -> httpx.Response:
    return httpx.Response(200, json={"v": 1, "ok": True, "result": result})


def test_all_port_operations_have_closed_typed_requests() -> None:
    captured: list[dict[str, Any]] = []
    responses: dict[str, Any] = {
        "get_user_by_index": user_wire(USER),
        "get_user_by_id": user_wire(USER),
        "get_session": session_wire(SESSION),
        "cas_last_seen": True,
        "count_user_sessions": 1,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == SERVICE_URL
        assert request.method == "POST"
        assert (
            request.headers["authorization"]
            == "Basic " + base64.b64encode(b"synthetic-service:synthetic-secret").decode()
        )
        assert request.headers["accept-encoding"] == "identity"
        body = json.loads(request.content)
        assert body.keys() == {"v", "op", "args"} and body["v"] == 1
        captured.append(body)
        return reply(responses.get(body["op"]))

    store: PersistentAuthStore = IrisHTTPSAuthStore(
        config(), transport=httpx.MockTransport(handler)
    )
    store.create_user(USER)
    assert store.get_user_by_index(USER.username_index) == USER
    assert store.get_user_by_id(USER.user_id) == USER
    store.update_user(replace(USER, auth_version=2))
    store.create_session(SESSION)
    assert store.get_session(SESSION.token_hash) == SESSION
    assert store.cas_last_seen(SESSION.token_hash, 100, 101) is True
    store.delete_session(SESSION.token_hash)
    assert store.count_user_sessions(USER.user_id) == 1
    store.prune_user_sessions(USER.user_id, 31)
    store.revoke_user_sessions(USER.user_id)
    store.prune_expired_sessions(200, 100)
    store.rate_reserve(USER.username_index, 100, 10, 60, 100, 60)
    assert len(captured) == 13
    assert captured[0]["args"] == {"record": user_wire(USER)}
    assert captured[6]["args"] == {"token_hash": SESSION.token_hash, "old": 100, "new": 101}
    assert captured[-1]["args"] == {
        "account_key": USER.username_index,
        "now": 100,
        "account_limit": 10,
        "account_window": 60,
        "global_limit": 100,
        "global_window": 60,
    }
    with pytest.raises(ContractError, match="auth schema requires administrator"):
        store.init_schema()
    assert len(captured) == 13


@pytest.mark.parametrize("op", ["get_user_by_id", "get_user_by_index", "get_session"])
def test_missing_record_is_not_synthesized(op: str) -> None:
    store = IrisHTTPSAuthStore(config(), transport=httpx.MockTransport(lambda _: reply(None)))
    key = USER.user_id if op == "get_user_by_id" else "b" * 64
    assert getattr(store, op)(key) is None


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"Location": "https://other.example/stolen"}),
        httpx.Response(401, text="synthetic-secret"),
        httpx.Response(403),
        httpx.Response(503),
        httpx.Response(200, text="not-json"),
        httpx.Response(
            200,
            content=b'{"v":1,"ok":true,"result":0,"result":1}',
            headers={"Content-Type": "application/json"},
        ),
        httpx.Response(
            200,
            content=b'{"v":1,"ok":true,"result":0,"re\\u0073ult":1}',
            headers={"Content-Type": "application/json"},
        ),
        httpx.Response(200, json={"v": True, "ok": True, "result": 0}),
        httpx.Response(200, json={"v": 1, "ok": 1, "result": 0}),
        httpx.Response(200, json={"v": 1, "ok": True, "result": True}),
        httpx.Response(200, json={"v": 1, "ok": True, "result": 0, "extra": "secret"}),
        httpx.Response(200, json={"v": 1, "ok": False, "error": "raw SQL secret"}),
        httpx.Response(200, content=b"x" * 16385, headers={"Content-Type": "application/json"}),
        httpx.Response(
            200, json={"v": 1, "ok": True, "result": 0}, headers={"Content-Encoding": "unsupported"}
        ),
    ],
)
def test_untrusted_responses_fail_closed_without_retries(response: httpx.Response) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return response

    store = IrisHTTPSAuthStore(config(), transport=httpx.MockTransport(handler))
    with pytest.raises(StoreUnavailable) as caught:
        store.count_user_sessions(USER.user_id)
    assert len(calls) == 1
    assert "secret" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_mutation_timeout_has_no_automatic_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("synthetic-secret", request=request)

    store = IrisHTTPSAuthStore(config(), transport=httpx.MockTransport(handler))
    with pytest.raises(StoreUnavailable) as caught:
        store.update_user(USER)
    assert calls == 1 and "secret" not in str(caught.value)


def test_only_typed_operation_specific_errors_escape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        op = json.loads(request.content)["op"]
        code = "rate_limited" if op == "rate_reserve" else "duplicate_id"
        return httpx.Response(200, json={"v": 1, "ok": False, "error": code})

    store = IrisHTTPSAuthStore(config(), transport=httpx.MockTransport(handler))
    with pytest.raises(RateLimited):
        store.rate_reserve(USER.username_index, 100, 10, 60, 100, 60)
    with pytest.raises(ContractError) as caught:
        store.create_user(USER)
    assert caught.value.code == "duplicate_id"
    with pytest.raises(StoreUnavailable):
        store.get_user_by_id(USER.user_id)


def test_default_client_disables_redirects_environment_and_tls_bypass() -> None:
    store = IrisHTTPSAuthStore(config())
    with store._client() as client:
        assert client.follow_redirects is False
        assert client.trust_env is False
        assert client.timeout.connect == 5
        assert client.timeout.read == 12
    assert "synthetic-secret" not in repr(config())
    assert "synthetic-service" not in repr(config())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("active", 1),
        ("role", []),
        ("role", "watchdog"),
        ("auth_version", True),
        ("auth_version", 0),
        ("password_hash", "plaintext"),
        ("enc_nonce", "bad"),
        ("enc_ct", "YQ=="),
        ("key_id", "injected\n"),
        ("updated_at", 99),
    ],
)
def test_malformed_remote_user_record_is_not_trusted(field: str, value: Any) -> None:
    data = user_wire(USER)
    data[field] = value
    store = IrisHTTPSAuthStore(config(), transport=httpx.MockTransport(lambda _: reply(data)))
    with pytest.raises(StoreUnavailable):
        store.get_user_by_id(USER.user_id)


def test_session_boolean_version_and_time_order_fail_closed() -> None:
    data = session_wire(SESSION)
    data["auth_version"] = True
    store = IrisHTTPSAuthStore(config(), transport=httpx.MockTransport(lambda _: reply(data)))
    with pytest.raises(StoreUnavailable):
        store.get_session(SESSION.token_hash)
    data["auth_version"] = 1
    data["last_seen"] = data["expires_at"]
    with pytest.raises(StoreUnavailable):
        store.get_session(SESSION.token_hash)
