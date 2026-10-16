from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

from rakathon_backend.b2.iris.config import TRUSTED_REMOTE_BASE, IrisFhirConfig
from rakathon_backend.b2.iris.fhir import DirectFhirAdapter
from rakathon_backend.b2.iris.fhir_only import FhirOnlyStorage
from rakathon_backend.common.errors import ContractError
from rakathon_backend.runtime.env_file import KNOWN_ENV_KEYS, apply_env_file, parse_env_file
from rakathon_backend.runtime.secret_config import write_client_config

LOOPBACK = "http://127.0.0.1:8765/fhir/r4"
TRUSTED = TRUSTED_REMOTE_BASE


def _client(handler: object, base: str) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]  # :3
        base_url=base,
        trust_env=False,
        follow_redirects=False,
    )


def _loopback(handler: object) -> DirectFhirAdapter:
    return DirectFhirAdapter(
        IrisFhirConfig(base_url=LOOPBACK, username="u", password="p"),
        client=_client(handler, LOOPBACK),
    )


def _trusted_env(**over: str) -> dict[str, str]:
    env = {
        "RAKATHON_IRIS_FHIR_BASE_URL": TRUSTED,
        "RAKATHON_IRIS_FHIR_USER": "u",
        "RAKATHON_IRIS_FHIR_PASSWORD": "p",
        "RAKATHON_IRIS_FHIR_ALLOW_DIRECT": "1",
    }
    env.update(over)
    return env


def test_trusted_base_accepted_with_flag() -> None:
    cfg = IrisFhirConfig.from_env(
        _trusted_env(RAKATHON_IRIS_FHIR_PASSWORD="distinct-pw-abc"),
        allow_direct_remote=True,
    )
    assert cfg.base_url == TRUSTED
    assert cfg.trusted_remote is True
    assert cfg.verify_tls is True
    assert "distinct-pw-abc" not in repr(cfg)


def test_trusted_base_trailing_slash_normalized() -> None:
    cfg = IrisFhirConfig.from_env(
        _trusted_env(RAKATHON_IRIS_FHIR_BASE_URL=TRUSTED + "/"),
        allow_direct_remote=True,
    )
    assert cfg.base_url == TRUSTED


@pytest.mark.parametrize(
    "base",
    [
        "http://iris.racek.xyz/fhir/r4",
        "https://iris.racek.xyz:443/fhir/r4",
        "https://iris.racek.xyz/fhir/r4?x=1",
        "https://iris.racek.xyz/fhir/r4#frag",
        "https://user@iris.racek.xyz/fhir/r4",
        "https://user:pw@iris.racek.xyz/fhir/r4",
        "https://evil.example/fhir/r4",
        "https://iris.racek.xyz/fhir/r5",
        "https://iris.racek.xyz/",
        "https://iris.racek.xyz.evil.example/fhir/r4",
        "https://iris.racek.xyz/fhir/r4//",
        "https://iris.racek.xyz//fhir/r4",
        "https://iris.racek.xyz/%66hir/r4",
        "http://127.0.0.1:8765/fhir/r4",
    ],
)
def test_trusted_variants_rejected(base: str) -> None:
    with pytest.raises(ContractError):
        IrisFhirConfig.from_env(
            _trusted_env(RAKATHON_IRIS_FHIR_BASE_URL=base), allow_direct_remote=True
        )


def test_trusted_without_flag_rejected() -> None:
    env = _trusted_env()
    del env["RAKATHON_IRIS_FHIR_ALLOW_DIRECT"]
    with pytest.raises(ContractError):
        IrisFhirConfig.from_env(env, allow_direct_remote=True)
    with pytest.raises(ContractError):
        IrisFhirConfig.from_env(_trusted_env(), allow_direct_remote=False)


def test_remote_verify_tls_zero_rejected() -> None:
    with pytest.raises(ContractError):
        IrisFhirConfig.from_env(
            _trusted_env(RAKATHON_IRIS_FHIR_VERIFY_TLS="0"), allow_direct_remote=True
        )


def test_remote_missing_creds_no_io() -> None:
    with pytest.raises(ContractError):
        IrisFhirConfig.from_env({"RAKATHON_IRIS_FHIR_BASE_URL": TRUSTED}, allow_direct_remote=True)


def test_adapter_trust_required() -> None:
    cfg = IrisFhirConfig.from_env(_trusted_env(), allow_direct_remote=True)
    with pytest.raises(ContractError):
        DirectFhirAdapter(cfg, client=_client(lambda r: httpx.Response(200, json={}), TRUSTED))
    adapter = DirectFhirAdapter(
        cfg, client=_client(lambda r: httpx.Response(200, json={}), TRUSTED), trusted_remote=True
    )
    assert adapter is not None


def test_adapter_rejects_case_variant_host() -> None:
    cfg = IrisFhirConfig(
        base_url="https://IRIS.RACEK.XYZ/fhir/r4",
        username="u",
        password="p",
        trusted_remote=True,
    )
    with pytest.raises(ContractError):
        DirectFhirAdapter(
            cfg,
            client=_client(lambda r: httpx.Response(200, json={}), TRUSTED),
            trusted_remote=True,
        )


