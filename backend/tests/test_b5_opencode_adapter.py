from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from rakathon_backend.b5.opencode.adapter import OpenCodeAdapter
from rakathon_backend.b5.opencode.client import OpenCodeClient
from rakathon_backend.b5.opencode.process import OpenCodeProcess
from rakathon_backend.common.errors import ContractError, TransportError

_BUNDLE = {
    "resourceType": "Bundle",
    "type": "transaction",
    "entry": [
        {
            "fullUrl": "urn:uuid:patient-p1",
            "resource": {"resourceType": "Patient", "id": "p1", "name": [{"text": "N"}]},
            "request": {"method": "PUT", "url": "Patient/p1"},
        },
        {
            "fullUrl": "urn:uuid:sr-p1",
            "resource": {
                "resourceType": "ServiceRequest",
                "id": "sr-p1",
                "status": "active",
                "intent": "order",
                "subject": {"reference": "Patient/p1"},
            },
            "request": {"method": "PUT", "url": "ServiceRequest/sr-p1"},
        },
    ],
}

_OUTCOME = {
    "resourceType": "OperationOutcome",
    "issue": [{"severity": "information", "code": "incomplete"}],
}


def _adapter(handler: Any) -> tuple[OpenCodeAdapter, dict[str, Any]]:
    seen: dict[str, Any] = {}
    transport = httpx.MockTransport(handler)
    client = OpenCodeClient(
        "http://127.0.0.1:4099",
        "pw-value-12345678901234567890",
        "local",
        "tiny",
        timeout=5.0,
        transport=transport,
    )
    process = OpenCodeProcess(
        "opencode", "2.0.31", "local", "tiny", "http://127.0.0.1:11434", startup_timeout=1.0
    )
    return OpenCodeAdapter(client, process), seen


def _ok_handler(model_text: str, seen: dict[str, Any]) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/session":
            body = json.loads(request.content)
            assert body["model"] == {"providerID": "local", "id": "tiny"}
            assert body["permissions"] == [{"action": "*", "resource": "*", "effect": "deny"}]
            return httpx.Response(200, json={"data": {"id": "ses-9"}})
        if "/generate" in request.url.path:
            body = json.loads(request.content)
            seen["prompt"] = body["prompt"]
            return httpx.Response(200, json={"data": {"text": model_text}})
        if "/interrupt" in request.url.path:
            seen["interrupted"] = True
            return httpx.Response(200, json={"ok": True})
        if request.method == "DELETE":
            seen["deleted"] = seen.get("deleted", 0) + 1
            return httpx.Response(200, json={"ok": True})
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    return handler


async def test_translate_bundle_happy_path() -> None:
    adapter, seen = _adapter(_ok_handler(json.dumps({"bundle": _BUNDLE}), {}))
    _ = seen
    try:
        result = await adapter.translate(b"patient p1 needs referral", "text/plain")
        assert result["bundle"]["resourceType"] == "Bundle"
        assert result["mode"] == "opencode"
        assert result["synthetic"] is False
    finally:
        await adapter.close()


async def test_translate_prompt_carries_raw_data() -> None:
    seen: dict[str, Any] = {}
    adapter, _ = _adapter(_ok_handler(json.dumps({"bundle": _BUNDLE}), seen))
    try:
        await adapter.translate(b"raw-marker-xyz-123", "text/plain")
        assert "raw-marker-xyz-123" in seen["prompt"]
    finally:
        await adapter.close()


async def test_translate_outcome_manual_review() -> None:
    text = json.dumps({"outcome": _OUTCOME, "manualReview": True})
    adapter, _ = _adapter(_ok_handler(text, {}))
    try:
        result = await adapter.translate(b"incomplete", "text/plain")
        assert result["bundle"]["resourceType"] == "OperationOutcome"
        assert result["mode"] == "opencode"
    finally:
        await adapter.close()


