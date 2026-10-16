from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx
import pytest

from rakathon_backend.b5.direct import direct_config_from_env
from rakathon_backend.b5.direct_http import DirectHttpTransport
from rakathon_backend.common.errors import TransportError
from rakathon_backend.web.runtime import cmd_web_serve


def values() -> dict[str, str]:
    return {
        "AI_DISABLED": "0",
        "RAKATHON_AI_ENABLE": "1",
        "RAKATHON_AI_PROVIDER_KIND": "azure",
        "RAKATHON_AI_ALLOW_REMOTE": "1",
        "RAKATHON_AI_BASE_URL": "https://synthetic.invalid/openai/v1",
        "RAKATHON_AI_MODEL": "test",
        "RAKATHON_AI_API_KEY": "synthetic-key",
    }


@pytest.mark.parametrize(
    "scheme,header",
    [
        ("api-key", "api-key"),
        ("bearer", "authorization"),
        ("subscription-key", "ocp-apim-subscription-key"),
        ("Ocp-Apim-Subscription-Key", "ocp-apim-subscription-key"),
    ],
)
async def test_explicit_auth_header_without_fallback(
    scheme: str, header: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_DISABLED", "0")
    count = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        assert {
            name
            for name in ("api-key", "authorization", "ocp-apim-subscription-key")
            if name in request.headers
        } == {header}
        assert "response_format" not in json.loads(request.content)
        return httpx.Response(401)

    config = direct_config_from_env({**values(), "RAKATHON_AI_AUTH_SCHEME": scheme})
    transport = DirectHttpTransport(config, transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(TransportError):
            await transport.generate("Synthetic prompt")
        assert count == 1
    finally:
        await transport.aclose()


@pytest.mark.parametrize("scheme", ["", "none", "guess"])
async def test_web_startup_requires_auth_before_storage(
    tmp_path: Path, scheme: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RAKATHON_WEB_ASSISTANT_ENABLE", "1")
    monkeypatch.setenv("RAKATHON_AI_AUTH_SCHEME", scheme)
    args = argparse.Namespace(
        frontend_origin=["http://localhost:5174"],
        bind="127.0.0.1",
        port=8765,
        proxy_key_file=str(tmp_path / "proxy.key"),
        runtime_dir=str(tmp_path / "uds"),
    )
    assert await cmd_web_serve(args) == 1
    assert not (tmp_path / "uds").exists()
