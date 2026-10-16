from __future__ import annotations

from rakathon_backend.b2.auth.iris_store import IrisAuthStore
from rakathon_backend.b2.auth.keys import KeySet, generate_key_file, load_key_file
from rakathon_backend.b2.auth.models import (
    AuthFailed,
    LoginResult,
    RateLimited,
    SessionRecord,
    StoreUnavailable,
    UserIdentity,
    UserRecord,
)
from rakathon_backend.b2.auth.normalize import normalize_username, validate_password, validate_role
from rakathon_backend.b2.auth.protocol import PersistentAuthStore
from rakathon_backend.b2.auth.sqlite_store import SQLiteDemoAuthStore

__all__ = [
    "AuthFailed",
    "IrisAuthStore",
    "KeySet",
    "LoginResult",
    "PersistentAuthStore",
    "RateLimited",
    "SQLiteDemoAuthStore",
    "SessionRecord",
    "StoreUnavailable",
    "UserIdentity",
    "UserRecord",
    "generate_key_file",
    "load_key_file",
    "normalize_username",
    "validate_password",
    "validate_role",
]
