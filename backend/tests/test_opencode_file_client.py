from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import pytest

from rakathon_backend.b5.opencode.file_client import MAX_FILE_BYTES, OpenCodeFileClient
from rakathon_backend.common.errors import TransportError


def _assistant(mid: str, content: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": mid,
        "type": "assistant",
        "time": {"created": 1.0, "completed": 2.0},
        "finish": "stop",
        "content": content,
    }


def _text_piece(value: str) -> dict[str, Any]:
    return {"type": "text", "text": value}


def _user(mid: str) -> dict[str, Any]:
    return {"id": mid, "type": "user", "time": {"created": 0.5}}


def _idle(mid: str, outcome: str) -> dict[str, Any]:
    return {"id": mid, "type": "idle", "time": {"created": 3.0}, "outcome": outcome}


def _page(data: list[dict[str, Any]], nxt: str | None) -> httpx.Response:
    return httpx.Response(200, json={"data": data, "cursor": {"previous": None, "next": nxt}})


def _make_client(handler: Any, root: Path) -> OpenCodeFileClient:
    transport = httpx.MockTransport(handler)
    return OpenCodeFileClient(
        "http://127.0.0.1:4099",
        "pw-secret-value-1234567890",
        "rakathon-azure",
        "gpt-6-luna-dz-eu",
        timeout=5.0,
        transport=transport,
        allowed_root=root,
    )


def _image(root: Path, name: str) -> Path:
    target = root / name
    target.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    return target


async def test_prompt_files_paginated_text_ignores_reasoning(tmp_path: Path) -> None:
    root = tmp_path / "input"
    root.mkdir()
    img = _image(root, "scan.png")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/session/ses-1/prompt":
            body = json.loads(request.content)
            seen["prompt"] = body
            assert body["resume"] is True
            assert body["text"] == "read this"
            assert body["files"] == [
                {"uri": "file://" + quote(str(img), safe="/"), "name": "scan.png"}
            ]
            return httpx.Response(200, json={"data": {"id": "msg-u1"}})
        if request.method == "POST" and request.url.path == "/api/experimental/session/ses-1/wait":
            return httpx.Response(204)
        if request.method == "GET" and request.url.path == "/api/session/ses-1/message":
            params = dict(request.url.params)
            if "cursor" not in params:
                assert params["limit"] == "50"
                assert params["order"] == "asc"
                return _page([_user("msg-u1")], "c1")
            assert params["cursor"] == "c1"
            assert "order" not in params
            assistant = _assistant(
                "msg-a1", [{"type": "reasoning", "text": "hmm"}, _text_piece("A"), _text_piece("B")]
            )
            return _page([assistant, _idle("idle-1", "succeeded")], None)
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    client = _make_client(handler, root)
    try:
        result = await client.prompt_files("ses-1", "read this", [img])
        assert result.text == "AB"
        assert result.assistant_id == "msg-a1"
        assert result.admission_id == "msg-u1"
    finally:
        await client.aclose()


async def test_two_turn_returns_latest_only(tmp_path: Path) -> None:
    root = tmp_path / "input"
    root.mkdir()
    img = _image(root, "scan.png")
    history: list[dict[str, Any]] = []
    admissions = iter(["msg-u1", "msg-u2"])
    assistant_text = {"msg-u1": "first", "msg-u2": "second"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/prompt"):
            body = json.loads(request.content)
            admission = next(admissions)
            history.append(_user(admission))
            history.append(_assistant("a-" + admission, [_text_piece(assistant_text[admission])]))
            history.append(_idle("i-" + admission, "succeeded"))
            if admission == "msg-u2":
                assert body["files"] == []
            return httpx.Response(200, json={"data": {"id": admission}})
        if request.url.path.endswith("/wait"):
            return httpx.Response(204)
        if request.method == "GET" and request.url.path.endswith("/message"):
            return _page(list(history), None)
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    client = _make_client(handler, root)
    try:
        first = await client.prompt_files("ses-9", "turn one", [img])
        assert first.text == "first"
        second = await client.prompt_text("ses-9", "turn two")
        assert second.text == "second"
        assert second.admission_id == "msg-u2"
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "mutate",
    [
        "finish-length",
        "finish-tool-calls",
        "assistant-error",
        "assistant-retry",
        "assistant-unfinished",
        "assistant-tool-chunk",
        "assistant-empty",
        "no-assistant",
        "idle-failed",
        "idle-error",
    ],
)
async def test_terminal_failures_rejected(tmp_path: Path, mutate: str) -> None:
    root = tmp_path / "input"
    root.mkdir()
    assistant = _assistant("msg-a1", [_text_piece("hello")])
    idle = _idle("idle-1", "succeeded")
    if mutate == "finish-length":
        assistant["finish"] = "length"
    elif mutate == "finish-tool-calls":
        assistant["finish"] = "tool-calls"
    elif mutate == "assistant-error":
        assistant["error"] = {"type": "upstream", "message": "kept-secret"}
    elif mutate == "assistant-retry":
        assistant["retry"] = {"at": 1.0}
    elif mutate == "assistant-unfinished":
        assistant["time"] = {"created": 1.0}
    elif mutate == "assistant-tool-chunk":
        assistant["content"] = [{"type": "tool", "id": "t", "name": "read"}]
    elif mutate == "assistant-empty":
        assistant["content"] = [_text_piece("   ")]
    elif mutate == "idle-failed":
        idle = _idle("idle-1", "failed")
    elif mutate == "idle-error":
        idle = {
            "id": "idle-1",
            "type": "idle",
            "time": {"created": 3.0},
            "outcome": "failed",
            "error": {"type": "x", "message": "kept-secret"},
        }
    data = [_user("msg-u1")]
    if mutate != "no-assistant":
        data = [_user("msg-u1"), assistant, idle]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/prompt"):
            return httpx.Response(200, json={"data": {"id": "msg-u1"}})
        if request.url.path.endswith("/wait"):
            return httpx.Response(204)
        if request.method == "GET" and request.url.path.endswith("/message"):
            return _page(data, None)
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    client = _make_client(handler, root)
    try:
        with pytest.raises(TransportError):
            await client.prompt_text("ses-1", "hi")
    finally:
        await client.aclose()


