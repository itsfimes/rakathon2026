from __future__ import annotations

import json
import time
from typing import Any, cast

import httpx

from rakathon_backend.b2.auth.https_config import AuthHTTPSConfig
from rakathon_backend.b2.auth.https_contract import (
    MAX_BODY,
    decode,
    request_args,
    result_value,
    session_wire,
    shape,
    user_wire,
)
from rakathon_backend.b2.auth.models import RateLimited, SessionRecord, StoreUnavailable, UserRecord
from rakathon_backend.common.errors import ContractError


class IrisHTTPSAuthStore:
    """Typed synchronous port for B7's worker threads; never retries a mutation."""

    def __init__(
        self, config: AuthHTTPSConfig, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._config = config
        self._transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(
            auth=httpx.BasicAuth(self._config.username, self._config.password),
            verify=True,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(12, connect=5),
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
            transport=self._transport,
        )

    def init_schema(self) -> None:
        raise ContractError(
            code="administrative_install_required", message="auth schema requires administrator"
        )

    def _call(self, op: str, **args: Any) -> Any:
        request_args(op, args)
        body = json.dumps({"v": 1, "op": op, "args": args}, allow_nan=False).encode("ascii")
        if len(body) > MAX_BODY:
            raise StoreUnavailable()
        deadline = time.monotonic() + 12
        try:
            with (
                self._client() as client,
                client.stream(
                    "POST",
                    self._config.url,
                    content=body,
                    headers={"Content-Type": "application/json", "Accept-Encoding": "identity"},
                ) as response,
            ):
                if response.status_code != 200:
                    raise StoreUnavailable()
                if response.headers.get("content-type", "").split(";", 1)[0] != "application/json":
                    raise StoreUnavailable()
                if response.headers.get("content-encoding", "identity") != "identity":
                    raise StoreUnavailable()
                raw = bytearray()
                for chunk in response.iter_bytes(chunk_size=1024):
                    raw.extend(chunk)
                    if len(raw) > MAX_BODY or time.monotonic() > deadline:
                        raise StoreUnavailable()
                if time.monotonic() > deadline:
                    raise StoreUnavailable()
                payload = decode(bytes(raw))
        except (httpx.HTTPError, ValueError, UnicodeError):
            raise StoreUnavailable() from None
        if not isinstance(payload, dict) or type(payload.get("ok")) is not bool:
            raise StoreUnavailable()
        if type(payload.get("v")) is not int or payload["v"] != 1:
            raise StoreUnavailable()
        if payload["ok"]:
            shape(payload, frozenset({"v", "ok", "result"}))
            return result_value(op, payload["result"])
        shape(payload, frozenset({"v", "ok", "error"}))
        if payload["error"] == "rate_limited" and op == "rate_reserve":
            raise RateLimited()
        if payload["error"] == "duplicate_id" and op == "create_user":
            raise ContractError(code="duplicate_id", message="user exists")
        raise StoreUnavailable()

    def create_user(self, record: UserRecord) -> None:
        self._call("create_user", record=user_wire(record))

    def get_user_by_index(self, username_index: str) -> UserRecord | None:
        return cast(
            UserRecord | None, self._call("get_user_by_index", username_index=username_index)
        )

    def get_user_by_id(self, user_id: str) -> UserRecord | None:
        return cast(UserRecord | None, self._call("get_user_by_id", user_id=user_id))

    def update_user(self, record: UserRecord) -> None:
        self._call("update_user", record=user_wire(record))

    def create_session(self, record: SessionRecord) -> None:
        self._call("create_session", record=session_wire(record))

    def get_session(self, token_hash: str) -> SessionRecord | None:
        return cast(SessionRecord | None, self._call("get_session", token_hash=token_hash))

    def cas_last_seen(self, token_hash: str, old: int, new: int) -> bool:
        return cast(bool, self._call("cas_last_seen", token_hash=token_hash, old=old, new=new))

    def delete_session(self, token_hash: str) -> None:
        self._call("delete_session", token_hash=token_hash)

    def count_user_sessions(self, user_id: str) -> int:
        return cast(int, self._call("count_user_sessions", user_id=user_id))

    def prune_user_sessions(self, user_id: str, keep: int) -> None:
        self._call("prune_user_sessions", user_id=user_id, keep=keep)

    def revoke_user_sessions(self, user_id: str) -> None:
        self._call("revoke_user_sessions", user_id=user_id)

    def prune_expired_sessions(self, now: int, limit: int) -> None:
        self._call("prune_expired_sessions", now=now, limit=limit)

    def rate_reserve(
        self,
        account_key: str,
        now: int,
        account_limit: int,
        account_window: int,
        global_limit: int,
        global_window: int,
    ) -> None:
        self._call(
            "rate_reserve",
            account_key=account_key,
            now=now,
            account_limit=account_limit,
            account_window=account_window,
            global_limit=global_limit,
            global_window=global_window,
        )
