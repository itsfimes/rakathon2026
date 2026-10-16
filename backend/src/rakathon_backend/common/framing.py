from __future__ import annotations

import hmac
import json
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def frame_error(code: str, message: str) -> bytes:
    return (json.dumps({"error": {"code": code, "message": message}}) + "\n").encode()


def lookup_service(registry: Mapping[str, str], token: Any) -> str | None:
    if not isinstance(token, str) or not token:
        return None
    try:
        ascii_ok = token.isascii()
    except (AttributeError, TypeError, UnicodeError):
        return None
    if not ascii_ok:
        return None
    found: str | None = None
    for candidate, service in registry.items():
        try:
            if not isinstance(candidate, str) or not candidate.isascii():
                continue
            if hmac.compare_digest(candidate, token):
                found = service
        except (TypeError, ValueError):
            continue
    return found


def is_socket(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    if path.is_symlink():
        return False
    return stat.S_ISSOCK(info.st_mode)


def encode_envelope_frame(body: dict[str, Any]) -> bytes:
    return (json.dumps(body) + "\n").encode()