async def test_wait_requires_204(tmp_path: Path) -> None:
    root = tmp_path / "input"
    root.mkdir()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/prompt"):
            return httpx.Response(200, json={"data": {"id": "msg-u1"}})
        if request.url.path.endswith("/wait"):
            return httpx.Response(200, json={"ok": True})
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    client = _make_client(handler, root)
    try:
        with pytest.raises(TransportError):
            await client.prompt_text("ses-1", "hi")
    finally:
        await client.aclose()


async def test_cursor_cycle_rejected(tmp_path: Path) -> None:
    root = tmp_path / "input"
    root.mkdir()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/wait"):
            return httpx.Response(204)
        if request.method == "POST":
            return httpx.Response(200, json={"data": {"id": "msg-u1"}})
        if request.method == "GET":
            return _page([_user("msg-u1")], "c-loop")
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    client = _make_client(handler, root)
    try:
        with pytest.raises(TransportError):
            await client.prompt_text("ses-1", "hi")
    finally:
        await client.aclose()


async def test_truncated_history_rejected(tmp_path: Path) -> None:
    root = tmp_path / "input"
    root.mkdir()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/wait"):
            return httpx.Response(204)
        if request.method == "POST":
            return httpx.Response(200, json={"data": {"id": "msg-u1"}})
        if request.method == "GET":
            cursor = request.url.params.get("cursor", "c0")
            return _page([_user("msg-u1")], f"{cursor}-next")
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    client = _make_client(handler, root)
    try:
        with pytest.raises(TransportError, match="truncated"):
            await client.prompt_text("ses-1", "hi")
    finally:
        await client.aclose()


async def test_oversize_assistant_text_rejected(tmp_path: Path) -> None:
    root = tmp_path / "input"
    root.mkdir()
    big = _assistant("msg-a1", [_text_piece("x" * (300 * 1024))])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/wait"):
            return httpx.Response(204)
        if request.method == "POST":
            return httpx.Response(200, json={"data": {"id": "msg-u1"}})
        if request.method == "GET":
            return _page([_user("msg-u1"), big, _idle("idle-1", "succeeded")], None)
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    client = _make_client(handler, root)
    try:
        with pytest.raises(TransportError, match="too large"):
            await client.prompt_text("ses-1", "hi")
    finally:
        await client.aclose()


async def test_unsafe_paths_rejected(tmp_path: Path) -> None:
    root = tmp_path / "input"
    root.mkdir()
    real = _image(root, "real.png")
    link = root / "link.png"
    link.symlink_to(real)
    subdir = root / "sub.png"
    subdir.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"0" * 16)
    pdf = _image(root, "doc.png").rename(root / "doc.pdf")
    big = root / "big.png"
    big.touch()
    os.truncate(big, MAX_FILE_BYTES + 1)
    extra = [_image(root, f"f{i}.png") for i in range(3)]
    candidates = [
        [outside],
        [link],
        [subdir],
        [pdf],
        [big],
        [Path("http://example.com/evil.png")],
        [root / ".." / "outside.png"],
        extra,
        [],
    ]
    for paths in candidates:

        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("no request must be sent")

        client = _make_client(handler, root)
        try:
            with pytest.raises(TransportError):
                await client.prompt_files("ses-1", "hi", paths)
        finally:
            await client.aclose()
