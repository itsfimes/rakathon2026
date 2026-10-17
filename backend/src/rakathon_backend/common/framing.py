from __future__ import annotations

import hmac
import json
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from rakathon_backend.common.collection import checked_metadata
from rakathon_backend.common.errors import AuthError, TransportError


def frame_error(code: str, message: str, metadata: dict[str, Any] | None = None) -> bytes:
    detail = {
        "code": code,
        "message": message,
        **({"metadata": checked_metadata(metadata)} if metadata else {}),
    }
    return (json.dumps({"error": detail}) + "\n").encode()


def raise_frame_error(detail: Any) -> None:
    value = detail if isinstance(detail, dict) else {}
    code, message = (
        str(value.get("code", "remote_error")),
        str(value.get("message", "remote call failed")),
    )
    try:
        metadata = checked_metadata(value.get("metadata", {}))
    except ValueError as exc:
        raise TransportError(code="bad_frame", message="Invalid error metadata") from exc
    cls = AuthError if code in ("auth_failed", "spoofed_source") else TransportError
    raise cls(code=code, message=message, metadata=metadata)


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
