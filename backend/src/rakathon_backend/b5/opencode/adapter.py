from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import httpx

from rakathon_backend.b5.opencode.client import OpenCodeClient
from rakathon_backend.b5.opencode.config import OpenCodeConfig
from rakathon_backend.b5.opencode.process import OpenCodeProcess
from rakathon_backend.b5.opencode.validation import (
    MAX_INPUT_BYTES,
    build_complete_prompt,
    build_translate_prompt,
    parse_model_output,
)
from rakathon_backend.common.errors import ContractError, TransportError


class OpenCodeAdapter:
    def __init__(self, client: OpenCodeClient, process: OpenCodeProcess) -> None:
        self._client = client
        self._process = process
        self._closed = False
        self._lock = asyncio.Lock()

    @classmethod
    async def create(
        cls,
        config: OpenCodeConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        api_key: str = "",
    ) -> OpenCodeAdapter:
        if not config.ready:
            raise TransportError(code="ai_disabled", message="opencode runtime is not enabled")
        process = OpenCodeProcess(
            config.binary,
            config.expected_version,
            config.provider_id,
            config.model,
            config.base_url,
            startup_timeout=config.startup_timeout,
            api_key=api_key,
            provider_kind=config.provider_kind,
        )
        base_url = await process.start()
        username, password = process.auth()
        client = OpenCodeClient(
            base_url,
            password,
            config.provider_id,
            config.model,
            timeout=config.request_timeout,
            transport=transport,
        )
        _ = username
        return cls(client, process)

    @property
    def closed(self) -> bool:
        return self._closed

    async def translate(self, data: bytes, content_type: str) -> dict[str, Any]:
        self._ensure_open()
        text = self._decode(data, content_type)
        try:
            prompt = build_translate_prompt(text)
        except ValueError as exc:
            raise TransportError(code="ai_too_large", message=str(exc)) from exc
        try:
            raw = await self._generate(prompt)
        except (ContractError, TransportError):
            raise
        except Exception as exc:
            raise TransportError(code="ai_failed", message="opencode translate failed") from exc
        try:
            parsed = parse_model_output(raw)
        except (TypeError, ValueError) as exc:
            raise TransportError(code="ai_bad_output", message=str(exc)) from exc
        return {**parsed, "mode": "opencode", "synthetic": False}

    async def complete(self, data: bytes, content_type: str) -> dict[str, Any]:
        self._ensure_open()
        text = self._decode(data, content_type)
        try:
            prompt = build_complete_prompt(text)
        except ValueError as exc:
            raise TransportError(code="ai_too_large", message=str(exc)) from exc
        try:
            raw = await self._generate(prompt)
        except (ContractError, TransportError):
            raise
        except Exception as exc:
            raise TransportError(code="ai_failed", message="opencode complete failed") from exc
        if not raw.strip():
            raise TransportError(code="ai_bad_output", message="opencode returned empty text")
        return {"answer": raw, "mode": "opencode", "synthetic": False}

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
        with contextlib.suppress(Exception):
            await self._client.aclose()
        with contextlib.suppress(Exception):
            await self._process.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise TransportError(code="ai_closed", message="opencode adapter is closed")

    def _decode(self, data: bytes, content_type: str) -> str:
        if len(data) > MAX_INPUT_BYTES:
            raise TransportError(code="ai_too_large", message="AI input exceeds size cap")
        if content_type not in ("text/plain", "application/json"):
            raise ContractError(code="bad_payload", message="unsupported content type")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContractError(code="bad_payload", message="input is not valid UTF-8") from exc

    async def _generate(self, prompt: str) -> str:
        session_id = await self._client.create_session()
        try:
            try:
                return await self._client.generate(session_id, prompt)
            except asyncio.CancelledError:
                with contextlib.suppress(Exception):
                    await asyncio.shield(self._client.interrupt(session_id))
                raise
        finally:
            with contextlib.suppress(Exception):
                await self._client.delete(session_id)
