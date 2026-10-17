from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from rakathon_backend.b2.auth.models import AuthFailed, RateLimited, StoreUnavailable
from rakathon_backend.common.errors import AuthError, ContractError, TransportError
from rakathon_backend.web.config import (
    CSRF_HEADER,
    LOGIN_HEADER,
    LOGIN_HEADER_VALUE,
    ORIGIN_HEADER,
    PROXY_HEADER,
    WebConfig,
    check_csrf,
    check_host_allowlist,
    check_host_authority,
    check_origin_exact,
    check_proxy_key,
    clear_cookie_header,
    extract_session_cookie,
    set_cookie_header,
)
from rakathon_backend.web.demo_login import (
    DemoLoginConfig,
    anon_session_body,
    auth_success_body,
    demo_account_from,
    demo_fail_closed,
    demo_matches,
    revoke_quietly,
    revoked_stale_session_401,
    stale_session_401,
)
from rakathon_backend.web.demo_login import auth_default_deny as _default_deny
from rakathon_backend.web.demo_login import auth_safe_error as _safe_error


@dataclass(frozen=True)
class VerifiedIdentity:
    user_id: str
    username: str
    role: str
    auth_version: int


ProtectedHandler = Callable[
    [VerifiedIdentity, str, str, dict[str, Any]], tuple[int, dict[str, Any]]
]
B4Dispatch = Callable[[VerifiedIdentity, str, str, dict[str, Any]], tuple[int, dict[str, Any]]]

LOGIN_PATH = "/api/v1/auth/login"
DEMO_LOGIN_PATH = "/api/v1/auth/demo-login"
SESSION_PATH = "/api/v1/auth/session"
LOGOUT_PATH = "/api/v1/auth/logout"
HEALTH_PATH = "/health"
AUTH_PREFIX = "/api/v1/auth/"
RETRY_AFTER = "5"


