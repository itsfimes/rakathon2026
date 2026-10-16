from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Protocol

from rakathon_backend.b2.auth.models import (
    AUTH_ROLES,
    AuthFailed,
    LoginResult,
    RateLimited,
    StoreUnavailable,
    UserIdentity,
)
from rakathon_backend.b7.handler import LOGIN_ACTION, LOGOUT_ACTION, RESOLVE_ACTION
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import AuthError, ContractError, TransportError
from rakathon_backend.common.ipc import UnixJsonClient
from rakathon_backend.common.rpc import new_envelope, socket_for

SERVICE_NAME = "b7"
WEB_SOURCE = "web:auth"
RPC_TIMEOUT = 5.0
MAX_TIMEOUT = 30.0


class AuthenticationPort(Protocol):
    def login(self, username: str, password: str) -> LoginResult: ...
    def resolve(self, session_token: str) -> UserIdentity: ...
    def csrf_token(self, session_token: str) -> str: ...
    def logout(self, session_token: str) -> None: ...


AuthSessionPort = AuthenticationPort


def _socket_for_runtime(runtime_dir: Path | str) -> Path:
    text = str(runtime_dir)
    lowered = text.lower()
    if not text or "://" in text or lowered.startswith("http"):
        raise ValueError("runtime_dir must be a local directory")
    return socket_for(Path(text), SERVICE_NAME)


def _mapped_error(exc: BaseException) -> AuthError | ContractError:
    code = getattr(exc, "code", "")
    if code == "invalid_credentials":
        return AuthFailed()
    if code == "rate_limited":
        return RateLimited()
    return StoreUnavailable()


def _checked_text(value: Any, limit: int) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise StoreUnavailable()
    return value


def _checked_version(value: Any) -> int:
    if type(value) is not int or value <= 0:
        raise StoreUnavailable()
    return value


def _checked_role(value: Any) -> str:
    if not isinstance(value, str) or value not in AUTH_ROLES:
        raise StoreUnavailable()
    return value


def _identity_fields(payload: dict[str, Any]) -> UserIdentity:
    return UserIdentity(
        user_id=_checked_text(payload["userId"], 128),
        username=_checked_text(payload["username"], 128),
        role=_checked_role(payload["role"]),
        auth_version=_checked_version(payload["authVersion"]),
    )


class B7SocketClient:
    def __init__(
        self, runtime_dir: Path | str, token: str, *, timeout: float = RPC_TIMEOUT
    ) -> None:
        if not isinstance(token, str) or not token:
            raise ValueError("token must be nonempty")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 0 < timeout <= MAX_TIMEOUT
        ):
            raise ValueError("timeout must be a positive finite bound")
        self._socket = _socket_for_runtime(runtime_dir)
        self._token = token
        self._timeout = float(timeout)

    @property
    def socket_path(self) -> Path:
        return self._socket

    @property
    def timeout(self) -> float:
        return self._timeout

    def login(self, username: str, password: str) -> LoginResult:
        payload = self._verified(
            self._request(LOGIN_ACTION, {"username": username, "password": password}),
            LOGIN_ACTION,
            frozenset({"userId", "username", "role", "authVersion", "sessionToken", "csrfToken"}),
        )
        token = _checked_text(payload["sessionToken"], 256)
        _checked_text(payload["csrfToken"], 256)
        return LoginResult(session_token=token, identity=_identity_fields(payload))

    def resolve(self, session_token: str) -> UserIdentity:
        payload = self._verified(
            self._request(RESOLVE_ACTION, {"sessionToken": session_token}),
            RESOLVE_ACTION,
            frozenset({"userId", "username", "role", "authVersion", "csrfToken"}),
        )
        _checked_text(payload["csrfToken"], 256)
        return _identity_fields(payload)

    def csrf_token(self, session_token: str) -> str:
        payload = self._verified(
            self._request(RESOLVE_ACTION, {"sessionToken": session_token}),
            RESOLVE_ACTION,
            frozenset({"userId", "username", "role", "authVersion", "csrfToken"}),
        )
        _identity_fields(payload)
        return _checked_text(payload["csrfToken"], 256)

    def logout(self, session_token: str) -> None:
        payload = self._verified(
            self._request(LOGOUT_ACTION, {"sessionToken": session_token}),
            LOGOUT_ACTION,
            frozenset(),
        )
        if payload != {}:
            raise StoreUnavailable()

    def _request(self, action: str, payload: dict[str, Any]) -> Envelope:
        envelope = new_envelope(
            source=WEB_SOURCE,
            target=SERVICE_NAME,
            action=action,
            data_kind=DataKind.PROPRIETARY,
            payload=payload,
        )
        client = UnixJsonClient(
            self._socket, token=self._token, source=WEB_SOURCE, timeout=self._timeout
        )
        try:
            return asyncio.run(client.call(envelope, expect_source=SERVICE_NAME))
        except (
            AuthError,
            ContractError,
            TransportError,
            OSError,
            TimeoutError,
            ValueError,
            KeyError,
            RuntimeError,
        ) as exc:
            raise _mapped_error(exc) from None

    def _verified(self, reply: Envelope, action: str, allowed: frozenset[str]) -> dict[str, Any]:
        if reply.source != SERVICE_NAME or reply.action != action:
            raise StoreUnavailable()
        if reply.data_kind != DataKind.PROPRIETARY:
            raise StoreUnavailable()
        payload = dict(reply.payload)
        if set(payload) != set(allowed):
            raise StoreUnavailable()
        return payload

    def __repr__(self) -> str:
        return "B7SocketClient()"
