from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import pytest

from rakathon_backend.b5.opencode.client import OpenCodeClient
from rakathon_backend.common.errors import TransportError


def _auth_header(password: str) -> str:
    return "Basic " + base64.b64encode(f"opencode:{password}".encode()).decode()


def _ok_response(status: int, body: Any) -> httpx.Response:
    return httpx.Response(status, json=body)


def _make_client(handler: Any, password: str = "pw-secret-value-1234567890") -> OpenCodeClient:
    transport = httpx.MockTransport(handler)
    return OpenCodeClient(
        "http://127.0.0.1:4099", password, "local", "tiny", timeout=5.0, transport=transport
    )


def _check_auth(request: httpx.Request, password: str) -> None:
    assert request.headers.get("authorization") == _auth_header(password)


async def test_health_session_generate_interrupt_delete_flow() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        _check_auth(request, "pw-secret-value-1234567890")
        seen[str(request.url.path)] = json.loads(request.content or b"null")
        if request.method == "GET" and request.url.path == "/api/session":
            return _ok_response(200, {"data": [], "cursor": {"previous": None, "next": None}})
        if request.method == "POST" and request.url.path == "/api/session":
            body = json.loads(request.content)
            assert body["model"] == {"providerID": "local", "id": "tiny"}
            assert body["permissions"] == [{"action": "*", "resource": "*", "effect": "deny"}]
            return _ok_response(200, {"data": {"id": "ses-1"}})
        if request.method == "POST" and request.url.path == "/api/session/ses-1/generate":
            assert json.loads(request.content) == {"prompt": "hello"}
            return _ok_response(200, {"data": {"text": "answer-text"}})
        if request.method == "POST" and request.url.path == "/api/session/ses-1/interrupt":
            assert request.url.query == b"resume=false"
            return httpx.Response(200, json={"ok": True})
        if request.method == "DELETE" and request.url.path == "/api/session/ses-1":
            return httpx.Response(200, json={"ok": True})
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    client = _make_client(handler)
    try:
        await client.health()
        session_id = await client.create_session()
        assert session_id == "ses-1"
        text = await client.generate(session_id, "hello")
        assert text == "answer-text"
        await client.interrupt(session_id)
        await client.delete(session_id)
    finally:
        await client.aclose()


async def test_session_id_nested_data_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return _ok_response(200, {"data": {"id": "ses-nested"}})

    client = _make_client(handler)
    try:
        assert await client.create_session() == "ses-nested"
    finally:
        await client.aclose()


async def test_session_id_top_level_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return _ok_response(200, {"id": "ses-top"})

    client = _make_client(handler)
    try:
        assert await client.create_session() == "ses-top"
    finally:
        await client.aclose()


async def test_delete_no_content_accepted() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url.path))
        return httpx.Response(204)

    client = _make_client(handler)
    try:
        await client.delete("ses-1")
        assert seen == ["/api/session/ses-1"]
    finally:
        await client.aclose()


async def test_unsafe_session_id_rejected_without_request() -> None:
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url.path))
        return _ok_response(200, {"data": {"text": "x"}})

    client = _make_client(handler)
    try:
        with pytest.raises(TransportError):
            await client.generate("../evil", "hi")
        with pytest.raises(TransportError):
            await client.interrupt("a/b")
        with pytest.raises(TransportError):
            await client.delete("ses with space")
        assert sent == []
    finally:
        await client.aclose()


async def test_session_id_missing_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return _ok_response(200, {"noid": True})

    client = _make_client(handler)
    try:
        with pytest.raises(TransportError):
            await client.create_session()
    finally:
        await client.aclose()


async def test_generate_missing_text_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/session":
            return _ok_response(200, {"id": "s"})
        return _ok_response(200, {"data": {}})

    client = _make_client(handler)
    try:
        with pytest.raises(TransportError):
            await client.generate("s", "hi")
    finally:
        await client.aclose()


async def test_redirect_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(302, headers={"location": "/api/other"})

    client = _make_client(handler)
    try:
        with pytest.raises(TransportError, match="redirect"):
            await client.health()
    finally:
        await client.aclose()


async def test_non_json_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(200, content=b"not json", headers={"content-type": "text/plain"})

    client = _make_client(handler)
    try:
        with pytest.raises(TransportError):
            await client.create_session()
    finally:
        await client.aclose()


async def test_malformed_json_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(200, content=b'{"id":', headers={"content-type": "application/json"})

    client = _make_client(handler)
    try:
        with pytest.raises(TransportError):
            await client.create_session()
    finally:
        await client.aclose()


async def test_unauthorized_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(401, json={"error": "nope"})

    client = _make_client(handler)
    try:
        with pytest.raises(TransportError):
            await client.health()
    finally:
        await client.aclose()


async def test_oversize_response_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        big = "x" * (300 * 1024)
        return httpx.Response(
            200,
            content=json.dumps({"data": {"text": big}}).encode(),
            headers={"content-type": "application/json"},
        )

    client = _make_client(handler)
    try:
        with pytest.raises(TransportError, match="too large"):
            await client.generate("s", "hi")
    finally:
        await client.aclose()


async def test_closed_client_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return _ok_response(200, {})

    client = _make_client(handler)
    await client.aclose()
    with pytest.raises(TransportError):
        await client.health()
