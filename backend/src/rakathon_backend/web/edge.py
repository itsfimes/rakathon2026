from __future__ import annotations

import asyncio
import hmac
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rakathon_backend.b4.router import USER_ACTIONS, web_envelope
from rakathon_backend.b7.client import AuthSessionPort
from rakathon_backend.common.contracts import Envelope
from rakathon_backend.common.errors import ContractError
from rakathon_backend.common.ipc import UnixJsonClient
from rakathon_backend.common.kinds import request_kind
from rakathon_backend.common.rpc import socket_for
from rakathon_backend.web.router import (
    AuthHTTPRouter,
    ProtectedHandler,
    VerifiedIdentity,
)

B4_SERVICE = "b4"
WEB_SOURCE = "web:auth"
B4_TIMEOUT = 5.0
MAX_TIMEOUT = 30.0

LoginCallable = Callable[[str, str], tuple[str, VerifiedIdentity, str]]
ResolveCallable = Callable[[str], VerifiedIdentity]
CsrfCallable = Callable[[str], str]
LogoutCallable = Callable[[str], None]


class B4ActionClient:
    def __init__(self, runtime_dir: Path | str, token: str, *, timeout: float = B4_TIMEOUT) -> None:
        text = str(runtime_dir)
        lowered = text.lower()
        if not text or "://" in text or lowered.startswith("http"):
            raise ValueError("runtime_dir must be a local directory")
        if not isinstance(token, str) or not token:
            raise ValueError("token must be nonempty")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 0 < timeout <= MAX_TIMEOUT
        ):
            raise ValueError("timeout must be a positive finite bound")
        self._socket = socket_for(Path(text), B4_SERVICE)
        self._token = token
        self._timeout = float(timeout)

    @property
    def socket_path(self) -> Path:
        return self._socket

    @property
    def timeout(self) -> float:
        return self._timeout

    def call(self, identity: VerifiedIdentity, action: str, payload: dict[str, Any]) -> Envelope:
        if action not in USER_ACTIONS:
            raise ContractError(code="bad_action", message="unsupported action")
        request = web_envelope(identity.user_id, action, dict(payload), request_kind(action))
        client = UnixJsonClient(
            self._socket, token=self._token, source=WEB_SOURCE, timeout=self._timeout
        )
        return asyncio.run(client.call(request, expect_source=B4_SERVICE))

    def __repr__(self) -> str:
        return "B4ActionClient()"


def make_b4_action_client(
    runtime_dir: Path | str, token: str, *, timeout: float = B4_TIMEOUT
) -> B4ActionClient:
    return B4ActionClient(runtime_dir, token, timeout=timeout)


class AuthMiddleware:
    def __init__(self, router: AuthHTTPRouter) -> None:
        self._router = router

    def protect(
        self, next_handler: ProtectedHandler
    ) -> Callable[[VerifiedIdentity, str, str, dict[str, Any]], tuple[int, dict[str, Any]]]:
        def wrapped(
            identity: VerifiedIdentity, method: str, path: str, body: dict[str, Any]
        ) -> tuple[int, dict[str, Any]]:
            return next_handler(identity, method, path, body)

        self._router.set_protected(wrapped)
        return wrapped

    def dispatch(
        self, identity: VerifiedIdentity, method: str, path: str, body: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        return self._router.run_protected(identity, method, path, body)


def build_login_callables(
    port: AuthSessionPort,
) -> tuple[LoginCallable, ResolveCallable, CsrfCallable, LogoutCallable]:
    def login(username: str, password: str) -> tuple[str, VerifiedIdentity, str]:
        result = port.login(username, password)
        csrf = port.csrf_token(result.session_token)
        ident = result.identity
        return (
            result.session_token,
            VerifiedIdentity(
                user_id=ident.user_id,
                username=ident.username,
                role=ident.role,
                auth_version=ident.auth_version,
            ),
            csrf,
        )

    def resolve(token: str) -> VerifiedIdentity:
        ident = port.resolve(token)
        return VerifiedIdentity(
            user_id=ident.user_id,
            username=ident.username,
            role=ident.role,
            auth_version=ident.auth_version,
        )

    def csrf_for(token: str) -> str:
        return str(port.csrf_token(token))

    def logout(token: str) -> None:
        port.logout(token)

    return (login, resolve, csrf_for, logout)


def hmac_equal(a: str, b: str) -> bool:
    try:
        return hmac.compare_digest(a, b)
    except (TypeError, ValueError):
        return False
