from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Any

import pytest

from rakathon_backend.b2.auth.https_config import SERVICE_URL, AuthHTTPSConfig
from rakathon_backend.b2.auth.https_contract import (
    OP_FIELDS,
    decode,
    request_args,
    result_value,
    session_record,
    user_record,
)
from rakathon_backend.b2.auth.models import StoreUnavailable
from rakathon_backend.b2.auth.protocol import PersistentAuthStore
from rakathon_backend.common.errors import ContractError


@pytest.mark.parametrize(
    "url",
    [
        "http://iris.racek.xyz/auth-storage/v1/operation",
        SERVICE_URL + "?",
        SERVICE_URL + "#",
        SERVICE_URL + "/",
        SERVICE_URL + "?token=secret",
        SERVICE_URL.replace("iris.racek.xyz", "iris.racek.xyz.evil.example"),
        SERVICE_URL.replace("iris.racek.xyz", "name:password@iris.racek.xyz"),
        SERVICE_URL.replace("iris.racek.xyz", "iris.racek.xyz:8443"),
        SERVICE_URL.replace("/auth-storage/", "/fhir/"),
        "https://iris.racek.xyz/auth-storage/../auth-storage/v1/operation",
        "http://127.0.0.1:8766/auth-storage/v1/operation",
    ],
)
def test_exact_service_egress_allowlist(url: str) -> None:
    with pytest.raises(ContractError, match="auth HTTPS is not configured"):
        AuthHTTPSConfig(url, "service", "secret")


def test_loopback_is_only_an_explicit_constructor_test_seam() -> None:
    AuthHTTPSConfig(
        "http://127.0.0.1:8766/auth-storage/v1/operation", "s", "p", allow_test_loopback=True
    )
    for url in [
        "http://localhost:8766/auth-storage/v1/operation",
        "http://127.0.0.1:8766/auth-storage/v1/operation?",
        "http://127.0.0.1:8766/auth-storage/v1/operation#",
    ]:
        with pytest.raises(ContractError):
            AuthHTTPSConfig(url, "s", "p", allow_test_loopback=True)


def test_explicit_credential_selection_and_namespace_required() -> None:
    env = {
        "RAKATHON_AUTH_HTTPS_URL": SERVICE_URL,
        "RAKATHON_AUTH_HTTPS_NAMESPACE": "USER",
        "RAKATHON_IRIS_FHIR_BASE_URL": "https://iris.racek.xyz/fhir/r4",
        "RAKATHON_IRIS_FHIR_USER": "service",
        "RAKATHON_IRIS_FHIR_PASSWORD": "secret",
    }
    with pytest.raises(ContractError):
        AuthHTTPSConfig.from_env(env)
    env["RAKATHON_AUTH_HTTPS_CREDENTIALS"] = "fhir"
    assert AuthHTTPSConfig.from_env(env).username == "service"
    env["RAKATHON_AUTH_HTTPS_NAMESPACE"] = "FHIRSERVER"
    with pytest.raises(ContractError):
        AuthHTTPSConfig.from_env(env)
    env["RAKATHON_AUTH_HTTPS_NAMESPACE"] = "USER"
    env["RAKATHON_AUTH_HTTPS_CREDENTIALS"] = "dedicated"
    with pytest.raises(ContractError):
        AuthHTTPSConfig.from_env(env)
    env.update(RAKATHON_AUTH_HTTPS_USER="separate", RAKATHON_AUTH_HTTPS_PASSWORD="other")
    assert AuthHTTPSConfig.from_env(env).username == "separate"


@pytest.mark.parametrize(
    ("op", "args"),
    [
        ("init_schema", {}),
        ("sql", {"query": "DROP TABLE FSB.AuthUsers"}),
        ("get_user_by_id", {"user_id": "a" * 32, "table": "FSB.AuthUsers"}),
        ("get_user_by_id", {"user_id": "not-an-id"}),
        ("get_user_by_index", {"username_index": "b" * 65}),
        ("count_user_sessions", {}),
        ("prune_user_sessions", {"user_id": "a" * 32, "keep": True}),
        ("prune_user_sessions", {"user_id": "a" * 32, "keep": 33}),
        ("prune_expired_sessions", {"now": 100, "limit": 1001}),
        ("cas_last_seen", {"token_hash": "b" * 64, "old": 101, "new": 100}),
        ("cas_last_seen", {"token_hash": "b" * 64, "old": 100, "new": 100.0}),
        (
            "rate_reserve",
            {
                "account_key": "b" * 64,
                "now": 100,
                "account_limit": 0,
                "account_window": 60,
                "global_limit": 100,
                "global_window": 60,
            },
        ),
    ],
)
def test_operation_and_field_bounds(op: str, args: dict[str, Any]) -> None:
    with pytest.raises(StoreUnavailable):
        request_args(op, args)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"op":1,"op":2}',
        b'{"args":{"user_id":1,"user\\u005fid":2}}',
        b'{"op":1,"\\u006fp":2}',
        b'{"a":{"b":1,"b":2}}',
        b"{" * 2000,
        b"\xff",
        b"x" * 16385,
    ],
)
def test_duplicate_equivalent_keys_and_malformed_json_rejected(raw: bytes) -> None:
    with pytest.raises(StoreUnavailable):
        decode(raw)


@pytest.mark.parametrize("value", [{}, [], True, "raw", {"role": []}])
def test_incomplete_records_fail_closed(value: Any) -> None:
    with pytest.raises(StoreUnavailable):
        user_record(value)
    with pytest.raises(StoreUnavailable):
        session_record(value)


@pytest.mark.parametrize(
    "op",
    [
        "create_user",
        "update_user",
        "create_session",
        "delete_session",
        "prune_user_sessions",
        "prune_expired_sessions",
        "revoke_user_sessions",
        "rate_reserve",
    ],
)
def test_mutation_result_is_explicit_null(op: str) -> None:
    assert result_value(op, None) is None
    with pytest.raises(StoreUnavailable):
        result_value(op, {"success": True})


def test_server_static_operation_manifest_matches_port_not_compile_proof() -> None:
    methods = {
        name
        for name, value in vars(PersistentAuthStore).items()
        if not name.startswith("_") and inspect.isfunction(value)
    }
    assert methods == set(OP_FIELDS) | {"init_schema"}
    server = Path(__file__).parents[1] / "iris/auth"
    contract = (server / "Contract.cls").read_text()
    fields_body = contract.split("ClassMethod Fields", 1)[1].split("ClassMethod Shape", 1)[0]
    assert set(re.findall(r'op="([a-z_]+)"', fields_body)) == set(OP_FIELDS)
    manifest = {
        op: frozenset(fields.split(","))
        for condition, fields in re.findall(r'if (.+?) \{ quit "([^"]+)" \}', fields_body)
        for op in re.findall(r'op="([a-z_]+)"', condition)
    }
    assert manifest == OP_FIELDS
    service = (server / "Service.cls").read_text()
    assert 'req.op="init_schema"' not in service
    assert "tstart" in service and "tcommit" in service and "trollback 1" in service
    assert 'RakathonAuthService","U"' in service and '$namespace\'="USER"' in service
    assert 'principal="UnknownUser"' in service
    assert "set seen(key)=1" in (server / "StrictJSON.cls").read_text()
    assert (
        "SET password_hash=?,role=?,active=?,auth_version=?,updated_at=?"
        in (server / "Users.cls").read_text()
    )
    for file in server.glob("*.cls"):
        assert len(file.read_text().splitlines()) <= 350
        assert "CREATE TABLE" not in file.read_text()
