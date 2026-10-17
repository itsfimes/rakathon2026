from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from rakathon_backend.b5.completion_retry import MAX_ATTEMPTS, CompletionRetry
from rakathon_backend.common.errors import ContractError, TransportError


def _bad_config() -> ContractError:
    return ContractError(code="ai_bad_config", message="Invalid direct AI configuration")


def _bad_output() -> ContractError:
    return ContractError(code="ai_bad_output", message="Invalid AI provider response")


def _endpoint(config: DirectProviderConfig) -> str:
    base = config.base_url
    if (
        not isinstance(base, str)
        or not 1 <= len(base) <= 2048
        or any(not 33 <= ord(char) <= 126 for char in base)
        or any(char in base for char in ("%", "\\", "?", "#"))
    ):
        raise _bad_config()
    try:
        parts = urlsplit(base)
        host, port = parts.hostname, parts.port
    except ValueError:
        raise _bad_config() from None
    if (
        parts.scheme not in ("https", "http")
        or not host
        or parts.username is not None
        or parts.password is not None
        or parts.netloc.endswith(":")
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise _bad_config()
    authority = f"[{host}]" if ":" in host else host
    if port is not None:
        authority += f":{port}"
    if parts.netloc.lower() != authority:
        raise _bad_config()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not all(
            re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
            for label in host.split(".")
        ):
            raise _bad_config() from None
    loopback = host in ("127.0.0.1", "::1")
    local_test = loopback and port is not None and config.allow_insecure_loopback
    if parts.scheme == "http" and not local_test:
        raise _bad_config()
    if not loopback and not config.allow_remote:
        raise _bad_config()
    if config.auth_scheme == "none":
        if not local_test or config.api_key is not None:
            raise _bad_config()
    elif config.auth_scheme in ("api-key", "bearer", "subscription-key"):
        key = config.api_key
        if (
            not isinstance(key, str)
            or not 1 <= len(key) <= 8192
            or any(not 33 <= ord(char) <= 126 for char in key)
        ):
            raise _bad_config()
    else:
        raise _bad_config()
    path = parts.path
    if (
        "//" in path
        or any(segment in (".", "..") for segment in path.split("/"))
        or re.fullmatch(r"[A-Za-z0-9_./~-]*", path) is None
    ):
        raise _bad_config()
    path = path.rstrip("/")
    suffix = "/chat/completions"
    if suffix in path and (not path.endswith(suffix) or path.count(suffix) != 1):
        raise _bad_config()
    if not path.endswith(suffix):
        path += suffix
    return f"{parts.scheme}://{parts.netloc}{path}"


@dataclass(frozen=True, slots=True)
class DirectProviderConfig:
    base_url: str = field(repr=False)
    model: str
    auth_scheme: Literal["api-key", "bearer", "subscription-key", "none"]
    api_key: str | None = field(default=None, repr=False)
    allow_remote: bool = False
    allow_insecure_loopback: bool = False
    timeout_seconds: float = 60.0
    max_request_bytes: int = 1_048_576
    max_response_bytes: int = 2_097_152
    max_content_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        if (
            type(self.allow_remote) is not bool
            or type(self.allow_insecure_loopback) is not bool
            or not isinstance(self.model, str)
            or not 1 <= len(self.model) <= 256
            or self.model != self.model.strip()
            or any(not 32 <= ord(char) <= 126 for char in self.model)
        ):
            raise _bad_config()
        timeout = self.timeout_seconds
        if (
            type(timeout) not in (int, float)
            or not 0 < timeout <= 120
            or not math.isfinite(timeout)
        ):
            raise _bad_config()
        for value, maximum in (
            (self.max_request_bytes, 4_194_304),
            (self.max_response_bytes, 8_388_608),
            (self.max_content_bytes, 4_194_304),
        ):
            if type(value) is not int or not 1 <= value <= maximum:
                raise _bad_config()
        if self.max_content_bytes > self.max_response_bytes:
            raise _bad_config()
        _endpoint(self)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError("Invalid JSON constant")


class DirectHttpTransport:
    def __init__(
        self,
        config: DirectProviderConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._endpoint = _endpoint(config)
        self._closed = False
        headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        if config.auth_scheme == "api-key":
            assert config.api_key is not None
            headers["api-key"] = config.api_key
        elif config.auth_scheme == "bearer":
            headers["Authorization"] = f"Bearer {config.api_key}"
        elif config.auth_scheme == "subscription-key":
            assert config.api_key is not None
            headers["Ocp-Apim-Subscription-Key"] = config.api_key
        self._client = httpx.AsyncClient(
            transport=transport,
            headers=headers,
            follow_redirects=False,
            trust_env=False,
            verify=True,
            timeout=httpx.Timeout(config.timeout_seconds),
        )

    async def generate(
        self,
        prompt: str,
        *,
        response_schema: dict[str, Any] | None = None,
        schema_name: str = "rakathon_ingestion",
        retry_rate_limit: bool = False,
        system_message: str | None = None,
    ) -> str:
        if self._closed:
            raise TransportError(code="ai_closed", message="Direct AI transport is closed")
        body = self._request_body(prompt, response_schema, schema_name, system_message)
        budget = CompletionRetry(self._config.timeout_seconds) if retry_rate_limit else None
        try:
            async with asyncio.timeout(self._config.timeout_seconds):
                for attempt in range(MAX_ATTEMPTS if budget else 1):
                    if budget:
                        budget.check()
                    async with self._client.stream(
                        "POST",
                        self._endpoint,
                        content=body,
                        headers={"Content-Type": "application/json"},
                    ) as response:
                        if response.status_code == 429 and budget:
                            retry_after = response.headers.get_list("Retry-After")
                        else:
                            if response.status_code != 200:
                                raise TransportError(
                                    code="ai_http_error", message="AI provider rejected the request"
                                )
                            if (
                                response.headers.get("content-encoding", "identity").lower()
                                != "identity"
                            ):
                                raise _bad_output()
                            data = bytearray()
                            async for chunk in response.aiter_bytes(chunk_size=16_384):
                                if len(data) + len(chunk) > self._config.max_response_bytes:
                                    raise _bad_output()
                                data.extend(chunk)
                            if budget:
                                budget.check()
                            return self._response_content(data)
                    if budget:
                        await budget.wait(retry_after, attempt)
        except (TimeoutError, httpx.TimeoutException):
            raise TransportError(
                code="ai_timeout", message="AI provider request timed out"
            ) from None
        except httpx.HTTPError:
            raise TransportError(
                code="ai_transport_error", message="AI provider request failed"
            ) from None
        raise AssertionError("AI attempt budget exhausted without a result")

    def _request_body(
        self, prompt: str, response_schema: dict[str, Any] | None, schema_name: str,
        system_message: str | None = None,
    ) -> bytes:
        invalid = ContractError(code="ai_bad_input", message="Invalid AI request")
        if (
            not isinstance(prompt, str)
            or not prompt.strip()
            or len(prompt) > self._config.max_request_bytes
            or (response_schema is not None and not isinstance(response_schema, dict))
        ):
            raise invalid
        try:
            if len(prompt.encode("utf-8")) > self._config.max_request_bytes:
                raise invalid
            payload: dict[str, Any] = {
                "model": self._config.model,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system_message is not None:
                if not isinstance(system_message, str) or not system_message.strip():
                    raise invalid
                payload["messages"].insert(0, {"role": "system", "content": system_message})
            if response_schema is not None:
                if (
                    not isinstance(schema_name, str)
                    or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", schema_name) is None
                ):
                    raise invalid
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "schema": response_schema, "strict": True},
                }
            body = bytearray()
            encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            for part in encoder.iterencode(payload):
                encoded = part.encode("utf-8")
                if len(body) + len(encoded) > self._config.max_request_bytes:
                    raise invalid
                body.extend(encoded)
            return bytes(body)
        except (TypeError, ValueError, RecursionError):
            raise invalid from None

    def _response_content(self, data: bytearray) -> str:
        try:
            result = json.loads(
                data.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
            )
            if not isinstance(result, dict):
                raise _bad_output()
            choices = result.get("choices")
            if not isinstance(choices, list) or len(choices) != 1:
                raise _bad_output()
            choice = choices[0]
            if not isinstance(choice, dict) or choice.get("finish_reason") != "stop":
                raise _bad_output()
            message = choice.get("message")
            if not isinstance(message, dict) or any(
                message.get(key) is not None for key in ("refusal", "tool_calls", "function_call")
            ):
                raise _bad_output()
            content = message.get("content")
            if (
                not isinstance(content, str)
                or not content.strip()
                or len(content.encode("utf-8")) > self._config.max_content_bytes
            ):
                raise _bad_output()
            return content
        except (ValueError, RecursionError):
            raise _bad_output() from None

    async def aclose(self) -> None:
        self._closed = True
        await self._client.aclose()
