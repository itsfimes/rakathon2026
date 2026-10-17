from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from rakathon_backend.b5.opencode.file_client import MAX_RESULT_BYTES, OpenCodeFileClient
from rakathon_backend.b5.opencode.file_errors import FilePromptError
from rakathon_backend.common.errors import TransportError


def _assistant(mid: str, content: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": mid,
        "type": "assistant",
        "time": {"created": 1.0, "completed": 2.0},
        "finish": "stop",
        "content": content,
    }
    base.update(extra)
    return base


def _text_piece(value: str) -> dict[str, Any]:
    return {"type": "text", "text": value}


def _user(mid: str) -> dict[str, Any]:
    return {"id": mid, "type": "user", "time": {"created": 0.5}}


def _idle(mid: str, outcome: str) -> dict[str, Any]:
    return {"id": mid, "type": "idle", "time": {"created": 3.0}, "outcome": outcome}


def _make_client(root: Path) -> OpenCodeFileClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request must be sent")

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


async def test_admission_missing_rejects_without_partial(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    try:
        messages: list[Any] = [
            _user("msg-u-old"),
            _assistant("msg-a-old", [_text_piece("old-secret-text")]),
            _idle("idle-old", "succeeded"),
        ]
        with pytest.raises(FilePromptError) as excinfo:
            client._select(messages, "msg-u-new")
        exc = excinfo.value
        assert exc.code == "ai_bad_output"
        assert getattr(exc, "partial_text", None) is None
        assert "old-secret-text" not in str(exc)
        assert "old-secret-text" not in repr(exc)
        assert isinstance(exc, TransportError)
    finally:
        await client.aclose()


async def test_finish_length_returns_bounded_own_text(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    try:
        own = _assistant("msg-a2", [_text_piece("own-partial-text")], finish="length")
        messages: list[Any] = [
            _user("msg-u1"),
            _assistant("msg-a1", [_text_piece("prior-secret-text")]),
            _user("msg-u2"),
            own,
            _idle("idle-2", "succeeded"),
        ]
        with pytest.raises(FilePromptError) as excinfo:
            client._select(messages, "msg-u2")
        exc = excinfo.value
        assert exc.code == "ai_bad_output"
        assert exc.partial_text == "own-partial-text"
        assert "prior-secret-text" not in (exc.partial_text or "")
        assert "own-partial-text" not in str(exc)
        assert exc.metadata == {}
    finally:
        await client.aclose()


async def test_error_and_retry_partial_excludes_reasoning(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    try:
        err = _assistant(
            "msg-a1",
            [{"type": "reasoning", "text": "reason-secret"}, _text_piece("own-err-text")],
            error={"type": "upstream", "message": "kept-secret"},
        )
        with pytest.raises(FilePromptError) as excinfo:
            client._select([_user("msg-u1"), err, _idle("i1", "succeeded")], "msg-u1")
        assert excinfo.value.partial_text == "own-err-text"
        assert "reason-secret" not in (excinfo.value.partial_text or "")
        assert "kept-secret" not in str(excinfo.value)
        retry = _assistant(
            "msg-a1",
            [{"type": "reasoning", "text": "reason-secret-2"}, _text_piece("own-retry-text")],
            retry={"at": 1.0},
        )
        with pytest.raises(FilePromptError) as excinfo2:
            client._select([_user("msg-u1"), retry, _idle("i1", "succeeded")], "msg-u1")
        assert excinfo2.value.partial_text == "own-retry-text"
        assert "reason-secret-2" not in (excinfo2.value.partial_text or "")
    finally:
        await client.aclose()


async def test_tool_chunk_partial_excludes_tool(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    try:
        term = _assistant(
            "msg-a1",
            [_text_piece("own-tool-text"), {"type": "tool", "id": "t", "name": "read"}],
        )
        with pytest.raises(FilePromptError) as excinfo:
            client._select([_user("msg-u1"), term, _idle("i1", "succeeded")], "msg-u1")
        assert excinfo.value.code == "ai_bad_output"
        assert excinfo.value.partial_text == "own-tool-text"
    finally:
        await client.aclose()


async def test_oversize_truncates_utf8_safely(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    try:
        big = "é" * (300 * 1024)
        term = _assistant("msg-a1", [_text_piece(big)])
        with pytest.raises(FilePromptError) as excinfo:
            client._select([_user("msg-u1"), term, _idle("i1", "succeeded")], "msg-u1")
        exc = excinfo.value
        assert exc.code == "ai_too_large"
        assert exc.partial_text is not None
        raw = exc.partial_text.encode("utf-8")
        assert len(raw) <= MAX_RESULT_BYTES
        assert exc.partial_text.encode("utf-8").decode("utf-8") == exc.partial_text
        assert big.startswith(exc.partial_text[:1024])
        edge = "a" * (MAX_RESULT_BYTES - 1) + "é"
        term2 = _assistant("msg-a2", [_text_piece(edge)])
        with pytest.raises(FilePromptError) as excinfo2:
            client._select([_user("msg-u1"), term2, _idle("i1", "succeeded")], "msg-u1")
        part2 = excinfo2.value.partial_text
        assert part2 is not None
        assert len(part2.encode("utf-8")) <= MAX_RESULT_BYTES
        assert part2.encode("utf-8").decode("utf-8") == part2
        assert part2 == "a" * (MAX_RESULT_BYTES - 1)
    finally:
        await client.aclose()


async def test_idle_checked_before_no_assistant(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    try:
        with pytest.raises(FilePromptError) as excinfo:
            client._select([_user("msg-u1"), _idle("i1", "failed")], "msg-u1")
        assert excinfo.value.code == "ai_bad_output"
        assert "did not succeed" in str(excinfo.value)
        assert getattr(excinfo.value, "partial_text", None) is None
        bad_idle = {
            "id": "i1",
            "type": "idle",
            "time": {"created": 3.0},
            "outcome": "failed",
            "error": {"type": "x", "message": "kept-secret"},
        }
        with pytest.raises(FilePromptError) as excinfo2:
            client._select([_user("msg-u1"), bad_idle], "msg-u1")
        assert "ended with an error" in str(excinfo2.value)
        assert "kept-secret" not in str(excinfo2.value)
    finally:
        await client.aclose()


async def test_empty_partial_is_none(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    try:
        term = _assistant("msg-a1", [_text_piece("   ")])
        with pytest.raises(FilePromptError) as excinfo:
            client._select([_user("msg-u1"), term, _idle("i1", "succeeded")], "msg-u1")
        assert getattr(excinfo.value, "partial_text", None) is None
    finally:
        await client.aclose()
