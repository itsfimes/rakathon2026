from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from rakathon_backend.b5.opencode import process as proc_module
from rakathon_backend.b5.opencode.file_config import build_file_config_content
from rakathon_backend.b5.opencode.process import OpenCodeProcess
from rakathon_backend.b5.opencode.validation import (
    AZURE_API_KEY_REF,
    AZURE_BASE_URL,
    PROVIDER_PACKAGE,
    build_config_content,
)


def test_file_config_native_shape() -> None:
    content = json.loads(
        build_file_config_content("rakathon-azure", "gpt-6-luna-dz-eu", AZURE_BASE_URL)
    )
    provider = content["providers"]["rakathon-azure"]
    assert provider["package"] == PROVIDER_PACKAGE
    assert provider["settings"]["baseURL"] == AZURE_BASE_URL
    assert provider["settings"]["maxRetries"] == 0
    assert provider["headers"] == {"api-key": AZURE_API_KEY_REF}
    model = provider["models"]["gpt-6-luna-dz-eu"]
    assert model["capabilities"] == {"tools": False, "input": ["text", "image"], "output": ["text"]}
    assert model["settings"]["maxRetries"] == 0
    assert 1024 <= model["settings"]["maxOutputTokens"] <= 8192
    assert content["permission"] == "deny"
    assert {"action": "tool.use", "resource": "*", "effect": "deny"} in content["policies"]
    assert content["model"] == "rakathon-azure/gpt-6-luna-dz-eu"


def test_file_config_rejects_untrusted() -> None:
    with pytest.raises(ValueError):
        build_file_config_content("local", "tiny", "http://127.0.0.1:11434")
    with pytest.raises(ValueError):
        build_file_config_content(
            "rakathon-azure", "gpt-6-luna-dz-eu", "https://api.example.com/v1"
        )
    with pytest.raises(ValueError):
        build_file_config_content(
            "rakathon-azure", "gpt-6-luna-dz-eu", AZURE_BASE_URL, max_output_tokens=512
        )
    with pytest.raises(ValueError):
        build_file_config_content(
            "rakathon-azure", "gpt-6-luna-dz-eu", AZURE_BASE_URL, max_output_tokens=16384
        )


def test_legacy_config_unchanged() -> None:
    content = json.loads(build_config_content("local", "tiny", "http://127.0.0.1:11434"))
    assert "providers" not in content
    assert content["provider"]["local"]["models"] == {"tiny": {"name": "tiny"}}
    assert content["permission"] == "deny"


async def test_process_file_mode_selects_native_builder(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    async def fake_spawn(*args: Any, **kwargs: Any) -> Any:
        captured["config"] = str(kwargs["env"]["OPENCODE_CONFIG_CONTENT"])

        class _Proc:
            returncode = None
            pid = 424242

            async def wait(self) -> int:
                return 0

        return _Proc()

    async def fake_probe(binary: str, expected: str, timeout: float = 10.0) -> str:
        return "2.0.31"

    async def fake_ready(self: OpenCodeProcess) -> None:
        return None

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    monkeypatch.setattr(proc_module, "probe_version", fake_probe)
    monkeypatch.setattr(OpenCodeProcess, "_wait_ready", fake_ready)
    legacy = OpenCodeProcess(
        "opencode", "2.0.31", "local", "tiny", "http://127.0.0.1:11434", startup_timeout=1.0
    )
    assert legacy._file_mode is False
    try:
        await legacy.start()
        assert '"provider":' in captured["config"].replace(" ", "")
    finally:
        await legacy.close()
    native = OpenCodeProcess(
        "opencode",
        "2.0.31",
        "rakathon-azure",
        "gpt-6-luna-dz-eu",
        AZURE_BASE_URL,
        startup_timeout=1.0,
        file_mode=True,
    )
    try:
        await native.start()
        assert '"providers":' in captured["config"].replace(" ", "")
    finally:
        await native.close()