def test_adapter_tls_disable_rejected() -> None:
    cfg = IrisFhirConfig(
        base_url=TRUSTED, username="u", password="p", verify_tls=False, trusted_remote=True
    )
    with pytest.raises(ContractError):
        DirectFhirAdapter(cfg, client=_client(lambda r: httpx.Response(200, json={}), TRUSTED))


def test_redirect_never_followed_under_hostile_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9/")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9/")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9/")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://evil.example/fhir/r4/Patient/p1"})

    with pytest.raises(ContractError):
        _loopback(handler).read("Patient", "p1")
    assert len(calls) == 1
    assert "evil.example" not in calls[0]


def test_url_like_search_values_rejected_pre_network() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"resourceType": "Bundle", "entry": []})

    adapter = _loopback(handler)
    with pytest.raises(ContractError):
        adapter.search("Patient", {"identifier": "https://evil.example/x"})
    with pytest.raises(ContractError):
        adapter.search("Patient", {"identifier": "//evil.example/x"})
    assert calls == []


def test_fhir_only_unsupported_ops_fail_closed() -> None:
    store = FhirOnlyStorage(_loopback(lambda r: httpx.Response(200, json={})))
    with pytest.raises(ContractError) as exc_create:
        store.tasks_create({"id": "t1"})
    assert exc_create.value.code == "not_configured"
    with pytest.raises(ContractError):
        store.tasks_write({"id": "t1"})
    with pytest.raises(ContractError):
        store.tasks_read(None)
    with pytest.raises(ContractError):
        store.tasks_ack("t1", "admin")
    with pytest.raises(ContractError):
        store.vector_search("anonymized", "[0.1]", 5)


def test_fhir_only_delegates() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        if request.method == "PUT":
            return httpx.Response(200, json={"resourceType": "Patient", "id": "p1"})
        return httpx.Response(200, json={"resourceType": "Patient", "id": "p1"})

    store = FhirOnlyStorage(_loopback(handler))
    assert store.fhir_read("Patient", "p1") is not None
    stored = store.fhir_write({"resourceType": "Patient", "id": "p1"})
    assert stored["id"] == "p1"
    assert seen["path"] == "/fhir/r4/Patient/p1"


def test_env_keys_whitelisted() -> None:
    assert KNOWN_ENV_KEYS >= {
        "RAKATHON_IRIS_FHIR_BASE_URL",
        "RAKATHON_IRIS_FHIR_USER",
        "RAKATHON_IRIS_FHIR_PASSWORD",
        "RAKATHON_IRIS_FHIR_VERIFY_TLS",
        "RAKATHON_IRIS_FHIR_ALLOW_DIRECT",
    }
    for banned in (
        "PATH",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "RAKATHON_IRIS_SQL_HOST",
        "RAKATHON_BRIDGE_URL",
        "RAKATHON_IRIS_FHIR_EXTRA",
    ):
        assert banned not in KNOWN_ENV_KEYS


def test_env_file_round_trip_and_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "iris.env"
    target.write_text(
        "RAKATHON_IRIS_FHIR_BASE_URL=https://iris.racek.xyz/fhir/r4\n"
        "RAKATHON_IRIS_FHIR_USER=file-user\n"
        "RAKATHON_IRIS_FHIR_PASSWORD=file-pw\n"
        "RAKATHON_IRIS_FHIR_VERIFY_TLS=1\n"
        "RAKATHON_IRIS_FHIR_ALLOW_DIRECT=1\n",
        encoding="utf-8",
    )
    os.chmod(target, 0o600)
    parsed = parse_env_file(target)
    assert parsed["RAKATHON_IRIS_FHIR_USER"] == "file-user"
    monkeypatch.setenv("RAKATHON_IRIS_FHIR_USER", "process-user")
    for key in (
        "RAKATHON_IRIS_FHIR_BASE_URL",
        "RAKATHON_IRIS_FHIR_USER",
        "RAKATHON_IRIS_FHIR_PASSWORD",
        "RAKATHON_IRIS_FHIR_VERIFY_TLS",
        "RAKATHON_IRIS_FHIR_ALLOW_DIRECT",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("RAKATHON_IRIS_FHIR_USER", "process-user")
    filled = apply_env_file(target)
    assert os.environ["RAKATHON_IRIS_FHIR_USER"] == "process-user"
    assert "RAKATHON_IRIS_FHIR_USER" not in filled
    monkeypatch.delenv("RAKATHON_IRIS_FHIR_USER")


def test_secret_repr_and_generic_errors() -> None:
    cfg = IrisFhirConfig(
        base_url=TRUSTED, username="u", password="live-secret-pw", trusted_remote=True
    )
    assert "live-secret-pw" not in repr(cfg)
    with pytest.raises(ContractError) as excinfo:
        IrisFhirConfig.from_env({"RAKATHON_IRIS_FHIR_BASE_URL": TRUSTED})
    assert "live-secret-pw" not in str(excinfo.value)


def test_write_client_config_mode_truth(tmp_path: Path) -> None:
    default_path = write_client_config(tmp_path, {"frontend:admin": "tok"}, "mock")
    assert json.loads(default_path.read_text(encoding="utf-8"))["mode"] == "mock"
    live_path = write_client_config(tmp_path, {"frontend:admin": "tok"}, "mock", "iris-fhir")
    assert json.loads(live_path.read_text(encoding="utf-8"))["mode"] == "iris-fhir"
