from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import AuthError, ContractError, TransportError

SERVICE_NAME = "b7"
WEB_SOURCE = "web:auth"
LOGIN_ACTION = "auth.login"
RESOLVE_ACTION = "auth.resolve"
LOGOUT_ACTION = "auth.logout"
HANDLER_ACTIONS = frozenset({LOGIN_ACTION, RESOLVE_ACTION, LOGOUT_ACTION})
MAX_FIELD_CHARS = 1024


def _bounded_str(value: Any, limit: int = MAX_FIELD_CHARS) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(code="bad_payload", message="payload field invalid")
    if len(value) > limit:
        raise ContractError(code="bad_payload", message="payload field invalid")
    return value


def _closed(payload: dict[str, Any], allowed: frozenset[str]) -> dict[str, Any]:
    if set(payload.keys()) != set(allowed):
        raise ContractError(code="bad_payload", message="payload shape invalid")
    return payload


class B7AuthHandler:
    def __init__(self, service: Any, *, allowed_source: str = WEB_SOURCE) -> None:
        if not allowed_source or not allowed_source.strip():
            raise ValueError("allowed_source must be nonempty")
        self._service = service
        self._allowed = allowed_source

    async def handle(self, request: Envelope) -> Envelope:
        if request.target != SERVICE_NAME:
            raise ContractError(code="target_mismatch", message="request target mismatch")
        if request.source != self._allowed:
            raise AuthError(code="auth_failed", message="source is not permitted")
        if request.action not in HANDLER_ACTIONS:
            raise ContractError(code="bad_action", message="unsupported action")
        if request.data_kind != DataKind.PROPRIETARY:
            raise ContractError(code="misclassified", message="auth needs proprietary kind")
        if request.action == LOGIN_ACTION:
            return await self._login(request)
        if request.action == RESOLVE_ACTION:
            return await self._resolve(request)
        return await self._logout(request)

    async def _login(self, request: Envelope) -> Envelope:
        payload = _closed(dict(request.payload), frozenset({"username", "password"}))
        username = _bounded_str(payload["username"], 128)
        password = _bounded_str(payload["password"], 256)
        try:
            result = await asyncio.to_thread(self._service.login, username, password)
            csrf = await asyncio.to_thread(self._service.csrf_token, result.session_token)
        except AuthError:
            raise
        except ContractError:
            raise
        except Exception as exc:
            raise TransportError(code="store_unavailable", message="auth unavailable") from exc
        identity = result.identity
        return request.reply(
            source=SERVICE_NAME,
            action=LOGIN_ACTION,
            payload={
                "userId": identity.user_id,
                "username": identity.username,
                "role": identity.role,
                "authVersion": identity.auth_version,
                "sessionToken": result.session_token,
                "csrfToken": csrf,
            },
            data_kind=DataKind.PROPRIETARY,
        )

    async def _resolve(self, request: Envelope) -> Envelope:
        payload = _closed(dict(request.payload), frozenset({"sessionToken"}))
        token = _bounded_str(payload["sessionToken"], 256)
        try:
            identity = await asyncio.to_thread(self._service.resolve, token)
            csrf = await asyncio.to_thread(self._service.csrf_token, token)
        except AuthError:
            raise
        except ContractError:
            raise
        except Exception as exc:
            raise TransportError(code="store_unavailable", message="auth unavailable") from exc
        return request.reply(
            source=SERVICE_NAME,
            action=RESOLVE_ACTION,
            payload={
                "userId": identity.user_id,
                "username": identity.username,
                "role": identity.role,
                "authVersion": identity.auth_version,
                "csrfToken": csrf,
            },
            data_kind=DataKind.PROPRIETARY,
        )

    async def _logout(self, request: Envelope) -> Envelope:
        payload = _closed(dict(request.payload), frozenset({"sessionToken"}))
        token = _bounded_str(payload["sessionToken"], 256)
        try:
            await asyncio.to_thread(self._service.logout, token)
        except AuthError:
            raise
        except ContractError:
            raise
        except Exception as exc:
            raise TransportError(code="store_unavailable", message="auth unavailable") from exc
        return request.reply(
            source=SERVICE_NAME,
            action=LOGOUT_ACTION,
            payload={},
            data_kind=DataKind.PROPRIETARY,
        )


def make_handler(service: Any) -> Callable[[Envelope], Awaitable[Envelope]]:
    inner = B7AuthHandler(service)

    async def handler(request: Envelope) -> Envelope:
        return await inner.handle(request)

    return handler
