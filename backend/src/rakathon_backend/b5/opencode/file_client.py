from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from rakathon_backend.b5.opencode.client import OpenCodeClient
from rakathon_backend.b5.opencode.file_errors import FilePromptError, collect_own_text
from rakathon_backend.b5.opencode.validation import (
    MAX_PROMPT_CHARS,
    MAX_RESPONSE_BYTES,
    validate_session_id,
)
from rakathon_backend.common.errors import TransportError

FILE_ALLOWED_ROOT = "/input"
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_FILES = 2
MAX_TOTAL_BYTES = 10 * 1024 * 1024
MAX_FILENAME_CHARS = 255
MAX_PDF_PAGES = 4
MAX_MESSAGE_PAGES = 10
MAX_MESSAGES = 200
MAX_PAGE_BYTES = 1024 * 1024
MAX_RESULT_BYTES = MAX_RESPONSE_BYTES
MESSAGE_LIMIT = 50
ALLOWED_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"})


@dataclass(frozen=True, slots=True)
class FilePromptResult:
    text: str
    assistant_id: str | None
    admission_id: str | None


class OpenCodeFileClient(OpenCodeClient):
    def __init__(
        self,
        base_url: str,
        password: str,
        provider_id: str,
        model: str,
        *,
        timeout: float,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        transport: httpx.AsyncBaseTransport | None = None,
        allowed_root: str | Path = FILE_ALLOWED_ROOT,
    ) -> None:
        super().__init__(
            base_url,
            password,
            provider_id,
            model,
            timeout=timeout,
            max_response_bytes=max_response_bytes,
            transport=transport,
        )
        self._root = Path(allowed_root)

    async def prompt_files(self, session_id: str, text: str, paths: list[Path]) -> FilePromptResult:
        files = self._file_uris(paths)
        admission_id = await self._admit(session_id, text, files)
        await self.wait_for_idle(session_id)
        return await self._read_after(session_id, admission_id)

    async def prompt_text(self, session_id: str, text: str) -> FilePromptResult:
        admission_id = await self._admit(session_id, text, [])
        await self.wait_for_idle(session_id)
        return await self._read_after(session_id, admission_id)

    async def wait_for_idle(self, session_id: str) -> None:
        try:
            clean = validate_session_id(session_id)
        except ValueError as exc:
            raise TransportError(code="ai_bad_session", message=str(exc)) from exc
        if self._closed:
            raise TransportError(code="ai_closed", message="opencode client is closed")
        path = f"/api/experimental/session/{quote(clean, safe='')}/wait"
        try:
            async with self._http.stream("POST", path, json=None) as response:
                if 300 <= response.status_code < 400:
                    raise TransportError(code="ai_redirect", message="opencode refused redirect")
                if response.status_code == 401:
                    raise TransportError(code="ai_auth", message="opencode rejected credentials")
                if response.status_code != 204:
                    raise TransportError(
                        code="ai_status",
                        message=f"opencode wait returned status {response.status_code}",
                    )
        except TransportError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TransportError(code="ai_transport", message="opencode transport failed") from exc
        except (httpx.HTTPError, OSError) as exc:
            raise TransportError(code="ai_transport", message="opencode request failed") from exc

    def _file_uris(self, paths: list[Path]) -> list[dict[str, str]]:
        if not paths or len(paths) > MAX_FILES:
            raise TransportError(code="ai_bad_input", message="file count is outside the limit")
        try:
            root = self._root.resolve()
        except OSError as exc:
            raise TransportError(code="ai_bad_input", message="allowed root is unusable") from exc
        total = 0
        files: list[dict[str, str]] = []
        for raw in paths:
            resolved = self._resolve_one(raw, root)
            size = self._regular_size(resolved)
            if size > MAX_FILE_BYTES:
                raise TransportError(code="ai_too_large", message="file exceeds per-file size cap")
            total += size
            if total > MAX_TOTAL_BYTES:
                raise TransportError(code="ai_too_large", message="files exceed total size cap")
            uri = "file://" + quote(resolved.as_posix(), safe="/")
            files.append({"uri": uri, "name": resolved.name})
        return files

    def _resolve_one(self, raw: Path, root: Path) -> Path:
        try:
            text = os.fspath(raw)
            name = raw.name
            suffix = raw.suffix
            linked = raw.is_symlink()
        except (AttributeError, TypeError, OSError, ValueError) as exc:
            raise TransportError(code="ai_bad_input", message="file path is unusable") from exc
        if "://" in text or "\x00" in text:
            raise TransportError(code="ai_bad_input", message="file path carries an unsafe marker")
        if name in ("", ".", "..") or "\x00" in name or len(name) > MAX_FILENAME_CHARS:
            raise TransportError(code="ai_bad_input", message="file name is outside the limit")
        if suffix.lower() not in ALLOWED_SUFFIXES:
            raise TransportError(code="ai_bad_input", message="file type is not an allowed image")
        if linked:
            raise TransportError(code="ai_bad_input", message="file path is a symlink")
        try:
            resolved = raw.resolve()
        except OSError as exc:
            raise TransportError(
                code="ai_bad_input", message="file path cannot be resolved"
            ) from exc
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise TransportError(
                code="ai_bad_input", message="file path is outside the root"
            ) from exc
        return resolved

    def _regular_size(self, resolved: Path) -> int:
        try:
            info = resolved.stat()
        except OSError as exc:
            raise TransportError(code="ai_bad_input", message="file cannot be inspected") from exc
        if not stat.S_ISREG(info.st_mode):
            raise TransportError(code="ai_bad_input", message="file is not a regular file")
        return int(info.st_size)

    async def _admit(self, session_id: str, text: str, files: list[dict[str, str]]) -> str | None:
        if not isinstance(text, str) or not text or len(text) > MAX_PROMPT_CHARS:
            raise TransportError(code="ai_bad_input", message="prompt text is outside the limit")
        path = self._session_path(session_id, "/prompt")
        body = await self._request(
            "POST", path, {"text": text, "files": files, "resume": True}, expect_json=True
        )
        if isinstance(body, dict) and isinstance(body.get("data"), dict):
            candidate = body["data"].get("id")
            if isinstance(candidate, str) and candidate:
                return candidate
        return None

    async def _read_after(self, session_id: str, after_id: str | None) -> FilePromptResult:
        path = self._session_path(session_id, "/message")
        messages: list[Any] = []
        seen: set[str] = set()
        cursor: str | None = None
        text_bytes = 0
        for _ in range(MAX_MESSAGE_PAGES):
            if cursor is None:
                query = urlencode({"limit": str(MESSAGE_LIMIT), "order": "asc"})
            else:
                query = urlencode({"cursor": cursor})
            body = await self._request("GET", path, None, expect_json=True, query=query)
            data, nxt = self._parse_page(body)
            messages.extend(data)
            if len(messages) > MAX_MESSAGES:
                raise TransportError(code="ai_too_large", message="message history is too large")
            for entry in data:
                text_bytes += self._count_text_bytes(entry)
                if text_bytes > MAX_PAGE_BYTES:
                    raise TransportError(
                        code="ai_too_large", message="message history is too large"
                    )
            if nxt is None:
                break
            if nxt in seen:
                raise TransportError(code="ai_bad_output", message="message cursor repeated")
            seen.add(nxt)
            cursor = nxt
        else:
            raise TransportError(code="ai_truncated", message="message history was truncated")
        return self._select(messages, after_id)

    def _parse_page(self, body: Any) -> tuple[list[Any], str | None]:
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            raise TransportError(code="ai_bad_output", message="message page has no data array")
        cursor = body.get("cursor")
        if not isinstance(cursor, dict):
            raise TransportError(code="ai_bad_output", message="message page has no cursor")
        nxt = cursor.get("next")
        if nxt is not None and not isinstance(nxt, str):
            raise TransportError(code="ai_bad_output", message="message cursor is malformed")
        prev = cursor.get("previous")
        if prev is not None and not isinstance(prev, str):
            raise TransportError(code="ai_bad_output", message="message cursor is malformed")
        return (body["data"], nxt)

    def _count_text_bytes(self, entry: Any) -> int:
        if not isinstance(entry, dict) or not isinstance(entry.get("content"), list):
            return 0
        total = 0
        for chunk in entry["content"]:
            if isinstance(chunk, dict) and chunk.get("type") == "text":
                piece = chunk.get("text")
                if isinstance(piece, str):
                    total += len(piece.encode("utf-8"))
        return total

    def _check_idle(self, entry: dict[str, Any]) -> None:
        if entry.get("error") is not None:
            raise FilePromptError(code="ai_bad_output", message="session ended with an error")
        if entry.get("outcome") != "succeeded":
            raise FilePromptError(code="ai_bad_output", message="session did not succeed")

    def _select(self, messages: list[Any], after_id: str | None) -> FilePromptResult:
        start = 0
        if after_id is not None:
            found = False
            for index, entry in enumerate(messages):
                if isinstance(entry, dict) and entry.get("id") == after_id:
                    start = index + 1
                    found = True
                    break
            if not found:
                raise FilePromptError(
                    code="ai_bad_output", message="admission message was not found"
                )
        tail = messages[start:]
        assistants = [
            entry for entry in tail if isinstance(entry, dict) and entry.get("type") == "assistant"
        ]
        for entry in tail:
            if isinstance(entry, dict) and entry.get("type") == "idle":
                self._check_idle(entry)
        if not assistants:
            raise FilePromptError(code="ai_bad_output", message="no assistant message was found")
        term = assistants[-1]
        if not isinstance(term, dict):
            raise FilePromptError(code="ai_bad_output", message="assistant message is malformed")
        partial = collect_own_text(term.get("content"))
        if term.get("finish") != "stop":
            raise FilePromptError(
                code="ai_bad_output",
                message="assistant finish was not stop",
                partial_text=partial,
            )
        moment = term.get("time")
        if (
            not isinstance(moment, dict)
            or isinstance(moment.get("completed"), bool)
            or not isinstance(moment.get("completed"), (int, float))
        ):
            raise FilePromptError(
                code="ai_bad_output",
                message="assistant message is unfinished",
                partial_text=partial,
            )
        if term.get("error") is not None or term.get("retry"):
            raise FilePromptError(
                code="ai_bad_output",
                message="assistant message carries an error",
                partial_text=partial,
            )
        content = term.get("content")
        if not isinstance(content, list) or not content:
            raise FilePromptError(
                code="ai_bad_output",
                message="assistant message has no content",
                partial_text=partial,
            )
        parts: list[str] = []
        for chunk in content:
            if not isinstance(chunk, dict):
                raise FilePromptError(
                    code="ai_bad_output",
                    message="assistant content is malformed",
                    partial_text=None,
                )
            kind = chunk.get("type")
            if kind == "text":
                piece = chunk.get("text")
                if not isinstance(piece, str):
                    raise FilePromptError(
                        code="ai_bad_output",
                        message="assistant text is malformed",
                        partial_text=None,
                    )
                parts.append(piece)
            elif kind == "tool":
                raise FilePromptError(
                    code="ai_bad_output",
                    message="assistant used a tool call",
                    partial_text=partial,
                )
        text = "".join(parts)
        if not text.strip():
            raise FilePromptError(
                code="ai_bad_output", message="assistant text is empty", partial_text=None
            )
        if len(text.encode("utf-8")) > MAX_RESULT_BYTES:
            raise FilePromptError(
                code="ai_too_large",
                message="assistant text exceeds size cap",
                partial_text=text,
            )
        assistant_id = term.get("id")
        return FilePromptResult(
            text=text,
            assistant_id=assistant_id if isinstance(assistant_id, str) else None,
            admission_id=after_id,
        )
