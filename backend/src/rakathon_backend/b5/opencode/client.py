from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import httpx

from rakathon_backend.b5.opencode.validation import (
    API_USERNAME,
    MAX_RESPONSE_BYTES,
    parse_generate_text,
    parse_session_id,
    validate_session_id,
)
from rakathon_backend.common.errors import TransportError


class OpenCodeClient:
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
    ) -> None:
        self._base = base_url.rstrip("/")
        self._provider_id = provider_id
        self._model = model
        self._max_bytes = max_response_bytes
        http_timeout = httpx.Timeout(timeout, connect=min(5.0, timeout))
        self._http = httpx.AsyncClient(
            base_url=self._base,
            auth=httpx.BasicAuth(API_USERNAME, password),
            timeout=http_timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self._closed = False

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._http.aclose()

    async def health(self) -> None:
        body = await self._request("GET", "/api/session", None, expect_json=True)
        _ = body

    async def create_session(self) -> str:
        payload: dict[str, Any] = {
            "model": {"providerID": self._provider_id, "id": self._model},
            "permissions": [{"action": "*", "resource": "*", "effect": "deny"}],
        }
        body = await self._request("POST", "/api/session", payload, expect_json=True)
        try:
            return parse_session_id(body)
        except ValueError as exc:
            raise TransportError(code="ai_bad_session", message=str(exc)) from exc

    def _session_path(self, session_id: str, suffix: str) -> str:
        try:
            clean = validate_session_id(session_id)
        except ValueError as exc:
            raise TransportError(code="ai_bad_session", message=str(exc)) from exc
        return f"/api/session/{quote(clean, safe='')}{suffix}"

    async def generate(self, session_id: str, prompt: str) -> str:
        path = self._session_path(session_id, "/generate")
        body = await self._request("POST", path, {"prompt": prompt}, expect_json=True)
        try:
            return parse_generate_text(body)
        except ValueError as exc:
            raise TransportError(code="ai_bad_output", message=str(exc)) from exc

    async def interrupt(self, session_id: str) -> None:
        path = self._session_path(session_id, "/interrupt")
        await self._request("POST", path, None, expect_json=False, query="resume=false")

    async def delete(self, session_id: str) -> None:
        path = self._session_path(session_id, "")
        await self._request("DELETE", path, None, expect_json=False)

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        *,
        expect_json: bool,
        query: str = "",
    ) -> Any:
        if self._closed:
            raise TransportError(code="ai_closed", message="opencode client is closed")
        url = path + (f"?{query}" if query else "")
        try:
            async with self._http.stream(method, url, json=payload) as response:
                if 300 <= response.status_code < 400:
                    raise TransportError(code="ai_redirect", message="opencode refused redirect")
                if response.status_code == 401:
                    raise TransportError(code="ai_auth", message="opencode rejected credentials")
                if response.status_code < 200 or response.status_code >= 300:
                    raise TransportError(
                        code="ai_status",
                        message=f"opencode returned status {response.status_code}",
                    )
                raw = await self._read_limited(response)
        except TransportError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TransportError(code="ai_transport", message="opencode transport failed") from exc
        except (httpx.HTTPError, OSError) as exc:
            raise TransportError(code="ai_transport", message="opencode request failed") from exc
        if not expect_json:
            return None
        content_type = ""
        for key, value in raw[1]:
            if key.lower() == "content-type":
                content_type = value
                break
        if "application/json" not in content_type:
            raise TransportError(code="ai_bad_output", message="opencode response is not JSON")
        try:
            return json.loads(raw[0].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TransportError(
                code="ai_bad_output", message="opencode JSON is malformed"
            ) from exc

    async def _read_limited(self, response: httpx.Response) -> tuple[bytes, list[tuple[str, str]]]:
        length = response.headers.get("content-length", "")
        try:
            if length and int(length) > self._max_bytes:
                raise TransportError(code="ai_too_large", message="opencode response is too large")
        except ValueError:
            pass
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes(65536):
            total += len(chunk)
            if total > self._max_bytes:
                raise TransportError(code="ai_too_large", message="opencode response is too large")
            chunks.append(chunk)
        headers = [(k, v) for k, v in response.headers.items()]
        return (b"".join(chunks), headers)