@pytest.mark.parametrize(
    "model_text",
    [
        "not json at all",
        "[1, 2, 3]",
        json.dumps({"answer": "wrong shape"}),
        json.dumps({"bundle": {"resourceType": "Patient"}}),
        json.dumps({"outcome": _OUTCOME}),
        json.dumps({"outcome": _OUTCOME, "manualReview": False}),
        "",
    ],
)
async def test_translate_invalid_model_output_refused(model_text: str) -> None:
    adapter, _ = _adapter(_ok_handler(model_text, {}))
    try:
        with pytest.raises(TransportError):
            await adapter.translate(b"some text", "text/plain")
    finally:
        await adapter.close()


async def test_complete_happy_path() -> None:
    adapter, _ = _adapter(_ok_handler("plain answer", {}))
    try:
        result = await adapter.complete(b"question?", "text/plain")
        assert result["answer"] == "plain answer"
        assert result["mode"] == "opencode"
    finally:
        await adapter.close()


async def test_complete_empty_text_refused() -> None:
    adapter, _ = _adapter(_ok_handler("   ", {}))
    try:
        with pytest.raises(TransportError):
            await adapter.complete(b"question?", "text/plain")
    finally:
        await adapter.close()


async def test_runtime_failure_has_no_mock_fallback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(500, json={"error": "down"})

    adapter, _ = _adapter(handler)
    try:
        with pytest.raises(TransportError):
            await adapter.translate(b"some text", "text/plain")
        with pytest.raises(TransportError):
            await adapter.complete(b"some text", "text/plain")
    finally:
        await adapter.close()


async def test_oversize_input_refused() -> None:
    adapter, _ = _adapter(_ok_handler("x", {}))
    try:
        with pytest.raises(TransportError):
            await adapter.translate(b"x" * 70000, "text/plain")
    finally:
        await adapter.close()


async def test_cancel_interrupts_session_and_deletes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/session":
            return httpx.Response(200, json={"data": {"id": "ses-c"}})
        if "/generate" in request.url.path:
            seen["prompt"] = json.loads(request.content)["prompt"]
            raise httpx.ConnectError("cancelled-by-test")
        if "/interrupt" in request.url.path:
            seen["interrupted"] = True
            return httpx.Response(200, json={"ok": True})
        if request.method == "DELETE":
            seen["deleted"] = True
            return httpx.Response(200, json={"ok": True})
        raise AssertionError("unexpected path")

    adapter, seen = _adapter(handler)
    try:
        with pytest.raises(TransportError):
            await adapter.translate(b"data", "text/plain")
        assert seen.get("deleted") is True
    finally:
        await adapter.close()


async def test_inflight_cancel_no_orphan_session() -> None:
    seen: dict[str, Any] = {}
    release = asyncio.Event()

    async def slow_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/session":
            return httpx.Response(200, json={"data": {"id": "ses-slow"}})
        if "/generate" in request.url.path:
            await release.wait()
            return httpx.Response(200, json={"data": {"text": "late"}})
        if request.method == "DELETE":
            seen["deleted"] = True
            return httpx.Response(200, json={"ok": True})
        if "/interrupt" in request.url.path:
            seen["interrupted"] = True
            return httpx.Response(200, json={"ok": True})
        raise AssertionError("unexpected path")

    transport = httpx.MockTransport(slow_handler)
    client = OpenCodeClient(
        "http://127.0.0.1:4099",
        "pw-value-12345678901234567890",
        "local",
        "tiny",
        timeout=5.0,
        transport=transport,
    )
    process = OpenCodeProcess(
        "opencode", "2.0.31", "local", "tiny", "http://127.0.0.1:11434", startup_timeout=1.0
    )
    adapter = OpenCodeAdapter(client, process)
    try:
        task = asyncio.create_task(adapter.translate(b"data", "text/plain"))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        await asyncio.sleep(0.05)
        assert seen.get("interrupted") is True
        assert seen.get("deleted") is True
    finally:
        release.set()
        await adapter.close()


async def test_close_idempotent() -> None:
    adapter, _ = _adapter(_ok_handler("x", {}))
    await adapter.close()
    await adapter.close()
    with pytest.raises(TransportError):
        await adapter.translate(b"x", "text/plain")


async def test_unsupported_content_type_rejected() -> None:
    adapter, _ = _adapter(_ok_handler("x", {}))
    try:
        with pytest.raises(ContractError):
            await adapter.translate(b"%PDF", "application/pdf")
    finally:
        await adapter.close()
