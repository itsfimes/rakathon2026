from __future__ import annotations

import time
import unicodedata

from rakathon_backend.b2.auth.models import AUTH_ROLES
from rakathon_backend.common.errors import ContractError

MAX_USERNAME_CHARS = 96
MIN_PASSWORD_CHARS = 15
MAX_PASSWORD_CHARS = 128
MAX_PASSWORD_BYTES = 1024


def system_clock() -> int:
    return int(time.time())


def normalize_username(raw: object) -> str:
    if not isinstance(raw, str):
        raise ContractError(code="bad_payload", message="username invalid")
    text = unicodedata.normalize("NFKC", raw).casefold()
    if not text or len(text) > MAX_USERNAME_CHARS:
        raise ContractError(code="bad_payload", message="username invalid")
    for ch in text:
        code = ord(ch)
        if code < 32 or code == 127:
            raise ContractError(code="bad_payload", message="username invalid")
        if ch in (" ", "\t", "\n", "\r", "/", "\\"):
            raise ContractError(code="bad_payload", message="username invalid")
    if text.count(".") != 1:
        raise ContractError(code="bad_payload", message="username invalid")
    first, second = text.split(".", 1)
    for part in (first, second):
        if not part:
            raise ContractError(code="bad_payload", message="username invalid")
        if part.startswith("-") or part.endswith("-"):
            raise ContractError(code="bad_payload", message="username invalid")
        if "--" in part:
            raise ContractError(code="bad_payload", message="username invalid")
        for ch in part:
            if ch == "-":
                continue
            if not ch.isalpha():
                raise ContractError(code="bad_payload", message="username invalid")
    return text


def validate_password(raw: object) -> str:
    if not isinstance(raw, str):
        raise ContractError(code="bad_payload", message="password invalid")
    if len(raw) < MIN_PASSWORD_CHARS or len(raw) > MAX_PASSWORD_CHARS:
        raise ContractError(code="bad_payload", message="password invalid")
    if len(raw.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ContractError(code="bad_payload", message="password invalid")
    return raw


def validate_role(raw: object) -> str:
    if not isinstance(raw, str) or raw not in AUTH_ROLES:
        raise ContractError(code="bad_payload", message="role invalid")
    return raw
