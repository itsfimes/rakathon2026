from __future__ import annotations

import os
import re
import secrets
import stat
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

KEY = re.compile(r"[A-Za-z0-9_-]{43}")


def proxy_key(path: Path) -> str:
    frontend = Path(__file__).resolve().parents[4] / "app"
    if path.resolve().is_relative_to(frontend):
        raise ValueError("proxy key must remain outside frontend")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(parent.is_symlink() for parent in (path.parent, *path.parent.parents)):
        raise ValueError("symlink key directory rejected")
    candidate = secrets.token_urlsafe(32)
    fd, temporary = tempfile.mkstemp(prefix=".web-key-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(candidate.encode("ascii"))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            candidate = ""
    finally:
        os.unlink(temporary)
    if candidate:
        return candidate
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise ValueError("unsafe proxy key file")
        raw = os.read(fd, 128).decode("ascii").strip()
        if KEY.fullmatch(raw) is None:
            raise ValueError("invalid proxy key file")
        return raw
    finally:
        os.close(fd)


def checked_origins(origins: list[str]) -> frozenset[str]:
    for origin in origins:
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
            or origin != f"{parsed.scheme}://{parsed.netloc}"
        ):
            raise ValueError("explicit origin required")
        _ = parsed.port
    return frozenset(origins)
