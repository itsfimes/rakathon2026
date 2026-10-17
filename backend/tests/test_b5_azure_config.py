from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import pytest

from rakathon_backend.b4.router import B4Router
from rakathon_backend.b5.opencode import process as proc_module
from rakathon_backend.b5.opencode.adapter import OpenCodeAdapter
from rakathon_backend.b5.opencode.config import from_env
from rakathon_backend.b5.opencode.validation import (
    AI_EDGE_TIMEOUT,
    AI_FRONTEND_TIMEOUT,
    AI_GATEWAY_TIMEOUT,
    AI_IPC_TIMEOUT,
    AI_REQUEST_TIMEOUT,
    AZURE_BASE_URL,
    build_config_content,
    validate_azure_base_url,
    validate_provider_kind,
)
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import TransportError
from rakathon_backend.runtime import commands as cmd_module

_AZURE_URL = "https://apim-rakathon-q7146n.azure-api.net/openai/v1"
_TEST_KEY = "test-key-value-for-offline-assertions-only"


def _azure_env() -> dict[str, str]:
    return {
        "RAKATHON_AI_ENABLE": "1",
        "RAKATHON_AI_TRUST_AZURE": "1",
        "RAKATHON_AI_PROVIDER_KIND": "azure",
        "RAKATHON_AI_MODEL": "gpt-6-luna-dz-eu",
        "RAKATHON_AI_BASE_URL": _AZURE_URL,
        "RAKATHON_AI_API_KEY": _TEST_KEY,
    }


def _local_env() -> dict[str, str]:
    return {
        "RAKATHON_AI_ENABLE": "1",
        "RAKATHON_AI_OS_EGRESS_ISOLATED": "1",
        "RAKATHON_AI_PROVIDER": "local",
        "RAKATHON_AI_MODEL": "tiny",
        "RAKATHON_AI_BASE_URL": "http://127.0.0.1:11434",
    }


def test_azure_full_env_enables() -> None:
    config = from_env(_azure_env(), requested=True)
    assert config.ready is True
    assert config.blockers == ()
    assert config.provider_kind == "azure"
    assert config.provider_id == "rakathon-azure"
    assert config.model == "gpt-6-luna-dz-eu"
    assert config.base_url == _AZURE_URL
    assert config.trust_azure is True
    assert config.api_key_present is True
    assert config.request_timeout == 180.0


def test_azure_needs_no_egress_attestation() -> None:
    env = _azure_env()
    assert "RAKATHON_AI_OS_EGRESS_ISOLATED" not in env
    assert from_env(env, requested=True).ready is True


def test_azure_missing_consent_blocks() -> None:
    env = _azure_env()
    del env["RAKATHON_AI_TRUST_AZURE"]
    config = from_env(env, requested=True)
    assert config.ready is False
    assert any("TRUST_AZURE" in blocker for blocker in config.blockers)


def test_azure_missing_key_blocks_without_spawning() -> None:
    env = _azure_env()
    del env["RAKATHON_AI_API_KEY"]
    config = from_env(env, requested=True)
    assert config.ready is False
    assert config.api_key_present is False
    assert any("RAKATHON_AI_API_KEY" in blocker for blocker in config.blockers)


