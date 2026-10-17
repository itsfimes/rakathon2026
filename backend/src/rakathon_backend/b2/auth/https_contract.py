from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any

from rakathon_backend.b2.auth.models import AUTH_ROLES, SessionRecord, StoreUnavailable, UserRecord

MAX_BODY = 16384
MAX_TIME = 253402300799
MAX_VERSION = 2147483647
USER_FIELDS = frozenset(UserRecord.__dataclass_fields__)
SESSION_FIELDS = frozenset(SessionRecord.__dataclass_fields__)
OP_FIELDS: dict[str, frozenset[str]] = {
    "create_user": frozenset({"record"}),
    "get_user_by_index": frozenset({"username_index"}),
    "get_user_by_id": frozenset({"user_id"}),
    "update_user": frozenset({"record"}),
    "create_session": frozenset({"record"}),
    "get_session": frozenset({"token_hash"}),
    "cas_last_seen": frozenset({"token_hash", "old", "new"}),
    "delete_session": frozenset({"token_hash"}),
    "count_user_sessions": frozenset({"user_id"}),
    "prune_user_sessions": frozenset({"user_id", "keep"}),
    "revoke_user_sessions": frozenset({"user_id"}),
    "prune_expired_sessions": frozenset({"now", "limit"}),
    "rate_reserve": frozenset(
        {"account_key", "now", "account_limit", "account_window", "global_limit", "global_window"}
    ),
}


def integer(value: Any, low: int = 0, high: int = MAX_TIME) -> int:
    if type(value) is not int or not low <= value <= high:
        raise StoreUnavailable()
    return value


def text(value: Any, maximum: int, pattern: str | None = None) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise StoreUnavailable()
    if any(ord(c) < 32 or ord(c) > 126 for c in value):
        raise StoreUnavailable()
    if pattern is not None and re.fullmatch(pattern, value) is None:
        raise StoreUnavailable()
    return value


def shape(value: Any, fields: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or value.keys() != fields:
        raise StoreUnavailable()
    return value


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StoreUnavailable()
        result[key] = value
    return result


def decode(raw: bytes) -> Any:
    if len(raw) > MAX_BODY:
        raise StoreUnavailable()
    try:
        return json.loads(raw, object_pairs_hook=_pairs)
    except (ValueError, UnicodeError, RecursionError):
        raise StoreUnavailable() from None


def _encoded(value: Any, minimum: int, maximum: int) -> bytes:
    encoded = text(value, maximum)
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise StoreUnavailable() from None
    if not minimum <= len(raw) or base64.b64encode(raw).decode("ascii") != encoded:
        raise StoreUnavailable()
    return raw


def user_wire(record: UserRecord) -> dict[str, Any]:
    data = {name: getattr(record, name) for name in USER_FIELDS}
    data["enc_nonce"] = base64.b64encode(record.enc_nonce).decode("ascii")
    data["enc_ct"] = base64.b64encode(record.enc_ct).decode("ascii")
    user_record(data)
    return data


def user_record(value: Any) -> UserRecord:
    data = shape(value, USER_FIELDS)
    if (
        type(data["active"]) is not bool
        or not isinstance(data["role"], str)
        or data["role"] not in AUTH_ROLES
    ):
        raise StoreUnavailable()
    record = UserRecord(
        user_id=text(data["user_id"], 32, r"[a-f0-9]{32}"),
        username_index=text(data["username_index"], 64, r"[a-f0-9]{64}"),
        password_hash=text(data["password_hash"], 512, r"\$argon2id\$[A-Za-z0-9$=,+/.-]+"),
        enc_nonce=_encoded(data["enc_nonce"], 12, 16),
        enc_ct=_encoded(data["enc_ct"], 17, 1024),
        key_id=text(data["key_id"], 64, r"[A-Za-z0-9_-]+"),
        role=data["role"],
        active=data["active"],
        auth_version=integer(data["auth_version"], 1, MAX_VERSION),
        created_at=integer(data["created_at"]),
        updated_at=integer(data["updated_at"]),
    )
    if len(record.enc_nonce) != 12 or record.updated_at < record.created_at:
        raise StoreUnavailable()
    return record


def session_wire(record: SessionRecord) -> dict[str, Any]:
    data = {name: getattr(record, name) for name in SESSION_FIELDS}
    session_record(data)
    return data


def session_record(value: Any) -> SessionRecord:
    data = shape(value, SESSION_FIELDS)
    if not isinstance(data["role"], str) or data["role"] not in AUTH_ROLES:
        raise StoreUnavailable()
    record = SessionRecord(
        token_hash=text(data["token_hash"], 64, r"[a-f0-9]{64}"),
        user_id=text(data["user_id"], 32, r"[a-f0-9]{32}"),
        auth_version=integer(data["auth_version"], 1, MAX_VERSION),
        role=data["role"],
        created_at=integer(data["created_at"]),
        last_seen=integer(data["last_seen"]),
        expires_at=integer(data["expires_at"]),
    )
    if not record.created_at <= record.last_seen < record.expires_at:
        raise StoreUnavailable()
    return record


def request_args(op: str, args: dict[str, Any]) -> None:
    if op not in OP_FIELDS:
        raise StoreUnavailable()
    shape(args, OP_FIELDS[op])
    for key, value in args.items():
        if key == "record":
            (session_record if op == "create_session" else user_record)(value)
        elif key == "user_id":
            text(value, 32, r"[a-f0-9]{32}")
        elif key in {"token_hash", "username_index", "account_key"}:
            text(value, 64, r"[a-f0-9]{64}")
        elif key in {"account_limit", "global_limit"}:
            integer(value, 1, 10000)
        elif key in {"account_window", "global_window"}:
            integer(value, 1, 86400)
        elif key == "keep":
            integer(value, 0, 32)
        elif key == "limit":
            integer(value, 1, 1000)
        else:
            integer(value)
    if op == "cas_last_seen" and args["new"] < args["old"]:
        raise StoreUnavailable()


def result_value(op: str, value: Any) -> Any:
    if op in {"get_user_by_id", "get_user_by_index"}:
        return None if value is None else user_record(value)
    if op == "get_session":
        return None if value is None else session_record(value)
    if op == "cas_last_seen":
        if type(value) is not bool:
            raise StoreUnavailable()
        return value
    if op == "count_user_sessions":
        return integer(value, 0, 2147483647)
    if value is not None:
        raise StoreUnavailable()
    return None
