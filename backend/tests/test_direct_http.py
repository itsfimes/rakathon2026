from __future__ import annotations

import asyncio
import gzip
import json
from typing import Any

import httpx
import pytest
from direct_fixtures import outcome, provider_response, response

from rakathon_backend.b1.schema import OUTPUT_SCHEMA
from rakathon_backend.b5.direct import DirectAdapter, direct_config_from_env
from rakathon_backend.b5.direct_http import DirectHttpTransport, DirectProviderConfig
from rakathon_backend.common.errors import ContractError, TransportError


def config(**changes: Any) -> DirectProviderConfig:
    values: dict[str, Any] = {
        "base_url": "https://synthetic.invalid/v1",
        "model": "synthetic-model",
        "auth_scheme": "api-key",
        "api_key": "synthetic-key",
        "allow_remote": True,
    }
    return DirectProviderConfig(**(values | changes))


async def test_strict_request_auth_identity_compression_and_conversation() -> None:
    calls: list[httpx.Request] = []

    def send(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["Accept-Encoding"] == "identity"
        assert request.headers["api-key"] == "synthetic-key"
        assert "Authorization" not in request.headers
        assert str(request.url) == "https://synthetic.invalid/v1/chat/completions"
        data = json.loads(request.content)
        if len(calls) == 1:
            assert data["response_format"]["json_schema"] == {
                "name": "rakathon_ingestion",
                "schema": OUTPUT_SCHEMA,
                "strict": True,
            }
            return provider_response(outcome())
        assert "response_format" not in data
        return response("Synthetic conversation")

    adapter = DirectAdapter(DirectHttpTransport(config(), transport=httpx.MockTransport(send)))
    try:
        result = await adapter.translate(b"Synthetic source", "text/plain")
        assert result["status"] == "complete"
        assert await adapter.complete(b"Synthetic question", "text/plain") == {
            "answer": "Synthetic conversation"
        }
    finally:
        await adapter.close()
    with pytest.raises(TransportError, match="closed"):
        await adapter.complete(b"question", "text/plain")


@pytest.mark.parametrize(
    "change",
    [
        {"base_url": "http://remote.invalid/v1"},
        {"base_url": "https://user:password@remote.invalid/v1"},
        {"base_url": "https://remote.invalid/v1?x=1"},
        {"allow_remote": False},
        {"api_key": "line\nbreak"},
        {"model": ""},
        {"timeout_seconds": 0},
    ],
)
def test_bad_config(change: dict[str, Any]) -> None:
    with pytest.raises(ContractError):
        config(**change)


def test_explicit_environment_and_no_implicit_credentials() -> None:
    with pytest.raises(ContractError):
        direct_config_from_env({})
    env = {
        "RAKATHON_AI_ENABLE": "1",
        "RAKATHON_AI_PROVIDER_KIND": "azure",
        "RAKATHON_AI_BASE_URL": "https://synthetic.invalid/openai/v1",
        "RAKATHON_AI_MODEL": "synthetic",
        "RAKATHON_AI_API_KEY": "synthetic-key",
        "RAKATHON_AI_ALLOW_REMOTE": "1",
    }
    assert direct_config_from_env(env).auth_scheme == "api-key"
    env["RAKATHON_AI_PROVIDER_KIND"] = "openai-compatible"
    assert direct_config_from_env(env).auth_scheme == "bearer"
    env["AI_DISABLED"] = "1"
    with pytest.raises(TransportError) as killed:
        direct_config_from_env(env)
    assert killed.value.code == "killed"


@pytest.mark.parametrize(
    "kind",
    [
        "http-error",
        "redirect",
        "compressed",
        "duplicate-outer",
        "duplicate-inner",
        "refusal",
        "tool-call",
        "null-content",
        "nonstop",
        "schema",
        "markdown",
        "invalid-json",
    ],
)
async def test_bad_provider_responses_fail_closed(kind: str) -> None:
    def send(request: httpx.Request) -> httpx.Response:
        if kind == "http-error":
            return httpx.Response(500, text="must not leak upstream text")
        if kind == "redirect":
            return httpx.Response(302, headers={"Location": "http://private.invalid"})
        if kind == "compressed":
            return httpx.Response(
                200, headers={"Content-Encoding": "gzip"}, content=gzip.compress(b"{}")
            )
        if kind == "duplicate-outer":
            return httpx.Response(200, content=b'{"choices":[],"choices":[]}')
        if kind == "duplicate-inner":
            return response('{"status":"complete","status":"manual-review"}')
        if kind == "refusal":
            return response("{}", refusal="Synthetic refusal")
        if kind == "tool-call":
            return response("{}", tool_calls=[])
        if kind == "null-content":
            return httpx.Response(
                200, json={"choices": [{"finish_reason": "stop", "message": {"content": None}}]}
            )
        if kind == "nonstop":
            return httpx.Response(
                200, json={"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}
            )
        return response(
            {
                "schema": '{"unsupported":true}',
                "markdown": "```json\n{}\n```",
                "invalid-json": "{broken",
            }[kind]
        )

    adapter = DirectAdapter(DirectHttpTransport(config(), transport=httpx.MockTransport(send)))
    try:
        with pytest.raises((ContractError, TransportError)) as rejected:
            await adapter.translate(b"Synthetic source", "text/plain")
        assert "must not leak" not in str(rejected.value)
    finally:
        await adapter.close()


async def test_timeout_cancellation_and_request_response_bounds() -> None:
    cancelled = asyncio.Event()

    async def wait(request: httpx.Request) -> httpx.Response:
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()
        return response("unreachable")

    transport = DirectHttpTransport(
        config(timeout_seconds=0.02), transport=httpx.MockTransport(wait)
    )
    try:
        with pytest.raises(TransportError) as timeout:
            await transport.generate("Synthetic")
        assert timeout.value.code == "ai_timeout" and cancelled.is_set()
    finally:
        await transport.aclose()
    transport = DirectHttpTransport(
        config(max_response_bytes=32, max_content_bytes=32, max_request_bytes=64),
        transport=httpx.MockTransport(lambda req: response("x" * 64)),
    )
    try:
        with pytest.raises(ContractError):
            await transport.generate("x" * 65)
        with pytest.raises(ContractError):
            await transport.generate("x")
    finally:
        await transport.aclose()
