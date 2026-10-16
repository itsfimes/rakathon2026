from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from rakathon_backend.common.errors import AuthError, ContractError

AUTH_ROLES = frozenset({"admin", "coordinator", "clinician", "viewer"})
SESSION_ABSOLUTE_TTL = 8 * 3600
SESSION_IDLE_TTL = 15 * 60
ACCOUNT_LIMIT = 10
ACCOUNT_WINDOW = 60
GLOBAL_LIMIT = 100
GLOBAL_WINDOW = 60
MAX_SESSIONS_PER_USER = 32
KEY_SCHEMA_VERSION = 1


class AuthFailed(AuthError):
    def __init__(self) -> None:
        super().__init__(code="invalid_credentials", message="invalid credentials")


class StoreUnavailable(ContractError):
    def __init__(self) -> None:
        super().__init__(code="store_unavailable", message="auth store unavailable")


class RateLimited(ContractError):
    def __init__(self) -> None:
        super().__init__(code="rate_limited", message="too many attempts")


@dataclass(frozen=True, slots=True)
class UserRecord:
    user_id: str
    username_index: str
    password_hash: str = field(repr=False)
    enc_nonce: bytes = field(repr=False)
    enc_ct: bytes = field(repr=False)
    key_id: str
    role: str
    active: bool
    auth_version: int
    created_at: int
    updated_at: int


@dataclass(frozen=True, slots=True)
class SessionRecord:
    token_hash: str = field(repr=False)
    user_id: str
    auth_version: int
    role: str
    created_at: int
    last_seen: int
    expires_at: int


@dataclass(frozen=True, slots=True)
class UserIdentity:
    user_id: str
    username: str = field(repr=False)
    role: str
    auth_version: int


@dataclass(frozen=True, slots=True)
class LoginResult:
    session_token: str = field(repr=False)
    identity: UserIdentity


AuditCallback = Callable[[dict[str, Any]], None]
Clock = Callable[[], int]