async def test_azure_not_ready_never_spawns(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _azure_env()
    del env["RAKATHON_AI_API_KEY"]
    config = from_env(env, requested=True)
    assert config.ready is False

    async def fake_spawn(*args: Any, **kwargs: Any) -> Any:
        _ = (args, kwargs)
        raise AssertionError("must not spawn")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    with pytest.raises(TransportError):
        await OpenCodeAdapter.create(config, api_key="")


def test_canonical_azure_provider_id_rejected() -> None:
    env = _azure_env()
    env["RAKATHON_AI_PROVIDER"] = "azure"
    config = from_env(env, requested=True)
    assert config.ready is False
    assert any("api-key" in blocker for blocker in config.blockers)


def test_azure_exact_url_accepted() -> None:
    assert validate_azure_base_url(_AZURE_URL) == _AZURE_URL
    assert validate_azure_base_url(_AZURE_URL + "/") == _AZURE_URL
    assert AZURE_BASE_URL == _AZURE_URL


@pytest.mark.parametrize(
    "raw",
    [
        "http://127.0.0.1:11434",
        "https://apim-rakathon-q7146n.azure-api.net/openai/v1?api-version=1",
        "https://apim-rakathon-q7146n.azure-api.net/openai/v1#frag",
        "https://user:pass@apim-rakathon-q7146n.azure-api.net/openai/v1",
        "https://apim-rakathon-q7146n.azure-api.net/openai/v1/extra",
        "https://apim-rakathon-q7146n.azure-api.net/openai",
        "https://apim-rakathon-q7146n.azure-api.net/",
        "https://other.azure-api.net/openai/v1",
        "https://api.example.com/v1",
        "http://apim-rakathon-q7146n.azure-api.net/openai/v1",
        "",
        "not-a-url",
    ],
)
def test_azure_narrow_allowlist_rejects(raw: str) -> None:
    with pytest.raises(ValueError):
        validate_azure_base_url(raw)
    env = _azure_env()
    env["RAKATHON_AI_BASE_URL"] = raw
    config = from_env(env, requested=True)
    assert config.ready is False
    assert config.base_url == ""


def test_bad_provider_kind_rejected() -> None:
    with pytest.raises(ValueError):
        validate_provider_kind("gcp")
    assert validate_provider_kind("") == "local"
    assert validate_provider_kind("AZURE") == "azure"
    env = _azure_env()
    env["RAKATHON_AI_PROVIDER_KIND"] = "gcp"
    config = from_env(env, requested=True)
    assert config.ready is False


def test_local_path_unchanged() -> None:
    config = from_env(_local_env(), requested=True)
    assert config.ready is True
    assert config.provider_kind == "local"
    assert config.api_key_present is False
    env = _local_env()
    env["RAKATHON_AI_BASE_URL"] = "https://api.example.com/v1"
    assert from_env(env, requested=True).ready is False
    env = _local_env()
    del env["RAKATHON_AI_OS_EGRESS_ISOLATED"]
    blocked = from_env(env, requested=True)
    assert blocked.ready is False
    assert any("EGRESS" in blocker for blocker in blocked.blockers)


def test_azure_child_config_sends_api_key_header() -> None:
    content = json.loads(
        build_config_content(
            "rakathon-azure", "gpt-6-luna-dz-eu", _AZURE_URL, provider_kind="azure"
        )
    )
    provider = content["provider"]["rakathon-azure"]
    assert provider["npm"] == "@ai-sdk/openai-compatible"
    assert provider["options"]["baseURL"] == _AZURE_URL
    assert provider["options"]["headers"] == {"api-key": "{env:RAKATHON_AI_API_KEY}"}
    assert "apiKey" not in provider["options"]
    assert provider["models"] == {"gpt-6-luna-dz-eu": {"name": "gpt-6-luna-dz-eu"}}
    assert content["permission"] == "deny"
    assert content["model"] == "rakathon-azure/gpt-6-luna-dz-eu"
    allow = [p for p in content["policies"] if p["effect"] == "allow"]
    assert allow == [{"action": "provider.use", "resource": "rakathon-azure", "effect": "allow"}]


def test_local_child_config_carries_no_headers() -> None:
    content = json.loads(build_config_content("local", "tiny", "http://127.0.0.1:11434"))
    assert content["provider"]["local"]["options"] == {"baseURL": "http://127.0.0.1:11434"}


def test_config_carries_no_secret_value() -> None:
    config = from_env(_azure_env(), requested=True)
    assert _TEST_KEY not in repr(config)
    assert _TEST_KEY not in str(config.blockers)


async def test_ai_check_redacts_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for key, value in _azure_env().items():
        monkeypatch.setenv(key, value)

    async def fake_probe(binary: str, expected: str, timeout: float = 10.0) -> str:
        _ = (binary, expected, timeout)
        return "2.0.31"

    monkeypatch.setattr(proc_module, "probe_version", fake_probe)
    monkeypatch.setattr(cmd_module, "probe_version", fake_probe)
    rc = await cmd_module.cmd_ai_check()
    assert rc == 0
    out = capsys.readouterr().out
    assert _TEST_KEY not in out
    report = json.loads(out)
    assert report["enabled"] is True
    assert report["providerKind"] == "azure"
    assert report["apiKeyPresent"] is True


async def test_ai_check_missing_key_reports_blocker_redacted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for key in (
        "RAKATHON_AI_ENABLE",
        "RAKATHON_AI_TRUST_AZURE",
        "RAKATHON_AI_PROVIDER_KIND",
        "RAKATHON_AI_PROVIDER",
        "RAKATHON_AI_MODEL",
        "RAKATHON_AI_BASE_URL",
        "RAKATHON_AI_API_KEY",
        "RAKATHON_AI_KILL_FILE",
        "AI_DISABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("RAKATHON_AI_BINARY", sys.executable)
    rc = await cmd_module.cmd_ai_check()
    assert rc == 2
    out = capsys.readouterr().out
    assert _TEST_KEY not in out
    report = json.loads(out)
    assert report["enabled"] is False
    assert report["apiKeyPresent"] is False


def test_operation_timeouts_are_bounded_and_ordered() -> None:
    assert AI_REQUEST_TIMEOUT == 180.0
    assert AI_GATEWAY_TIMEOUT == 185.0
    assert AI_IPC_TIMEOUT == 190.0
    assert AI_FRONTEND_TIMEOUT == 200.0
    assert AI_EDGE_TIMEOUT == 205.0
    assert 0 < AI_REQUEST_TIMEOUT < AI_GATEWAY_TIMEOUT < AI_IPC_TIMEOUT
    assert AI_IPC_TIMEOUT < AI_FRONTEND_TIMEOUT <= AI_EDGE_TIMEOUT
    assert cmd_module.client_timeout_for("ai.complete") == AI_EDGE_TIMEOUT
    assert cmd_module.client_timeout_for("ingest") == AI_EDGE_TIMEOUT
    assert cmd_module.client_timeout_for("reminders.read") == 5.0


async def _allow_all(*, user_id: str, action: str, correlation_id: str) -> bool:
    _ = (user_id, action, correlation_id)
    return True


def _front(user: str, action: str, rid: str = "r-1") -> Envelope:
    return Envelope(
        request_id=rid,
        correlation_id="c-1",
        source=f"frontend:{user}",
        target="b4",
        action=action,
        data_kind=DataKind.METADATA,
        payload={},
        user_id=user,
    )


async def test_b4_ai_route_outlives_generic_pending_timeout() -> None:
    async def slow(request: Envelope) -> Envelope:
        await asyncio.sleep(0.3)
        return request.reply(
            source="b5", action=request.action, payload={"ok": True}, data_kind=DataKind.METADATA
        )

    router = B4Router(
        _allow_all,
        None,
        slow,
        slow,
        {"frontend:clinician": "clinician"},
        pending_timeout=0.05,
        ai_pending_timeout=10.0,
    )
    reply = await router.handle(_front("clinician", "ai.complete"))
    assert reply.payload == {"ok": True}
    with pytest.raises(TransportError):
        await router.handle(_front("clinician", "tasks.read", rid="r-2"))


def test_b4_rejects_non_positive_timeouts() -> None:
    with pytest.raises(ValueError):
        B4Router(_allow_all, pending_timeout=0.0)
    with pytest.raises(ValueError):
        B4Router(_allow_all, ai_pending_timeout=-1.0)
