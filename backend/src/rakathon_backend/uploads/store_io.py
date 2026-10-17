from __future__ import annotations

import os
import tempfile
import urllib.parse as _up
from datetime import UTC, datetime
from pathlib import Path

from rakathon_backend.common.errors import ContractError

UUID_RE_LEN = 32


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def fsync_dir(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, str(path))
        fsync_dir(path.parent)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def valid_uuid(value: str) -> bool:
    if len(value) != UUID_RE_LEN:
        return False
    return all(c in "0123456789abcdef" for c in value.lower())


def sanitize_filename(raw: str) -> str:
    try:
        name = _up.unquote(raw, encoding="utf-8", errors="strict")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ContractError(code="bad_request", message="filename invalid") from exc
    name = name.split("/")[-1].split("\\")[-1].strip()
    if not name or len(name) > 128 or ".." in name:
        raise ContractError(code="bad_request", message="filename invalid")
    if any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ContractError(code="bad_request", message="filename invalid")
    return name