class AuthHTTPRouter:
    def __init__(
        self,
        config: WebConfig,
        proxy_key: str,
        login: Callable[[str, str], tuple[str, VerifiedIdentity, str]],
        resolve: Callable[[str], VerifiedIdentity],
        csrf_for: Callable[[str], str],
        logout: Callable[[str], None],
        protected: ProtectedHandler | None = None,
        allowed_hosts: frozenset[str] | None = None,
        demo: DemoLoginConfig | None = None,
    ) -> None:
        self._config = config
        self._proxy = proxy_key
        self._login = login
        self._resolve = resolve
        self._csrf_for = csrf_for
        self._logout = logout
        self._demo = demo
        self._protected = protected if protected is not None else _default_deny
        self._allowed_hosts = allowed_hosts

    def set_allowed_hosts(self, hosts: frozenset[str]) -> None:
        current = self._allowed_hosts if self._allowed_hosts is not None else frozenset()
        self._allowed_hosts = current | hosts

    def set_protected(self, handler: ProtectedHandler) -> None:
        self._protected = handler

    def run_protected(
        self, identity: VerifiedIdentity, method: str, path: str, body: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        return self._protected(identity, method, path, body)

    def handle(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        body: bytes | None,
    ) -> tuple[int, dict[str, str], dict[str, Any]]:
        lowered = {str(k).lower(): str(v) for k, v in headers.items()}
        if not check_proxy_key(lowered.get(PROXY_HEADER), self._proxy):
            return (401, {}, _safe_error("auth_failed"))
        host = lowered.get("host", "")
        if self._allowed_hosts is not None:
            if host and not check_host_allowlist(host, self._allowed_hosts):
                return (403, {}, _safe_error("auth_failed"))
        elif host and not check_host_authority(host, self._config.origin):
            return (403, {}, _safe_error("auth_failed"))
        for key in ("x-forwarded-for", "x-forwarded-host", "forwarded"):
            if key in lowered:
                return (403, {}, _safe_error("auth_failed"))
        if path == HEALTH_PATH and method == "GET":
            return (200, {}, {"status": "ok", "scope": "liveness"})
        if path.startswith(AUTH_PREFIX):
            return self._handle_auth(method, path, lowered, body)
        return self._handle_clinical(method, path, lowered, body)

    def _handle_auth(
        self, method: str, path: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, dict[str, str], dict[str, Any]]:
        if path == LOGIN_PATH and method == "POST":
            return self._do_login(headers, body)
        if path == DEMO_LOGIN_PATH and method == "POST":
            return self._do_demo_login(headers, body)
        if path == SESSION_PATH and method == "GET":
            return self._do_session(headers)
        if path == LOGOUT_PATH and method == "POST":
            return self._do_logout(headers)
        return (404, {}, _safe_error("not_found"))

    def _require_origin(self, headers: dict[str, str]) -> bool:
        return check_origin_exact(headers.get(ORIGIN_HEADER), self._config.origin)

    def _parse_json_body(
        self, headers: dict[str, str], body: bytes | None
    ) -> dict[str, Any] | None:
        ctype = headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return None
        if body is None or not body:
            return None
        try:
            raw = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        return raw

    def _do_login(
        self, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, dict[str, str], dict[str, Any]]:
        if headers.get(LOGIN_HEADER) != LOGIN_HEADER_VALUE:
            return (401, {}, _safe_error("auth_failed"))
        if not self._require_origin(headers):
            return (403, {}, _safe_error("auth_failed"))
        payload = self._parse_json_body(headers, body)
        if payload is None:
            return (400, {}, _safe_error("bad_request"))
        if set(payload.keys()) != {"username", "password"}:
            return (400, {}, _safe_error("bad_request"))
        username = payload.get("username")
        password = payload.get("password")
        if (
            not isinstance(username, str)
            or not isinstance(password, str)
            or not username
            or not password
            or len(username) > 128
            or len(password) > 256
        ):
            return (400, {}, _safe_error("bad_request"))
        try:
            token, identity, csrf = self._login(username, password)
        except RateLimited:
            return (429, {"Retry-After": RETRY_AFTER}, _safe_error("rate_limited"))
        except AuthFailed:
            return (401, {}, _safe_error("invalid_credentials"))
        except (StoreUnavailable, ContractError, TransportError, AuthError):
            return (503, {}, _safe_error("not_configured"))
        except (OSError, ValueError, KeyError, RuntimeError, TimeoutError):
            return (503, {}, _safe_error("not_configured"))
        if demo_fail_closed(self._demo, identity.username, identity.role):
            revoke_quietly(self._logout, token)
            return (401, {}, _safe_error("invalid_credentials"))
        cookie = set_cookie_header(self._config.cookie_name, token, self._config.secure_cookie)
        out = auth_success_body(
            identity.user_id, identity.username, identity.role, csrf, self._demo
        )
        return (200, {"Set-Cookie": cookie}, out)

    def _do_demo_login(
        self, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, dict[str, str], dict[str, Any]]:
        if self._demo is None:
            return (404, {}, _safe_error("not_found"))
        if headers.get(LOGIN_HEADER) != LOGIN_HEADER_VALUE:
            return (401, {}, _safe_error("auth_failed"))
        if not self._require_origin(headers):
            return (403, {}, _safe_error("auth_failed"))
        payload = self._parse_json_body(headers, body)
        if payload is None:
            return (400, {}, _safe_error("bad_request"))
        account = demo_account_from(payload)
        if account is None:
            return (400, {}, _safe_error("bad_request"))
        creds = self._demo.credentials_for(account)
        if creds is None:
            return (400, {}, _safe_error("bad_request"))
        try:
            token, identity, csrf = self._login(creds[0], creds[1])
        except RateLimited:
            return (429, {"Retry-After": RETRY_AFTER}, _safe_error("rate_limited"))
        except AuthFailed:
            return (401, {}, _safe_error("invalid_credentials"))
        except (StoreUnavailable, ContractError, TransportError, AuthError):
            return (503, {}, _safe_error("not_configured"))
        except (OSError, ValueError, KeyError, RuntimeError, TimeoutError):
            return (503, {}, _safe_error("not_configured"))
        if not demo_matches(self._demo, account, identity.username, identity.role):
            revoke_quietly(self._logout, token)
            return (401, {}, _safe_error("invalid_credentials"))
        cookie = set_cookie_header(self._config.cookie_name, token, self._config.secure_cookie)
        out = auth_success_body(
            identity.user_id, identity.username, identity.role, csrf, self._demo
        )
        return (200, {"Set-Cookie": cookie}, out)

    def _cookie_token(self, headers: dict[str, str]) -> str | None | bool:
        raw = headers.get("cookie")
        try:
            return extract_session_cookie(raw, self._config.cookie_name)
        except ContractError:
            return False

    def _do_session(self, headers: dict[str, str]) -> tuple[int, dict[str, str], dict[str, Any]]:
        token = self._cookie_token(headers)
        name, secure = self._config.cookie_name, self._config.secure_cookie
        if token is None:
            return (200, {}, anon_session_body(self._demo))
        if token is False:
            return stale_session_401(self._demo, name, secure)
        assert isinstance(token, str)
        try:
            identity = self._resolve(token)
            csrf = self._csrf_for(token)
        except RateLimited:
            return (429, {"Retry-After": RETRY_AFTER}, _safe_error("rate_limited"))
        except AuthFailed:
            return stale_session_401(self._demo, name, secure)
        except (StoreUnavailable, ContractError, TransportError, AuthError):
            return (503, {}, _safe_error("not_configured"))
        except (OSError, ValueError, KeyError, RuntimeError, TimeoutError):
            return (503, {}, _safe_error("not_configured"))
        if demo_fail_closed(self._demo, identity.username, identity.role):
            return revoked_stale_session_401(self._logout, token, self._demo, name, secure)
        ok = auth_success_body(identity.user_id, identity.username, identity.role, csrf, self._demo)
        return (200, {}, ok)

    def _do_logout(self, headers: dict[str, str]) -> tuple[int, dict[str, str], dict[str, Any]]:
        cleared = {
            "Set-Cookie": clear_cookie_header(self._config.cookie_name, self._config.secure_cookie)
        }
        token = self._cookie_token(headers)
        if token is None:
            return (204, cleared, {})
        if token is False:
            return (401, {}, _safe_error("invalid_credentials"))
        assert isinstance(token, str)
        try:
            identity = self._resolve(token)
        except AuthFailed:
            return (204, cleared, {})
        except (StoreUnavailable, ContractError, TransportError, AuthError):
            return (503, {}, _safe_error("not_configured"))
        except (OSError, ValueError, KeyError, RuntimeError, TimeoutError):
            return (503, {}, _safe_error("not_configured"))
        _ = identity
        try:
            expected = self._csrf_for(token)
        except (ContractError, AuthError, TransportError, OSError, ValueError, KeyError):
            return (503, {}, _safe_error("not_configured"))
        if not self._require_origin(headers):
            return (403, {}, _safe_error("auth_failed"))
        if not check_csrf(headers.get(CSRF_HEADER), expected):
            return (403, {}, _safe_error("auth_failed"))
        try:
            self._logout(token)
        except AuthFailed:
            return (204, cleared, {})
        except (StoreUnavailable, ContractError, TransportError, AuthError):
            return (503, {}, _safe_error("not_configured"))
        except (OSError, ValueError, KeyError, RuntimeError, TimeoutError):
            return (503, {}, _safe_error("not_configured"))
        return (204, cleared, {})

    def _handle_clinical(
        self, method: str, path: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, dict[str, str], dict[str, Any]]:
        token = self._cookie_token(headers)
        if token is None or token is False:
            return (401, {}, _safe_error("auth_failed"))
        assert isinstance(token, str)
        try:
            identity = self._resolve(token)
        except RateLimited:
            return (429, {"Retry-After": RETRY_AFTER}, _safe_error("rate_limited"))
        except AuthFailed:
            return (401, {}, _safe_error("auth_failed"))
        except (StoreUnavailable, ContractError, TransportError, AuthError):
            return (503, {}, _safe_error("not_configured"))
        except (OSError, ValueError, KeyError, RuntimeError, TimeoutError):
            return (503, {}, _safe_error("not_configured"))
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            try:
                expected = self._csrf_for(token)
            except (ContractError, AuthError, TransportError, OSError, ValueError, KeyError):
                return (503, {}, _safe_error("not_configured"))
            if not self._require_origin(headers):
                return (403, {}, _safe_error("auth_failed"))
            if not check_csrf(headers.get(CSRF_HEADER), expected):
                return (403, {}, _safe_error("auth_failed"))
            parsed = self._parse_json_body(headers, body) if body else {}
            if body and parsed is None:
                return (400, {}, _safe_error("bad_request"))
            is_assistant_post = method == "POST" and path == "/api/v1/assistant"
            if is_assistant_post:
                if isinstance(parsed, dict) and any(
                    k in parsed for k in ("userId", "user_id", "username")
                ):
                    return (400, {}, _safe_error("bad_request"))
            elif isinstance(parsed, dict) and any(
                k in parsed for k in ("userId", "user_id", "role", "username")
            ):
                return (400, {}, _safe_error("bad_request"))
            clean: dict[str, Any] = dict(parsed) if isinstance(parsed, dict) else {}
        else:
            clean = {}
        try:
            status, payload = self._protected(identity, method, path, clean)
        except (ContractError, AuthError, TransportError, OSError, ValueError, KeyError):
            return (503, {}, _safe_error("not_configured"))
        if not isinstance(status, int) or not isinstance(payload, dict):
            return (503, {}, _safe_error("not_configured"))
        return (status, {}, dict(payload))
